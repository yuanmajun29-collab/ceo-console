from __future__ import annotations

import os
import json
import re
import shutil
import sqlite3
import subprocess
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
        str(Path.home() / "Library" / "Python" / "3.9" / "bin"),
    ]
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
    if acp_target and acp_agent["exists"] and acp_agent["executable"]:
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
        return [agent_path, acp_target, prompt], None

    cmd_path = resolve_tool_command(tool_name)
    if not cmd_path:
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


def pick_fallback_tool(preferred_tools: list[str] | None = None) -> tuple[str | None, str | None]:
    ordered = preferred_tools or ["Claude Code", "Gemini"]
    status = get_tools_status_cached()
    for tool in ordered:
        info = status.get(tool) or {}
        if info.get("available") and info.get("runnable"):
            return tool, None
    return None, "未找到可自动调度的后备工具（需要可运行的 Claude Code 或 Gemini）"


def check_command_runnable(path: str) -> tuple[bool, str | None]:
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
            return True, None
        err = (res.stderr or res.stdout or "").strip()
        return False, err[:400]
    except Exception as exc:
        return False, str(exc)


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
    }
    data: dict[str, Any] = {}
    acp_scripts = get_acp_scripts()
    registry = get_acp_agent_registry()
    for tool, acp_entry in registry.items():
        command = resolve_tool_command(tool)
        acp_enabled = bool(acp_scripts["agent"]["exists"] and acp_scripts["agent"]["executable"] and acp_entry.get("target"))
        available = command is not None or acp_enabled
        runnable = False
        reason = None
        if available and command and headless_support.get(tool, True):
            runnable, reason = check_command_runnable(command)
        elif available and acp_enabled and headless_support.get(tool, True):
            runnable = True
            reason = "通过 ACP 动态接入，按通用 Agent 目标调度。"
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


def token_optimized_pipeline(
    task_type: str | None,
    title: str = "",
    notes: str = "",
    locked_scope: str = "",
    acceptance: str = "",
    project: str = "",
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

    return {
        "task_type": normalized,
        "primary_tool": preferred_tool,
        "reason": reason,
        "context": context,
        "project_profile": project_profile,
        "pipeline": [
            {
                "tool": tool,
                "acp_target": ACP_TOOL_TARGET.get(tool),
                "token_cost": TOOL_TOKEN_PROFILE.get(tool, {}).get("cost"),
                "tier": TOOL_TOKEN_PROFILE.get(tool, {}).get("tier"),
                "role": pipeline_role(tool, idx, preferred_tool),
            }
            for idx, tool in enumerate(deduped)
        ],
        "token_policy": [
            "先摘要、后执行：大上下文任务先由 Codex 提炼范围和验收点。",
            "先局部、后全栈：单文件/小范围改动不启动 Antigravity。",
            "工具擅长点优先：架构交给 Claude，广域调研/安全交给 Gemini，局部执行交给 Codex，全栈集成交给 Antigravity。",
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
