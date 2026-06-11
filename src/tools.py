from __future__ import annotations

import os
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import *

_TOOL_STATUS_CACHE: dict[str, Any] = {"ts": None, "data": None}

def tool_candidates(tool_name: str) -> list[str]:
    mapping = {
        "Claude Code": ["claude"],
        "Codex": ["codex"],
        "Gemini": ["gemini"],
        # For headless dispatch we must prefer OpenClaw CLI over GUI launcher.
        "Antigravity": ["openclaw", "antigravity"],
        "Cursor": ["cursor", "cursor-agent"],
        "Hermes": ["hermes", "hermes-agent"],
        "DeepSeek V4-Pro": ["deepseek", "deepseek-v4-pro"],
        "PilotDeck": ["pilotdeck"],
        "Obsidian": ["obsidian"],
    }
    if tool_name in mapping:
        return mapping[tool_name]
    registry = get_acp_agent_registry()
    target = (registry.get(tool_name) or {}).get("target")
    return [target, slugify_acp_target(tool_name)] if target else [slugify_acp_target(tool_name)]


def resolve_tool_command(tool_name: str) -> str | None:
    extra_dirs = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        str(Path.home() / ".antigravity" / "antigravity" / "bin"),
        str(Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin"),
        str(Path.home() / ".hermes" / "hermes-agent"),
        str(Path.home() / ".hermes" / "bin"),
        str(Path.home() / ".pilotdeck" / "app" / "bin"),
        str(Path.home() / "Library" / "Python" / "3.9" / "bin"),
    ]
    if tool_name == "PilotDeck":
        pilotdeck = Path.home() / ".pilotdeck" / "app" / "bin" / "pilotdeck"
        if pilotdeck.exists() and os.access(pilotdeck, os.X_OK):
            return str(pilotdeck)
    if tool_name == "Obsidian":
        vault = Path.home() / "Documents" / "Obsidian Vault"
        if vault.exists():
            return "obsidian://open?vault=Obsidian%20Vault"
    for c in tool_candidates(tool_name):
        found = shutil.which(c)
        if found:
            return found
        for d in extra_dirs:
            cand = Path(d) / c
            if cand.exists() and os.access(cand, os.X_OK):
                return str(cand)
    return None


