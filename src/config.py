from __future__ import annotations

import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "ceo_console.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

SAFE_COMPANY_DIR = Path.home() / "company"
DESKTOP_COMPANY_DIR = Path.home() / "Desktop" / "company"
LEGACY_COMPANY_DIR = Path.home() / "公司根目录"
COMPANY_DIR = SAFE_COMPANY_DIR if SAFE_COMPANY_DIR.exists() else (DESKTOP_COMPANY_DIR if DESKTOP_COMPANY_DIR.exists() else LEGACY_COMPANY_DIR)
ARCHIVE_DIR = COMPANY_DIR / ".archive"
PM_SCRIPT = Path.home() / "ai-team-template" / "初始化脚本" / "pm"
ACP_AGENT_SCRIPT = COMPANY_DIR / "acp-agent"
ACP_STATUS_SCRIPT = COMPANY_DIR / "acp-all-status"
DEFAULT_RECHARGE_URLS = {
    "Claude Code": "https://console.anthropic.com/settings/billing",
    "Codex": "https://platform.openai.com/settings/organization/billing/overview",
    "Gemini": "https://ai.google.dev/gemini-api/docs/billing",
    "Antigravity": "https://antigravity.com/pricing",
    "Cursor": "https://cursor.com/pricing",
}
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5050
DEFAULT_DISPATCH_TIMEOUT_SECONDS = 1800

ALLOWED_STATUS = {"待分配", "AI执行中", "待人工审查", "已完成"}
ALLOWED_PRIORITY = {"P0", "P1", "P2"}
ALLOWED_AI = {"Antigravity", "Claude Code", "Cursor", "Codex", "Gemini", "Other"}
ALLOWED_EXEC_STATE = {"idle", "running", "succeeded", "failed", "unsupported"}
ALLOWED_TASK_TYPE = {
    "market_research",
    "architecture",
    "fullstack",
    "code_edit",
    "testing",
    "docs",
    "security_review",
    "quality_review",
    "delivery",
}
PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9._\-\u4e00-\u9fff]{1,80}$")
TASK_TYPE_TOOL_ROUTE = {
    "market_research": ("Gemini", "广域调研需要长上下文检索，使用 Gemini，但只输出结论摘要以控制 token。"),
    "architecture": ("Claude Code", "架构决策需要高质量推理，使用 Claude Code；先让 Codex/摘要层准备精简上下文。"),
    "fullstack": ("Antigravity", "独立全栈集成任务才启动 Antigravity，避免把小改动交给高上下文 agent。"),
    "code_edit": ("Codex", "局部代码编辑默认交给 Codex，使用锁定范围降低上下文 token。"),
    "testing": ("Codex", "测试验证和批量命令执行默认交给 Codex，避免调用长上下文工具。"),
    "docs": ("Codex", "文档、接口说明和交付材料默认交给 Codex，复用已有上下文摘要。"),
    "security_review": ("Gemini", "安全/风险面扫描使用 Gemini，但限制为摘要式审查，避免全量代码粘贴。"),
    "quality_review": ("Claude Code", "代码质量和架构一致性审查使用 Claude Code，仅传 diff/关键文件。"),
    "delivery": ("Codex", "交付包、变更说明和验收材料默认交给 Codex。"),
}
ACP_TOOL_TARGET = {
    "Cursor": "cursor",
    "Antigravity": "antigravity",
    "Claude Code": "claude",
    "Codex": "codex",
    "Gemini": "gemini",
}
CORE_AI_TOOLS = tuple(ACP_TOOL_TARGET.keys())
ACP_AGENT_NAME_ALIASES = {
    "Claude": "Claude Code",
    "Claude Code": "Claude Code",
    "Gemini CLI": "Gemini",
    "Gemini": "Gemini",
    "Codex": "Codex",
    "Cursor": "Cursor",
    "Antigravity": "Antigravity",
    "OpenClaw": "Antigravity",
    "Hermes": "Hermes",
}
ACP_NON_AGENT_NAMES = {"coordinator", "项目目录", "INFO", "WARN", "ERROR"}
_ACP_DISCOVERY_CACHE: dict[str, Any] = {"tools": {}, "stdout": "", "ts": None}
TOOL_TOKEN_PROFILE = {
    "Codex": {
        "cost": 1,
        "tier": "low",
        "best_for": ["局部代码修改", "测试验证", "文档交付", "批量命令", "交付整理"],
        "avoid_for": ["大范围竞品调研", "需要产品/架构深推理的模糊任务"],
    },
    "Gemini": {
        "cost": 2,
        "tier": "medium",
        "best_for": ["市场调研", "安全面扫描", "大范围资料归纳", "跨文件风险发现"],
        "avoid_for": ["明确的小代码改动", "重复执行命令"],
    },
    "Claude Code": {
        "cost": 3,
        "tier": "high",
        "best_for": ["架构设计", "复杂方案权衡", "代码质量审查", "关键决策"],
        "avoid_for": ["机械批量修改", "低风险文档整理"],
    },
    "Antigravity": {
        "cost": 4,
        "tier": "highest",
        "best_for": ["端到端全栈功能", "跨前后端集成", "较完整的可运行交付"],
        "avoid_for": ["小 bug", "单文件改动", "单纯测试或文档"],
    },
    "Cursor": {
        "cost": 1,
        "tier": "human-in-loop",
        "best_for": ["人工精修", "可视化 IDE 微调", "CEO 亲自接管"],
        "avoid_for": ["后台无人值守调度"],
    },
}
TASK_TYPE_PIPELINE = {
    "market_research": ["Gemini", "Claude Code", "Codex"],
    "architecture": ["Codex", "Claude Code", "Codex"],
    "fullstack": ["Codex", "Antigravity", "Codex", "Claude Code"],
    "code_edit": ["Codex", "Cursor"],
    "testing": ["Codex"],
    "docs": ["Codex"],
    "security_review": ["Codex", "Gemini", "Codex"],
    "quality_review": ["Codex", "Claude Code"],
    "delivery": ["Codex"],
}


