from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterator

_watch_paths = [
    Path.home() / "company" / ".agent-coordinator" / "state.json",
    Path.home() / ".hermes" / "memories" / "MEMORY.md",
]

_subscribers: list[queue.Queue[dict[str, Any]]] = []
_subscribers_lock = threading.Lock()
_watcher_started = False
_watcher_lock = threading.Lock()


def _publish(event: dict[str, Any]) -> None:
    with _subscribers_lock:
        subscribers = list(_subscribers)
    for subscriber in subscribers:
        subscriber.put(event)


def _event(path: str, source: str) -> dict[str, Any]:
    return {"type": "file_change", "path": path, "source": source, "time": time.time()}


def _existing_watch_paths() -> list[str]:
    return [str(path) for path in _watch_paths if path.exists()]


def _polling_thread(interval_seconds: int = 10) -> None:
    previous: dict[Path, float | None] = {}
    while True:
        for path in _watch_paths:
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                mtime = None
            if path not in previous:
                previous[path] = mtime
                continue
            if mtime != previous[path]:
                previous[path] = mtime
                _publish(_event(str(path), "polling"))
        time.sleep(interval_seconds)


def _fswatch_thread() -> None:
    paths = _existing_watch_paths()
    if not paths:
        _polling_thread()
        return

    cmd = ["fswatch", "--event-flags"] + paths
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        _polling_thread()
        return

    if proc.stdout is None:
        _polling_thread()
        return

    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        path = line.split("\t", 1)[0]
        _publish(_event(path, "fswatch"))

    _polling_thread()


def _watcher_thread() -> None:
    if shutil.which("fswatch"):
        _fswatch_thread()
        return
    _polling_thread()


def start_watcher() -> None:
    global _watcher_started
    with _watcher_lock:
        if _watcher_started:
            return
        _watcher_started = True
        thread = threading.Thread(target=_watcher_thread, daemon=True)
        thread.start()


def event_stream() -> Iterator[str]:
    start_watcher()
    subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
    with _subscribers_lock:
        _subscribers.append(subscriber)

    try:
        yield f"data: {json.dumps({'type': 'connected', 'time': time.time()})}\n\n"
        while True:
            try:
                event = subscriber.get(timeout=15)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat', 'time': time.time()})}\n\n"
    finally:
        with _subscribers_lock:
            if subscriber in _subscribers:
                _subscribers.remove(subscriber)
