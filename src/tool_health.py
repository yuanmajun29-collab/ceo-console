from __future__ import annotations

import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import DB_PATH
from .subscription_reminders import get_subscription_expiry_risks

TOOL_HEALTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_health (
    tool_name TEXT PRIMARY KEY,
    last_ok_at TEXT,
    last_check_at TEXT,
    last_status TEXT,
    last_error TEXT,
    ok_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0
)
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _run(command: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _ok(tool: str, message: str, suggestion: str = "") -> dict[str, Any]:
    return {
        "tool": tool,
        "status": "ok",
        "level": "ok",
        "error": None,
        "message": message,
        "suggestion": suggestion,
    }


def _fail(
    tool: str,
    status: str,
    level: str,
    error: str,
    message: str,
    suggestion: str,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "status": status,
        "level": level,
        "error": error,
        "message": message,
        "suggestion": suggestion,
    }


def _get_deepseek_key() -> str | None:
    """从 .env 读取 DeepSeek API Key"""
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text("utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("DEEPSEEK_API_KEY="):
            val = line.split("=", 1)[1].strip().strip("\"'")
            if val and val != "***":
                return val
    return None


def _call_deepseek_api(api_key: str, timeout: int = 10) -> tuple[int, str | None]:
    """调 DeepSeek API 验证 Key，返回 (http_status, error_message)"""
    import urllib.request, urllib.error
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return 0, str(e)


def _check_deepseek_tool(tool_name: str, api_key: str | None) -> dict[str, Any]:
    """检测使用 DeepSeek Key 的工具（Hermes / PilotDeck）"""
    if not api_key:
        return _fail(tool_name, "unavailable", "high",
                     "DeepSeek API Key 未配置",
                     f"{tool_name} DeepSeek Key 未配置",
                     "在 .env 或 pilotdeck.yaml 中配置 DeepSeek API Key")
    status, err = _call_deepseek_api(api_key)
    if status == 200:
        return _ok(tool_name, f"{tool_name} DeepSeek Key 有效", "无需操作")
    if status == 401:
        return _fail(tool_name, "unavailable", "high", err or "401 Unauthorized",
                     f"{tool_name} DeepSeek Key 已失效 (HTTP 401)",
                     "DeepSeek Key 过期或被撤销，请续费后更新 Key")
    if status == 429:
        return _fail(tool_name, "degraded", "warning", err or "429 Rate Limit",
                     f"{tool_name} DeepSeek 额度已用完 (HTTP 429)",
                     "DeepSeek 免费额度已用完，请续费")
    return _fail(tool_name, "degraded", "warning", err or f"HTTP {status}",
                 f"{tool_name} DeepSeek API 返回异常 (HTTP {status})",
                 "检查网络连接或 DeepSeek 服务状态")


def _get_pilotdeck_key() -> str | None:
    """从 pilotdeck.yaml 读取 DeepSeek API Key（用正则，避免 yaml 依赖）"""
    import re
    yaml_path = Path.home() / ".pilotdeck" / "pilotdeck.yaml"
    if not yaml_path.exists():
        return None
    try:
        content = yaml_path.read_text("utf-8", errors="replace")
        m = re.search(r'apiKey:\s*(\S+)', content)
        if m:
            return m.group(1)
    except Exception:
        return None
    return None


def _check_hermes() -> dict[str, Any]:
    key = _get_deepseek_key()
    return _check_deepseek_tool("Hermes", key)


def _check_pilotdeck() -> dict[str, Any]:
    key = _get_pilotdeck_key()
    return _check_deepseek_tool("PilotDeck", key)


def _check_claude() -> dict[str, Any]:
    """检测 Claude Desktop App 是否可用"""
    app_path = Path("/Applications/Claude.app")
    claude_cli = shutil.which("claude")
    if app_path.exists():
        if claude_cli:
            return _ok("Claude Code", "Claude.app 已安装，CLI 命令可用", "无需操作")
        return _ok("Claude Code", "Claude.app 已安装", "如需 CLI 命令，安装 Claude Code")
    if claude_cli:
        return _fail("Claude Code", "degraded", "warning", "Claude.app not found",
                     "Claude CLI 可用但桌面 App 未安装", "安装 Claude Desktop App")
    return _fail("Claude Code", "unavailable", "high", "Claude.app and claude CLI not found",
                 "Claude Code 未安装", "安装 Claude Desktop App")


def _check_codex() -> dict[str, Any]:
    """检测 Codex 桌面 App 是否可运行"""
    app_path = Path("/Applications/Codex.app")
    codex_cli = shutil.which("codex")
    if app_path.exists():
        if codex_cli:
            return _ok("Codex", "Codex.app 已安装，CLI 命令可用", "无需操作")
        return _ok("Codex", "Codex.app 已安装", "如需 CLI 命令，确保 codex 在 PATH 中")
    if codex_cli:
        return _ok("Codex", "Codex CLI 命令可用", "建议安装 Codex Desktop App")
    return _fail("Codex", "unavailable", "high", "Codex.app and codex CLI not found",
                 "Codex 未安装", "安装 Codex Desktop App")


def _check_gemini() -> dict[str, Any]:
    """检测 Gemini CLI 是否已安装配置"""
    cli = shutil.which("gemini")
    if cli:
        return _ok("Gemini CLI", "Gemini CLI 命令可用", "无需操作")
    return _fail("Gemini CLI", "unavailable", "high", "gemini CLI not found",
                 "Gemini CLI 未安装", "通过 Homebrew 安装 Gemini CLI")


def _check_cursor() -> dict[str, Any]:
    """检测 Cursor 桌面 App 是否可运行"""
    app_path = Path("/Applications/Cursor.app")
    cursor_cli = shutil.which("cursor")
    if app_path.exists() and cursor_cli:
        return _ok("Cursor", "Cursor.app 已安装，CLI 命令可用", "无需操作")
    if app_path.exists():
        return _ok("Cursor", "Cursor.app 已安装", "如需 CLI 命令，启用 Shell Command")
    if cursor_cli:
        return _fail("Cursor", "degraded", "warning", "Cursor.app not found",
                     "Cursor CLI 可用但桌面 App 未安装", "安装 Cursor Desktop App")
    return _fail("Cursor", "unavailable", "high", "Cursor.app and CLI not found",
                 "Cursor 未安装", "安装 Cursor Desktop App")


def _check_openclaw() -> dict[str, Any]:
    """检查 OpenClaw 配置是否完整"""
    path = shutil.which("openclaw")
    if not path:
        return _fail("OpenClaw", "unavailable", "high", "openclaw not found", "OpenClaw 命令不可用", "安装 OpenClaw")
    try:
        proc = _run([path, "--version"])
    except Exception as exc:
        return _fail("OpenClaw", "unavailable", "high", str(exc), "OpenClaw 不可用", "检查 OpenClaw 安装")
    if proc.returncode != 0:
        return _fail("OpenClaw", "degraded", "warning", (proc.stderr or "")[:200], "OpenClaw 配置异常", "检查 OpenClaw 配置")
    return _ok("OpenClaw", "OpenClaw 配置正常", "无需操作")


def _cli_auth_check(tool: str, cmd: list[str], suggestion: str) -> dict[str, Any]:
    """通用 CLI 认证检测"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return _ok(tool, f"{tool} 登录有效", "无需操作")
        err = (r.stderr or r.stdout or f"exit {r.returncode}").strip()[:200]
        return _fail(tool, "unavailable", "high", err, f"{tool} 登录已过期", suggestion)
    except FileNotFoundError:
        return _fail(tool, "unavailable", "high", "command not found", f"{tool} 未安装", f"安装 {tool}")
    except subprocess.TimeoutExpired:
        return _fail(tool, "degraded", "warning", "timeout", f"{tool} 检测超时", suggestion)


def _check_codex() -> dict[str, Any]:
    return _cli_auth_check("Codex", ["codex", "exec", "echo ok"], "重新运行 codex login 登录")


def _check_gemini() -> dict[str, Any]:
    return _cli_auth_check("Gemini CLI", ["gemini", "-p", "ok"], "检查 GEMINI_API_KEY 或刷新免费额度")


def _check_cursor() -> dict[str, Any]:
    cmd = shutil.which("cursor")
    if cmd:
        return _ok("Cursor", "Cursor 命令可用", "无需操作")
    return _fail("Cursor", "unavailable", "high", "cursor not found", "Cursor 命令不可用", "安装 Cursor")


def _check_antigravity() -> dict[str, Any]:
    path = Path.home() / ".antigravity"
    if path.exists() and path.is_dir():
        return _ok("Antigravity", "Antigravity 配置目录存在", "无需操作")
    return _fail("Antigravity", "unavailable", "high", str(path), "Antigravity 配置目录不存在", "重新初始化 Antigravity 配置")


def _check_obsidian_vault() -> dict[str, Any]:
    path = Path.home() / "Documents" / "Obsidian Vault"
    if path.exists() and path.is_dir():
        return _ok("Obsidian Vault", "Obsidian Vault 目录存在", "无需操作")
    return _fail("Obsidian Vault", "unavailable", "high", str(path), "Obsidian Vault 目录不存在", "检查 ~/Documents/Obsidian Vault 路径")


TOOL_CHECKS: dict[str, Callable[[], dict[str, Any]]] = {
    "Hermes": _check_hermes,
    "Cursor": _check_cursor,
    "Claude Code": _check_claude,
    "Codex": _check_codex,
    "Gemini CLI": _check_gemini,
    "PilotDeck": _check_pilotdeck,
    "OpenClaw": _check_openclaw,
    "Antigravity": _check_antigravity,
    "Obsidian Vault": _check_obsidian_vault,
}


def _connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(TOOL_HEALTH_SCHEMA)
    conn.commit()
    return conn


def _persist_result(conn: sqlite3.Connection, result: dict[str, Any], checked_at: str) -> dict[str, Any]:
    tool_name = str(result["tool"])
    existing = conn.execute("SELECT * FROM tool_health WHERE tool_name = ?", (tool_name,)).fetchone()
    was_ok = result["status"] == "ok"
    last_ok_at = checked_at if was_ok else (existing["last_ok_at"] if existing else None)
    ok_count = (int(existing["ok_count"] or 0) + 1) if was_ok and existing else (1 if was_ok else 0)
    fail_count = 0 if was_ok else ((int(existing["fail_count"] or 0) + 1) if existing else 1)
    conn.execute(
        """
        INSERT INTO tool_health (
            tool_name, last_ok_at, last_check_at, last_status, last_error, ok_count, fail_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tool_name) DO UPDATE SET
            last_ok_at = excluded.last_ok_at,
            last_check_at = excluded.last_check_at,
            last_status = excluded.last_status,
            last_error = excluded.last_error,
            ok_count = excluded.ok_count,
            fail_count = excluded.fail_count
        """,
        (
            tool_name,
            last_ok_at,
            checked_at,
            result["status"],
            result.get("error"),
            ok_count,
            fail_count,
        ),
    )
    result["last_known_ok"] = last_ok_at
    result["last_check_at"] = checked_at
    result["ok_count"] = ok_count
    result["fail_count"] = fail_count
    return result


def _human_since(last_ok_at: str | None, checked_at: str) -> str | None:
    if not last_ok_at:
        return None
    try:
        delta = datetime.fromisoformat(checked_at) - datetime.fromisoformat(last_ok_at)
    except ValueError:
        return None
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return f"{seconds} seconds ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hours ago"
    return f"{hours // 24} days ago"


def check_all_tools() -> list[dict[str, Any]]:
    """Check all registered tools, persist health, and return degraded risk items."""
    checked_at = _now()
    risks: list[dict[str, Any]] = []
    with _connect() as conn:
        for tool_name, checker in TOOL_CHECKS.items():
            try:
                result = checker()
            except Exception as exc:
                result = _fail(tool_name, "unavailable", "high", str(exc), f"{tool_name} 健康检测异常", "查看配置并重新运行健康检测。")
            result = _persist_result(conn, result, checked_at)
            if result["status"] != "ok":
                risks.append(
                    {
                        "type": "tool_degraded",
                        "level": result["level"],
                        "tool": tool_name,
                        "status": result["status"],
                        "last_known_ok": result.get("last_known_ok"),
                        "last_check_at": checked_at,
                        "since": _human_since(result.get("last_known_ok"), checked_at),
                        "message": result["message"],
                        "suggestion": result["suggestion"],
                        "fail_count": result["fail_count"],
                    }
                )
        conn.commit()
    risks.extend(get_subscription_expiry_risks(7))
    return risks


def get_tool_health_status() -> list[dict[str, Any]]:
    """Read the latest persisted health records for all known tools."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT tool_name, last_ok_at, last_check_at, last_status, last_error, ok_count, fail_count
            FROM tool_health
            ORDER BY tool_name ASC
            """
        ).fetchall()
    by_name = {
        row["tool_name"]: {
            "tool": row["tool_name"],
            "last_ok_at": row["last_ok_at"],
            "last_check_at": row["last_check_at"],
            "status": row["last_status"],
            "last_error": row["last_error"],
            "ok_count": row["ok_count"],
            "fail_count": row["fail_count"],
        }
        for row in rows
    }
    return [
        by_name.get(
            name,
            {
                "tool": name,
                "last_ok_at": None,
                "last_check_at": None,
                "status": "unknown",
                "last_error": None,
                "ok_count": 0,
                "fail_count": 0,
            },
        )
        for name in TOOL_CHECKS
    ]