def is_dir_accessible(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        list(path.iterdir())
        return True
    except PermissionError:
        return False


def resolve_company_dir() -> tuple[Path, str]:
    if is_dir_accessible(SAFE_COMPANY_DIR):
        return SAFE_COMPANY_DIR, "safe_home_company"
    if is_dir_accessible(DESKTOP_COMPANY_DIR):
        return DESKTOP_COMPANY_DIR, "desktop"
    if is_dir_accessible(LEGACY_COMPANY_DIR):
        return LEGACY_COMPANY_DIR, "legacy"
    if SAFE_COMPANY_DIR.exists():
        return SAFE_COMPANY_DIR, "safe_permission_denied"
    if DESKTOP_COMPANY_DIR.exists():
        return DESKTOP_COMPANY_DIR, "desktop_permission_denied"
    return LEGACY_COMPANY_DIR, "unavailable"


def get_acp_scripts() -> dict[str, Any]:
    company_dir, _ = resolve_company_dir()
    agent = company_dir / "acp-agent"
    status = company_dir / "acp-all-status"
    return {
        "agent": {"path": str(agent), "exists": agent.exists(), "executable": os.access(agent, os.X_OK)},
        "status": {"path": str(status), "exists": status.exists(), "executable": os.access(status, os.X_OK)},
    }


def strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", value or "")


def slugify_acp_target(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", name.strip().lower()).strip("-")
    return value or "agent"


def normalize_acp_agent_name(raw_name: str) -> str:
    name = strip_ansi(raw_name).strip()
    name = re.split(r"\s+(?:命令|context\s+inject|hook|target|状态)\b", name, maxsplit=1, flags=re.I)[0].strip()
    name = re.sub(r"\s+", " ", name)
    return ACP_AGENT_NAME_ALIASES.get(name, name)


def _agent_entry(name: str, target: str | None = None, configured: bool = False, source: str = "fixed") -> dict[str, Any]:
    canonical = normalize_acp_agent_name(name)
    return {
        "name": canonical,
        "target": ACP_TOOL_TARGET.get(canonical) or target or slugify_acp_target(canonical),
        "configured": bool(configured),
        "builtin": canonical in ACP_TOOL_TARGET,
        "source": source,
    }


def display_name_from_acp_target(target: str) -> str:
    alias = {
        "cursor": "Cursor",
        "claude": "Claude Code",
        "claude-code": "Claude Code",
        "codex": "Codex",
        "gemini": "Gemini",
        "gemini-cli": "Gemini",
        "antigravity": "Antigravity",
        "hermes": "Hermes",
    }
    value = target.strip().lower()
    if value in alias:
        return alias[value]
    return " ".join(part.capitalize() for part in re.split(r"[-_\s]+", target.strip()) if part)


def discover_local_acp_agents() -> dict[str, dict[str, Any]]:
    agents: dict[str, dict[str, Any]] = {}
    company_dir, _ = resolve_company_dir()
    hook_dir = company_dir / ".agent-coordinator" / "hooks"
    if hook_dir.exists():
        for hook in hook_dir.glob("*.js"):
            target = hook.stem
            name = display_name_from_acp_target(target)
            entry = _agent_entry(name, target, True, "project_hook")
            agents[entry["name"]] = entry

    hermes_home = Path.home() / ".hermes"
    hermes_hook = hermes_home / "agent-hooks" / "coordinator-context-inject.sh"
    hermes_config = hermes_home / "config.yaml"
    hermes_configured = False
    if hermes_hook.exists() and os.access(hermes_hook, os.X_OK):
        hermes_configured = True
    if hermes_config.exists():
        try:
            hermes_configured = hermes_configured or "coordinator-context-inject.sh" in hermes_config.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass
    if hermes_configured:
        agents["Hermes"] = _agent_entry("Hermes", "hermes", True, "hermes_config")
    return agents


def parse_extra_acp_agents_env() -> dict[str, dict[str, Any]]:
    agents: dict[str, dict[str, Any]] = {}
    raw_json = os.getenv("CEO_CONSOLE_ACP_AGENTS_JSON", "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            items = parsed.items() if isinstance(parsed, dict) else enumerate(parsed if isinstance(parsed, list) else [])
            for key, value in items:
                if isinstance(value, str):
                    entry = _agent_entry(value, configured=True, source="env_json")
                elif isinstance(value, dict):
                    name = str(value.get("name") or key).strip()
                    entry = _agent_entry(name, str(value.get("target") or "").strip() or None, bool(value.get("configured", True)), "env_json")
                else:
                    continue
                agents[entry["name"]] = entry
        except json.JSONDecodeError:
            pass

    raw_list = os.getenv("CEO_CONSOLE_ACP_AGENTS", "").strip()
    if raw_list:
        for item in re.split(r"[,，\n]+", raw_list):
            item = item.strip()
            if not item:
                continue
            if ":" in item:
                name, target = item.split(":", 1)
            else:
                name, target = item, ""
            entry = _agent_entry(name.strip(), target.strip() or None, True, "env")
            agents[entry["name"]] = entry
    return agents


def parse_acp_status_tools(stdout: str) -> dict[str, dict[str, Any]]:
    tools: dict[str, dict[str, Any]] = {}
    for line in strip_ansi(stdout).splitlines():
        if "[OK]" not in line:
            continue
        text = line.split("[OK]", 1)[1].strip()
        if not text or ":" not in text:
            continue
        raw_name = text.split(":", 1)[0].strip()
        name = normalize_acp_agent_name(raw_name)
        if not name or name in ACP_NON_AGENT_NAMES or name.lower() in ACP_NON_AGENT_NAMES:
            continue
        entry = _agent_entry(name, configured=True, source="status")
        tools[entry["name"]] = entry
    return tools


def get_acp_agent_registry(stdout: str | None = None) -> dict[str, dict[str, Any]]:
    registry = {name: _agent_entry(name, target, False, "fixed") for name, target in ACP_TOOL_TARGET.items()}
    registry.update(discover_local_acp_agents())
    registry.update(parse_extra_acp_agents_env())
    if stdout is not None:
        discovered = parse_acp_status_tools(stdout)
        _ACP_DISCOVERY_CACHE["tools"] = discovered
        _ACP_DISCOVERY_CACHE["stdout"] = stdout
        _ACP_DISCOVERY_CACHE["ts"] = now_str()
    for name, entry in (_ACP_DISCOVERY_CACHE.get("tools") or {}).items():
        registry[name] = {**registry.get(name, {}), **entry}
    return registry


def allowed_ai_names() -> set[str]:
    return set(ALLOWED_AI) | set(get_acp_agent_registry().keys())


def is_allowed_ai_name(name: str) -> bool:
    return name in allowed_ai_names()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime_value(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip()[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def parse_due_at(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.strip() or None


def load_settings() -> dict[str, Any]:
    defaults = {
        "dispatch_timeout_seconds": DEFAULT_DISPATCH_TIMEOUT_SECONDS,
        "auto_route_new_tasks": True,
        "dashboard_refresh_seconds": 15,
        "default_task_type": "fullstack",
        "default_assignee_ai": "Other",
    }
    if not SETTINGS_PATH.exists():
        return defaults
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    merged = defaults | {k: v for k, v in data.items() if k in defaults}
    return normalize_settings(merged)


def normalize_settings(data: dict[str, Any]) -> dict[str, Any]:
    settings = dict(data)
    try:
        settings["dispatch_timeout_seconds"] = int(settings.get("dispatch_timeout_seconds", DEFAULT_DISPATCH_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        settings["dispatch_timeout_seconds"] = DEFAULT_DISPATCH_TIMEOUT_SECONDS
    settings["dispatch_timeout_seconds"] = max(60, min(7200, settings["dispatch_timeout_seconds"]))

    try:
        settings["dashboard_refresh_seconds"] = int(settings.get("dashboard_refresh_seconds", 15))
    except (TypeError, ValueError):
        settings["dashboard_refresh_seconds"] = 15
    settings["dashboard_refresh_seconds"] = max(5, min(300, settings["dashboard_refresh_seconds"]))

    settings["auto_route_new_tasks"] = bool(settings.get("auto_route_new_tasks", True))
    settings["default_task_type"] = normalize_task_type(settings.get("default_task_type", "fullstack"))
    default_ai = str(settings.get("default_assignee_ai", "Other")).strip()
    settings["default_assignee_ai"] = default_ai if is_allowed_ai_name(default_ai) else "Other"
    return settings


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = normalize_settings(load_settings() | data)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings


def validate_project_name(name: str) -> str | None:
    if not name:
        return "项目名不能为空"
    if "/" in name or "\\" in name or name in {".", ".."}:
        return "项目名不能包含路径分隔符"
    if not PROJECT_NAME_RE.fullmatch(name):
        return "项目名仅支持中文、英文、数字、点、下划线和短横线，长度 1-80"
    return None


def normalize_task_type(value: Any) -> str:
    task_type = str(value or "fullstack").strip()
    return task_type if task_type in ALLOWED_TASK_TYPE else "fullstack"


def get_configured_host() -> str:
    return os.environ.get("CEO_CONSOLE_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def get_configured_port() -> int:
    raw = os.environ.get("CEO_CONSOLE_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


def get_dispatch_timeout_seconds() -> int:
    saved = load_settings().get("dispatch_timeout_seconds")
    if saved:
        try:
            return max(60, int(saved))
        except (TypeError, ValueError):
            pass
    raw = os.environ.get("CEO_CONSOLE_DISPATCH_TIMEOUT_SECONDS", str(DEFAULT_DISPATCH_TIMEOUT_SECONDS)).strip()
    try:
        timeout = int(raw)
    except ValueError:
        return DEFAULT_DISPATCH_TIMEOUT_SECONDS
    return max(60, timeout)