def build_tool_run_command(tool_name: str, prompt: str) -> tuple[list[str] | None, str | None]:
    acp_scripts = get_acp_scripts()
    acp_agent = acp_scripts["agent"]
    acp_entry = get_acp_agent_registry().get(tool_name) or {}
    acp_target = acp_entry.get("target") or ACP_TOOL_TARGET.get(tool_name)
    acp_configured_for_tool = bool(acp_entry.get("configured") or tool_name != "DeepSeek V4-Pro")
    if acp_target and acp_agent["exists"] and acp_agent["executable"] and acp_configured_for_tool:
        agent_path = acp_agent["path"]
        if tool_name == "Claude Code":
            return [agent_path, acp_target, "-p", "--output-format", "text", prompt], None
        if tool_name == "Gemini":
            return [agent_path, acp_target, prompt], None
        if tool_name == "Codex":
            return [
                agent_path,
                acp_target,
                "exec",
                "--skip-git-repo-check",
                "--sandbox",
                "workspace-write",
                "--color",
                "never",
                prompt,
            ], None
        if tool_name == "Antigravity":
            return [agent_path, acp_target, "agent", "--local", "--agent", "main", "--message", prompt, "--json"], None
        if tool_name == "Cursor":
            return None, "Cursor ACP 当前会打开 IDE 交互窗口，不适合后台无头调度。请改用 Claude/Gemini/Antigravity/Codex。"
        if tool_name == "Hermes":
            cmd_path = resolve_tool_command(tool_name)
            if cmd_path:
                return [cmd_path, "--accept-hooks", "-z", prompt], None
            return None, "Hermes 已检测到 ACP/Hook 配置，但 hermes 命令不可执行；请把 ~/.hermes/hermes-agent/venv/bin 加入 PATH。"
        if tool_name == "DeepSeek V4-Pro":
            return [agent_path, acp_target, prompt], None
        return [agent_path, acp_target, prompt], None

    if tool_name == "DeepSeek V4-Pro":
        api_key = os.getenv("CEO_CONSOLE_DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        if api_key:
            script = """
import json
import os
import sys
import urllib.error
import urllib.request

prompt = sys.argv[1]
api_key = os.getenv("CEO_CONSOLE_DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
base_url = (os.getenv("CEO_CONSOLE_DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
model = os.getenv("CEO_CONSOLE_DEEPSEEK_MODEL") or "deepseek-chat"
payload = json.dumps({
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.2,
}, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request(
    f"{base_url}/chat/completions",
    data=payload,
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
except urllib.error.HTTPError as exc:
    sys.stderr.write(exc.read().decode("utf-8", errors="replace"))
    sys.exit(1)
content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
print(content or json.dumps(data, ensure_ascii=False))
""".strip()
            return [sys.executable, "-c", script, prompt], None

    cmd_path = resolve_tool_command(tool_name)
    if not cmd_path:
        if tool_name == "DeepSeek V4-Pro":
            return None, "DeepSeek V4-Pro 未配置 ACP 目标、API Key 或本地 deepseek 命令；请设置 DEEPSEEK_API_KEY / CEO_CONSOLE_DEEPSEEK_API_KEY，或在 ACP 中接入 deepseek-v4-pro。"
        return None, f"未找到可执行命令候选：{tool_candidates(tool_name)}"

    # Prefer non-interactive execution where supported.
    if tool_name == "Claude Code":
        return [cmd_path, "-p", "--output-format", "text", prompt], None
    if tool_name == "Gemini":
        return [cmd_path, "-p", prompt], None
    if tool_name == "Antigravity":
        # Antigravity/OpenClaw supports headless agent turns via local mode.
        # Force explicit agent to avoid "choose a session" interactive prompt.
        return [cmd_path, "agent", "--local", "--agent", "main", "--message", prompt, "--json"], None
    if tool_name == "Codex":
        # Use the non-interactive runner so backend dispatch does not require a TTY.
        return [cmd_path, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "--color", "never", prompt], None
    if tool_name == "Cursor":
        return None, "Cursor CLI 当前用于打开IDE窗口，不支持稳定的无头自动执行。请改用 Claude/Gemini/Antigravity/Codex。"
    if tool_name == "Hermes":
        return [cmd_path, "--accept-hooks", "-z", prompt], None

    return [cmd_path, prompt], None


BACKGROUND_UNSUPPORTED_TOOLS = {"Cursor", "Other"}
TASK_TYPE_FALLBACK_TOOLS = {
    "market_research": ["Gemini", "DeepSeek V4-Pro", "Claude Code", "Codex", "Antigravity"],
    "architecture": ["Claude Code", "Gemini", "Codex", "DeepSeek V4-Pro", "Antigravity"],
    "fullstack": ["Antigravity", "Codex", "Claude Code", "DeepSeek V4-Pro", "Gemini"],
    "code_edit": ["Codex", "DeepSeek V4-Pro", "Claude Code", "Gemini", "Antigravity"],
    "testing": ["Codex", "DeepSeek V4-Pro", "Claude Code", "Gemini", "Antigravity"],
    "docs": ["Codex", "DeepSeek V4-Pro", "Claude Code", "Gemini", "Antigravity"],
    "security_review": ["Gemini", "Claude Code", "Codex", "DeepSeek V4-Pro", "Antigravity"],
    "quality_review": ["Claude Code", "Codex", "Gemini", "DeepSeek V4-Pro", "Antigravity"],
    "delivery": ["Codex", "DeepSeek V4-Pro", "Claude Code", "Gemini", "Antigravity"],
    "customer_triage": ["Gemini", "DeepSeek V4-Pro", "Claude Code", "Codex"],
    "contract_review": ["Claude Code", "DeepSeek V4-Pro", "Codex", "Gemini"],
    "bookkeeping": ["DeepSeek V4-Pro", "Codex", "Gemini", "Claude Code"],
    "finance_report": ["DeepSeek V4-Pro", "Claude Code", "Codex", "Gemini"],
    "marketing_content": ["DeepSeek V4-Pro", "Claude Code", "Gemini", "Codex"],
    "social_monitor": ["Gemini", "DeepSeek V4-Pro", "Claude Code", "Codex"],
}
DEFAULT_BACKGROUND_FALLBACK_TOOLS = ["DeepSeek V4-Pro", "Codex", "Claude Code", "Gemini", "Antigravity"]


def dedupe_tools(tools: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tool in tools:
        if not tool or tool in seen:
            continue
        seen.add(tool)
        out.append(tool)
    return out


def is_runnable_tool(tool_name: str, status: dict[str, Any] | None = None) -> bool:
    if tool_name in BACKGROUND_UNSUPPORTED_TOOLS:
        return False
    info = (status or get_tools_status_cached()).get(tool_name) or {}
    return bool(info.get("available") and info.get("runnable"))


def tool_unavailable_reason(tool_name: str, status: dict[str, Any] | None = None) -> str:
    if tool_name == "Other":
        return "未指定具体后台工具"
    if tool_name == "Cursor":
        return "Cursor 当前作为人工精修入口，不参与后台自动调度"
    info = (status or {}).get(tool_name)
    if not info:
        return "未纳入工具状态监测"
    if not info.get("available"):
        return "命令或 ACP 目标不可用"
    if not info.get("runnable"):
        return str(info.get("reason") or "不支持后台无头调度")
    return "可调度"


def fallback_tools_for_task(task_type: str | None) -> list[str]:
    normalized = normalize_task_type(task_type)
    return TASK_TYPE_FALLBACK_TOOLS.get(normalized, DEFAULT_BACKGROUND_FALLBACK_TOOLS)


def pick_fallback_tool(preferred_tools: list[str] | None = None) -> tuple[str | None, str | None]:
    ordered = preferred_tools or DEFAULT_BACKGROUND_FALLBACK_TOOLS
    status = get_tools_status_cached()
    for tool in ordered:
        if is_runnable_tool(tool, status):
            return tool, None
    return None, "未找到可自动调度的后备工具"


def check_command_runnable(path: str) -> tuple[bool, str | None]:
    now = time.time()
    runnable_cache = _TOOL_STATUS_CACHE.setdefault("runnable_checks", {})
    cached = runnable_cache.get(path)
    if cached and now - cached["ts"] < 60:
        return cached["result"]

    try:
        # Quick smoke check: many CLIs support --help without side effects.
        res = subprocess.run(
            [path, "--help"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=8,
        )
        if res.returncode == 0:
            result = (True, None)
            runnable_cache[path] = {"ts": now, "result": result}
            return result
        err = (res.stderr or res.stdout or "").strip()
        result = (False, err[:400])
    except Exception as exc:
        result = (False, str(exc))
    runnable_cache[path] = {"ts": now, "result": result}
    return result


def quota_env_key(tool_name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", tool_name.upper()).strip("_")


def get_recharge_url(tool_name: str, raw: dict[str, Any] | None = None) -> str | None:
    raw_url = (raw or {}).get("recharge_url")
    if raw_url:
        return str(raw_url)
    key = quota_env_key(tool_name)
    env_url = os.getenv(f"CEO_CONSOLE_RECHARGE_{key}_URL")
    if env_url:
        return env_url
    return DEFAULT_RECHARGE_URLS.get(tool_name)


def normalize_quota(tool_name: str, raw: dict[str, Any] | None, source: str) -> dict[str, Any]:
    if not raw:
        return {
            "available": False,
            "source": "not_configured",
            "label": "未接入",
            "remaining": None,
            "limit": None,
            "unit": "tokens",
            "percent": None,
            "reset_at": None,
            "recharge_url": get_recharge_url(tool_name),
        }
    unit = str(raw.get("unit") or "tokens")
    remaining = raw.get("remaining")
    limit = raw.get("limit")
    try:
        remaining_num = float(remaining) if remaining not in (None, "") else None
    except (TypeError, ValueError):
        remaining_num = None
    try:
        limit_num = float(limit) if limit not in (None, "") else None
    except (TypeError, ValueError):
        limit_num = None
    percent = None
    if remaining_num is not None and limit_num and limit_num > 0:
        percent = max(0, min(100, round((remaining_num / limit_num) * 100)))
    label = str(raw.get("label") or "").strip()
    if not label:
        if remaining_num is not None and limit_num:
            label = f"{remaining_num:g}/{limit_num:g} {unit}"
        elif remaining_num is not None:
            label = f"{remaining_num:g} {unit}"
        else:
            label = "待同步"
    return {
        "available": True,
        "source": source,
        "label": label,
        "remaining": remaining_num,
        "limit": limit_num,
        "unit": unit,
        "percent": percent,
        "reset_at": raw.get("reset_at"),
        "recharge_url": get_recharge_url(tool_name, raw),
        "tool": tool_name,
    }


def get_tool_quota(tool_name: str) -> dict[str, Any]:
    quota_json = os.getenv("CEO_CONSOLE_AI_QUOTA_JSON", "").strip()
    if quota_json:
        try:
            quota_data = json.loads(quota_json)
            raw = quota_data.get(tool_name) or quota_data.get(quota_env_key(tool_name))
            if isinstance(raw, dict):
                return normalize_quota(tool_name, raw, "env_json")
        except json.JSONDecodeError:
            return {
                "available": False,
                "source": "env_json_error",
                "label": "配置错误",
                "remaining": None,
                "limit": None,
                "unit": "tokens",
                "percent": None,
                "reset_at": None,
                "recharge_url": get_recharge_url(tool_name),
            }

    key = quota_env_key(tool_name)
    raw = {
        "remaining": os.getenv(f"CEO_CONSOLE_QUOTA_{key}_REMAINING"),
        "limit": os.getenv(f"CEO_CONSOLE_QUOTA_{key}_LIMIT"),
        "unit": os.getenv(f"CEO_CONSOLE_QUOTA_{key}_UNIT") or "tokens",
        "reset_at": os.getenv(f"CEO_CONSOLE_QUOTA_{key}_RESET_AT"),
        "label": os.getenv(f"CEO_CONSOLE_QUOTA_{key}_LABEL"),
        "recharge_url": os.getenv(f"CEO_CONSOLE_RECHARGE_{key}_URL"),
    }
    if any(raw.get(field) for field in ["remaining", "limit", "reset_at", "label"]):
        return normalize_quota(tool_name, raw, "env")
    return normalize_quota(tool_name, None, "not_configured")


def get_tools_status_cached() -> dict[str, Any]:
    now = datetime.now()
    ts = _TOOL_STATUS_CACHE.get("ts")
    if ts and _TOOL_STATUS_CACHE.get("data") is not None:
        if (now - ts).total_seconds() < 60:
            return _TOOL_STATUS_CACHE["data"]

    headless_support = {
        "Cursor": False,
        "Antigravity": True,
        "Claude Code": True,
        "Codex": True,
        "Gemini": True,
        "DeepSeek V4-Pro": True,
        "PilotDeck": False,
        "Obsidian": False,
    }
    data: dict[str, Any] = {}
    acp_scripts = get_acp_scripts()
    registry = get_acp_agent_registry()
    for tool, acp_entry in registry.items():
        command = resolve_tool_command(tool)
        deepseek_api_enabled = tool == "DeepSeek V4-Pro" and bool(os.getenv("CEO_CONSOLE_DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY"))
        acp_requires_config = tool == "DeepSeek V4-Pro"
        acp_enabled = bool(
            acp_scripts["agent"]["exists"]
            and acp_scripts["agent"]["executable"]
            and acp_entry.get("target")
            and (not acp_requires_config or acp_entry.get("configured"))
        )
        probe_runnable = acp_entry.get("runnable")
        available = command is not None or acp_enabled or deepseek_api_enabled or probe_runnable is True
        runnable = False
        reason = None
        if available and probe_runnable is not None and not headless_support.get(tool, True):
            runnable = bool(probe_runnable)
            reason = None if runnable else "本地探测不可用。"
        elif available and command and headless_support.get(tool, True):
            runnable, reason = check_command_runnable(command)
        elif available and acp_enabled and headless_support.get(tool, True):
            runnable = True
            reason = "通过 ACP 动态接入，按通用 Agent 目标调度。"
        elif available and deepseek_api_enabled:
            runnable = True
            reason = "通过 DeepSeek API 接入，适合低成本批量摘要、草稿和结构化任务。"
        elif available and not headless_support.get(tool, True):
            runnable = False
            reason = "该工具当前仅支持交互模式，不支持后台无头自动执行。"
        data[tool] = {
            "available": available,
            "runnable": runnable if available else False,
            "command": command,
            "candidates": tool_candidates(tool),
            "reason": reason,
            "quota": get_tool_quota(tool),
            "acp_target": acp_entry.get("target"),
            "acp_enabled": acp_enabled,
            "acp_configured": bool(acp_entry.get("configured") or acp_enabled),
            "dynamic_acp": not bool(acp_entry.get("builtin")),
            "source": acp_entry.get("source") or "fixed",
            "agent_type": acp_entry.get("agent_type"),
            "meta": acp_entry.get("meta") or {},
        }

    _TOOL_STATUS_CACHE["ts"] = now
    _TOOL_STATUS_CACHE["data"] = data
    return data


def estimate_context_size(title: str = "", notes: str = "", locked_scope: str = "", acceptance: str = "") -> dict[str, Any]:
    text = f"{title}\n{notes}\n{locked_scope}\n{acceptance}"
    char_count = len(text)
    scope_count = len([part for part in re.split(r"[,，\n\s]+", locked_scope or "") if part.strip()])
    if char_count <= 600 and scope_count <= 2:
        level = "small"
        label = "小上下文"
    elif char_count <= 2200 and scope_count <= 8:
        level = "medium"
        label = "中上下文"
    else:
        level = "large"
        label = "大上下文"
    return {"level": level, "label": label, "char_count": char_count, "scope_count": scope_count}


def infer_project_profile(project: str = "", locked_scope: str = "") -> dict[str, Any]:
    company_dir, _ = resolve_company_dir()
    project_path = company_dir / project if project else None
    scope_text = locked_scope.lower()
    signals: set[str] = set()
    domains: set[str] = set()
    scope_domains: set[str] = set()

    def mark(domain: str, signal: str, from_scope: bool = False) -> None:
        domains.add(domain)
        signals.add(signal)
        if from_scope:
            scope_domains.add(domain)

    if any(k in scope_text for k in ["frontend", "web", ".vue", ".tsx", ".jsx", "package.json"]):
        mark("frontend", "locked_scope", True)
    if any(k in scope_text for k in ["backend", "server", ".py", ".java", ".kt", "api"]):
        mark("backend", "locked_scope", True)
    if any(k in scope_text for k in ["android", ".kt", "gradle"]):
        mark("android", "locked_scope", True)
    if any(k in scope_text for k in ["docker", "deploy", "k8s", "systemd", "nginx"]):
        mark("devops", "locked_scope", True)
    if any(k in scope_text for k in ["gate", "edge", "mqtt", "wavegate"]):
        mark("edge", "locked_scope", True)
    if any(k in scope_text for k in ["docs", "adr", ".md"]):
        mark("docs", "locked_scope", True)

    if project_path and project_path.exists():
        checks = [
            ("frontend", "package.json", project_path / "package.json"),
            ("frontend", "frontend/", project_path / "frontend"),
            ("frontend", "src/web", project_path / "src" / "web"),
            ("backend", "backend/", project_path / "backend"),
            ("backend", "java/", project_path / "java"),
            ("backend", "pyproject.toml", project_path / "pyproject.toml"),
            ("android", "android/", project_path / "android"),
            ("devops", "docker-compose.yml", project_path / "docker-compose.yml"),
            ("devops", "deploy/", project_path / "deploy"),
            ("edge", "src/gate", project_path / "src" / "gate"),
            ("docs", "docs/", project_path / "docs"),
        ]
        for domain, signal, path in checks:
            if path.exists():
                mark(domain, signal)

    nature_domains = scope_domains or domains
    if "edge" in nature_domains:
        archetype = "edge"
    elif "android" in nature_domains:
        archetype = "mobile"
    elif "devops" in nature_domains:
        archetype = "devops"
    elif {"frontend", "backend"}.issubset(nature_domains):
        archetype = "fullstack"
    elif "frontend" in nature_domains:
        archetype = "frontend"
    elif "backend" in nature_domains:
        archetype = "backend"
    elif "docs" in nature_domains:
        archetype = "docs"
    else:
        archetype = "unknown"
    return {
        "project": project or None,
        "archetype": archetype,
        "domains": sorted(domains),
        "scope_domains": sorted(scope_domains),
        "signals": sorted(signals),
    }


def adapt_pipeline_for_project(
    task_type: str,
    preferred_tool: str,
    pipeline: list[str],
    project_profile: dict[str, Any],
    context_level: str,
) -> tuple[str, list[str], str | None]:
    archetype = project_profile.get("archetype")
    domains = set(project_profile.get("domains") or [])
    note = None

    if task_type == "fullstack":
        if archetype == "fullstack":
            preferred_tool = "Antigravity"
            pipeline = ["Codex", "Antigravity", "Codex", "Claude Code"]
            note = "项目同时包含前后端，适合 Antigravity 做端到端集成，Codex 负责压缩与验收。"
        elif archetype in {"backend", "edge", "mobile", "devops"} or (domains & {"backend", "edge", "android", "devops"} and "frontend" not in domains):
            preferred_tool = "Codex"
            pipeline = ["Codex", "Claude Code"]
            note = "项目更偏后端/边缘/移动/部署，先用 Codex 做局部实现，复杂设计再交 Claude Code 复核，避免启动全栈 agent。"

    if task_type in {"code_edit", "testing", "docs", "delivery"}:
        preferred_tool = "Codex"
        pipeline = ["Codex", "Cursor"] if task_type == "code_edit" and context_level == "small" else ["Codex"]
        note = "任务属于明确执行型工作，Codex 成本最低；Cursor 仅保留为人工精修入口。"

    if task_type == "security_review" and domains & {"edge", "devops", "backend"}:
        preferred_tool = "Gemini"
        pipeline = ["Codex", "Gemini", "Codex"]
        note = "项目包含后端/边缘/部署风险面，先由 Codex 汇总范围，再用 Gemini 做广域安全扫描。"

    if task_type in {"architecture", "quality_review"}:
        preferred_tool = "Claude Code"
        pipeline = ["Codex", "Claude Code", "Codex"] if task_type == "architecture" else ["Codex", "Claude Code"]
        note = "架构/质量判断更适合 Claude Code，但先由 Codex 准备精简上下文。"

    return preferred_tool, pipeline, note


def tool_route_item(tool: str, index: int, primary_tool: str, status: dict[str, Any] | None = None) -> dict[str, Any]:
    info = (status or {}).get(tool) or {}
    return {
        "tool": tool,
        "acp_target": info.get("acp_target") or ACP_TOOL_TARGET.get(tool) or (get_acp_agent_registry().get(tool) or {}).get("target"),
        "token_cost": TOOL_TOKEN_PROFILE.get(tool, {}).get("cost"),
        "tier": TOOL_TOKEN_PROFILE.get(tool, {}).get("tier"),
        "role": pipeline_role(tool, index, primary_tool),
        "available": info.get("available"),
        "runnable": info.get("runnable"),
        "source": info.get("source"),
    }


def route_candidate_order(
    task_type: str,
    preferred_tool: str,
    pipeline: list[str],
    status: dict[str, Any] | None = None,
) -> list[str]:
    dynamic_runnable = []
    if status:
        dynamic_runnable = [
            name for name, info in status.items()
            if name not in ALLOWED_AI and info.get("available") and info.get("runnable")
        ]
    return dedupe_tools([preferred_tool, *fallback_tools_for_task(task_type), *pipeline, *dynamic_runnable])


def apply_route_availability(
    task_type: str,
    preferred_tool: str,
    pipeline: list[str],
    status: dict[str, Any] | None,
) -> dict[str, Any]:
    if status is None:
        return {
            "primary_tool": preferred_tool,
            "execution_pipeline": [tool_route_item(tool, idx, preferred_tool) for idx, tool in enumerate(pipeline)],
            "dispatch_candidates": pipeline[:],
            "skipped_tools": [],
            "availability_checked": False,
            "fallback_applied": False,
        }

    candidates = route_candidate_order(task_type, preferred_tool, pipeline, status)
    execution_pipeline: list[dict[str, Any]] = []
    skipped_tools: list[dict[str, Any]] = []
    for tool in candidates:
        if is_runnable_tool(tool, status):
            execution_pipeline.append(tool_route_item(tool, len(execution_pipeline), preferred_tool, status))
        else:
            skipped_tools.append({"tool": tool, "reason": tool_unavailable_reason(tool, status)})

    selected = execution_pipeline[0]["tool"] if execution_pipeline else preferred_tool
    return {
        "primary_tool": selected,
        "execution_pipeline": execution_pipeline,
        "dispatch_candidates": [step["tool"] for step in execution_pipeline],
        "skipped_tools": skipped_tools,
        "availability_checked": True,
        "fallback_applied": selected != preferred_tool,
    }


def format_route_plan_reason(plan: dict[str, Any]) -> str:
    strategic = " → ".join(step["tool"] for step in plan.get("pipeline", [])) or plan.get("primary_tool", "-")
    execution = " → ".join(step["tool"] for step in plan.get("execution_pipeline", [])) or "暂无可执行节点"
    reason = f"{plan.get('reason') or ''} Token 优先链路：{strategic}。可执行链路：{execution}。"
    if plan.get("fallback_applied"):
        reason += f"主节点 {plan.get('recommended_tool')} 当前不可用，已自动切换到 {plan.get('primary_tool')}。"
    skipped = plan.get("skipped_tools") or []
    if skipped:
        short = "；".join(f"{item['tool']}：{item['reason']}" for item in skipped[:4])
        suffix = "；..." if len(skipped) > 4 else ""
        reason += f"已跳过不可用节点：{short}{suffix}。"
    return re.sub(r"\s+", " ", reason).strip()


def dispatch_candidate_plan(task: Any) -> dict[str, Any]:
    requested_tool = task["assignee_ai"] if isinstance(task, sqlite3.Row) else task.get("assignee_ai")
    task_type = task["task_type"] if isinstance(task, sqlite3.Row) else task.get("task_type")
    title = task["title"] if isinstance(task, sqlite3.Row) else task.get("title", "")
    notes = task["notes"] if isinstance(task, sqlite3.Row) else task.get("notes", "")
    ai_instruction = task["ai_instruction"] if isinstance(task, sqlite3.Row) else task.get("ai_instruction", "")
    locked_scope = task["locked_scope"] if isinstance(task, sqlite3.Row) else task.get("locked_scope", "")
    acceptance = task["acceptance_criteria"] if isinstance(task, sqlite3.Row) else task.get("acceptance_criteria", "")
    project = task["project"] if isinstance(task, sqlite3.Row) else task.get("project", "")
    plan = token_optimized_pipeline(
        task_type,
        title or "",
        f"{notes or ''} {ai_instruction or ''}",
        locked_scope or "",
        acceptance or "",
        project or "",
        apply_availability=True,
    )
    status = get_tools_status_cached()
    candidates = dedupe_tools([requested_tool, *plan.get("dispatch_candidates", []), *fallback_tools_for_task(task_type)])
    runnable = [tool for tool in candidates if is_runnable_tool(tool, status)]
    skipped = [
        {"tool": tool, "reason": tool_unavailable_reason(tool, status)}
        for tool in candidates
        if tool not in runnable
    ]
    return {
        "routing_plan": plan,
        "candidates": runnable,
        "skipped": skipped,
        "requested_tool": requested_tool,
    }


def token_optimized_pipeline(
    task_type: str | None,
    title: str = "",
    notes: str = "",
    locked_scope: str = "",
    acceptance: str = "",
    project: str = "",
    apply_availability: bool = False,
) -> dict[str, Any]:
    normalized = normalize_task_type(task_type)
    context = estimate_context_size(title, notes, locked_scope, acceptance)
    project_profile = infer_project_profile(project, locked_scope)
    preferred_tool, reason = recommend_tool_for_task(normalized, title, f"{notes} {acceptance}")
    pipeline = list(TASK_TYPE_PIPELINE.get(normalized, ["Codex"]))
    preferred_tool, pipeline, project_note = adapt_pipeline_for_project(
        normalized, preferred_tool, pipeline, project_profile, context["level"]
    )
    if project_note:
        reason = project_note

    if context["level"] == "small" and preferred_tool != "Codex" and normalized in {"fullstack", "quality_review", "security_review"}:
        pipeline = ["Codex", preferred_tool] if preferred_tool != "Codex" else ["Codex"]
        reason = f"任务上下文较小，先用 Codex 做最小变更/摘要，再按需升级到 {preferred_tool}。"
    elif context["level"] == "large" and pipeline[0] != "Codex":
        pipeline.insert(0, "Codex")
        reason = f"任务上下文较大，先用 Codex 生成摘要/锁定范围，再调用 {preferred_tool}，降低后续 token。"

    deduped: list[str] = []
    for tool in pipeline:
        if not deduped or deduped[-1] != tool:
            deduped.append(tool)

    status = None
    availability_error = None
    if apply_availability:
        try:
            status = get_tools_status_cached()
        except Exception as exc:
            availability_error = str(exc)
            status = None

    availability = apply_route_availability(normalized, preferred_tool, deduped, status)
    primary_tool = availability["primary_tool"]

    return {
        "task_type": normalized,
        "recommended_tool": preferred_tool,
        "primary_tool": primary_tool,
        "reason": reason,
        "context": context,
        "project_profile": project_profile,
        "pipeline": [
            tool_route_item(tool, idx, preferred_tool, status)
            for idx, tool in enumerate(deduped)
        ],
        "execution_pipeline": availability["execution_pipeline"],
        "dispatch_candidates": availability["dispatch_candidates"],
        "skipped_tools": availability["skipped_tools"],
        "availability_checked": availability["availability_checked"],
        "availability_error": availability_error,
        "fallback_applied": availability["fallback_applied"],
        "token_policy": [
            "先摘要、后执行：大上下文任务先由 Codex 提炼范围和验收点。",
            "先局部、后全栈：单文件/小范围改动不启动 Antigravity。",
            "工具擅长点优先：架构/高风险交给 Claude，广域/多模态交给 Gemini，局部执行交给 Codex，低成本草稿/结构化交给 DeepSeek，全栈集成交给 Antigravity/OpenClaw，跨 Agent 管家交给 Hermes。",
            "项目性质优先：根据前端/后端/移动/边缘/部署/文档画像调整链路。",
            "先机器、后人工：Cursor 作为人工精修入口，不做后台调度。",
            "只传必要上下文：优先传 diff、锁定文件、执行清单和 ADR 摘要。",
        ],
    }


def pipeline_role(tool: str, index: int, primary_tool: str) -> str:
    if index == 0 and tool == "Codex" and primary_tool != "Codex":
        return "上下文压缩/任务拆解"
    if tool == primary_tool:
        return "主执行"
    if tool == "Cursor":
        return "人工精修"
    if tool == "Claude Code":
        return "架构/质量复核"
    if tool == "Gemini":
        return "广域调研/安全扫描"
    if tool == "Antigravity":
        return "端到端集成"
    if tool == "DeepSeek V4-Pro":
        return "低成本草稿/结构化"
    if tool == "Hermes":
        return "多模型路由/管家"
    return "执行/验证"


def recommend_tool_for_task(task_type: str | None, title: str = "", notes: str = "") -> tuple[str, str]:
    normalized = normalize_task_type(task_type)
    tool, reason = TASK_TYPE_TOOL_ROUTE.get(normalized, TASK_TYPE_TOOL_ROUTE["fullstack"])
    text = f"{title} {notes}".lower()
    if any(k in text for k in ["安全", "security", "漏洞", "权限"]):
        return "Gemini", "任务内容包含安全/风险关键词，优先使用 Gemini。"
    if any(k in text for k in ["架构", "schema", "数据模型", "architecture"]):
        return "Claude Code", "任务内容包含架构/数据模型关键词，优先使用 Claude Code。"
    if any(k in text for k in ["测试", "test", "文档", "docs", "swagger", "交付"]):
        return "Codex", "任务内容偏测试/文档/交付，优先使用 Codex。"
    return tool, reason
