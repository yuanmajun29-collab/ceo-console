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
    "DeepSeek V4-Pro": "https://platform.deepseek.com/usage",
}
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5050
DEFAULT_DISPATCH_TIMEOUT_SECONDS = 1800
ACP_DISCOVERY_REFRESH_SECONDS = int(os.getenv("CEO_CONSOLE_ACP_DISCOVERY_REFRESH_SECONDS", "5"))

FINANCE_DIRECTIONS = {"in", "out"}
FINANCE_CYCLES = {"monthly", "quarterly", "yearly", "once"}
FINANCE_SUBSCRIPTION_STATUSES = {"active", "paused", "cancelled"}
FINANCE_CYCLE_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12, "once": 0}

ALLOWED_STATUS = {"待分配", "AI执行中", "待人工审查", "已完成"}
ALLOWED_PRIORITY = {"P0", "P1", "P2"}
ALLOWED_AI = {"Antigravity", "Claude Code", "Cursor", "Codex", "Gemini", "DeepSeek V4-Pro", "Other"}
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
    "customer_triage",
    "contract_review",
    "bookkeeping",
    "finance_report",
    "marketing_content",
    "social_monitor",
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
    "customer_triage": ("Gemini", "客户沟通记录通常上下文长且来源多，先用 Gemini 汇总，再交 DeepSeek 低成本分类与草拟回复。"),
    "contract_review": ("Claude Code", "合同条款审查属于高风险逻辑判断，使用 Claude Code 标注风险，DeepSeek 负责整理摘要。"),
    "bookkeeping": ("DeepSeek V4-Pro", "票据与流水归档属于高频结构化任务，优先用 DeepSeek V4-Pro 控制成本，必要时调用 Gemini 识别图片。"),
    "finance_report": ("Claude Code", "现金流与异常支出分析需要严谨推理，使用 Claude Code 生成问诊式财务结论。"),
    "marketing_content": ("DeepSeek V4-Pro", "营销内容生产以 DeepSeek V4-Pro 批量初稿控成本，再由 Claude Code 做精修。"),
    "social_monitor": ("Gemini", "社媒监听需要广域搜索和长上下文归纳，使用 Gemini 发现机会，再由 Claude Code 判断是否参与。"),
}
ACP_TOOL_TARGET = {
    "Cursor": "cursor",
    "Antigravity": "antigravity",
    "Claude Code": "claude",
    "Codex": "codex",
    "Gemini": "gemini",
    "DeepSeek V4-Pro": "deepseek-v4-pro",
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
    "DeepSeek": "DeepSeek V4-Pro",
    "DeepSeek V4": "DeepSeek V4-Pro",
    "DeepSeek V4-Pro": "DeepSeek V4-Pro",
    "Deepseek V4 Pro": "DeepSeek V4-Pro",
    "deepspeek-v4-pro": "DeepSeek V4-Pro",
}
ACP_NON_AGENT_NAMES = {"coordinator", "项目目录", "INFO", "WARN", "ERROR"}
_ACP_DISCOVERY_CACHE: dict[str, Any] = {"tools": {}, "stdout": "", "ts": None, "ts_epoch": None, "company_dir": None}
TOOL_TOKEN_PROFILE = {
    "Codex": {
        "cost": 1,
        "tier": "low",
        "best_for": ["局部代码修改", "测试验证", "文档交付", "批量命令", "交付整理"],
        "avoid_for": ["大范围竞品调研", "需要产品/架构深推理的模糊任务"],
    },
    "DeepSeek V4-Pro": {
        "cost": 1,
        "tier": "low-cost-generalist",
        "best_for": ["日常代码生成", "单元测试草稿", "客户/营销文本初稿", "票据结构化", "低成本批量摘要"],
        "avoid_for": ["高风险合同结论", "最终架构裁决", "需要多模态识别且未提供结构化输入"],
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
    "customer_triage": ["Gemini", "DeepSeek V4-Pro", "Claude Code"],
    "contract_review": ["Claude Code", "DeepSeek V4-Pro", "Codex"],
    "bookkeeping": ["Gemini", "DeepSeek V4-Pro", "Codex"],
    "finance_report": ["DeepSeek V4-Pro", "Claude Code", "Codex"],
    "marketing_content": ["Gemini", "DeepSeek V4-Pro", "Claude Code"],
    "social_monitor": ["Gemini", "Claude Code", "DeepSeek V4-Pro"],
}

BUSINESS_DOMAINS = {
    "operations": {
        "name": "生产与经营",
        "tagline": "公司的交付能力——把目标变成可验收的产物",
        "modules": ["project"],
    },
    "sales": {
        "name": "营销与销售",
        "tagline": "公司的获客与成单能力——从触达、转化到续费",
        "modules": ["marketing", "customer"],
    },
    "finance": {
        "name": "财务运作",
        "tagline": "公司的财务全景——现金跑道、收入支出、订阅与税务",
        "modules": ["finance"],
    },
}

BUSINESS_MODULES = {
    "project": {
        "name": "项目交付",
        "domain": "operations",
        "tagline": "从需求、设计、开发、测试到交付的自动巡航",
        "task_types": ["market_research", "architecture", "fullstack", "code_edit", "testing", "docs", "security_review", "quality_review", "delivery"],
        "toolchain": ["Antigravity", "OpenClaw", "Codex", "Claude Code", "Gemini"],
        "ceo_actions": ["批准技术方案", "验收交付", "接受风险"],
        "default_task_type": "fullstack",
        "task_template": {
            "title": "项目交付巡航与阻塞清理",
            "priority": "P1",
            "instruction": "扫描当前项目任务、仓库变更、失败调度与待评审队列，给出下一步推进计划；可自动处理低风险测试、文档和小范围代码任务，关键变更等待 CEO 审批。",
            "expected_output": "项目巡航报告、阻塞清单、建议执行任务与验证结果",
        },
    },
    "customer": {
        "name": "客户与销售",
        "domain": "sales",
        "tagline": "客户分诊、合同审查、销售管道与续费提醒",
        "task_types": ["customer_triage", "contract_review"],
        "toolchain": ["Hermes", "Gemini", "DeepSeek V4-Pro", "Claude Code"],
        "ceo_actions": ["批准回复", "推进商机", "接受合同风险", "确认续费"],
        "default_task_type": "customer_triage",
        "task_template": {
            "title": "今日客户与销售管道巡航",
            "priority": "P0",
            "instruction": "汇总今日客户沟通、新询价、未签合同、续费到期与投诉风险；对低风险事项生成回复草稿，高风险事项进入 CEO 待决策队列。",
            "expected_output": "客户情绪日报、销售管道状态、续费提醒、合同风险清单、建议回复草稿",
        },
    },
    "marketing": {
        "name": "营销推广",
        "domain": "sales",
        "tagline": "内容车间、SEO 主题、社媒监听与回复建议",
        "task_types": ["marketing_content", "social_monitor", "market_research"],
        "toolchain": ["Gemini", "DeepSeek V4-Pro", "Claude Code", "Hermes"],
        "ceo_actions": ["批准发布", "修改语气", "选择渠道"],
        "default_task_type": "marketing_content",
        "task_template": {
            "title": "本周内容车间与社媒机会巡航",
            "priority": "P1",
            "instruction": "围绕当前产品和项目进展生成内容主题、文章初稿、短文案与社媒互动建议；DeepSeek 批量出初稿，Claude 做最终润色，发布前等待 CEO 批准。",
            "expected_output": "内容选题、营销文案初稿、社媒机会清单、发布前审批项",
        },
    },
    "finance": {
        "name": "财务运作",
        "domain": "finance",
        "tagline": "公司整体现金流、收入支出、订阅与税务，不绑定单一项目",
        "task_types": ["bookkeeping", "finance_report"],
        "toolchain": ["Gemini", "DeepSeek V4-Pro", "Claude Code", "Codex"],
        "ceo_actions": ["确认入账", "批准预算", "暂停订阅", "审批支出"],
        "default_task_type": "finance_report",
        "task_template": {
            "title": "公司财务健康巡航",
            "priority": "P1",
            "instruction": "汇总本期收入、支出、订阅净额与现金跑道；普通归档走 DeepSeek 低成本结构化，高风险结论交 Claude Code 复核；输出公司级（非单项目）的财务健康摘要。",
            "expected_output": "公司财务健康摘要、异常支出清单、现金跑道预测、订阅净额、需 CEO 确认的入账项",
        },
    },
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
        "deepseek": "DeepSeek V4-Pro",
        "deepseek-v4": "DeepSeek V4-Pro",
        "deepseek-v4-pro": "DeepSeek V4-Pro",
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


def clear_acp_discovery_cache() -> None:
    _ACP_DISCOVERY_CACHE["tools"] = {}
    _ACP_DISCOVERY_CACHE["stdout"] = ""
    _ACP_DISCOVERY_CACHE["ts"] = None
    _ACP_DISCOVERY_CACHE["ts_epoch"] = None
    _ACP_DISCOVERY_CACHE["company_dir"] = None


def acp_discovery_cache_age_seconds() -> float | None:
    ts_epoch = _ACP_DISCOVERY_CACHE.get("ts_epoch")
    if ts_epoch is None:
        return None
    try:
        return max(0.0, datetime.now().timestamp() - float(ts_epoch))
    except (TypeError, ValueError):
        return None


def update_acp_discovery_cache(stdout: str, company_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    discovered = parse_acp_status_tools(stdout)
    _ACP_DISCOVERY_CACHE["tools"] = discovered
    _ACP_DISCOVERY_CACHE["stdout"] = stdout
    _ACP_DISCOVERY_CACHE["ts"] = now_str()
    _ACP_DISCOVERY_CACHE["ts_epoch"] = datetime.now().timestamp()
    _ACP_DISCOVERY_CACHE["company_dir"] = str(company_dir) if company_dir else None
    return discovered


def get_acp_agent_registry(stdout: str | None = None) -> dict[str, dict[str, Any]]:
    company_dir, _ = resolve_company_dir()
    cached_company = _ACP_DISCOVERY_CACHE.get("company_dir")
    if cached_company and cached_company != str(company_dir):
        clear_acp_discovery_cache()

    registry = {name: _agent_entry(name, target, False, "fixed") for name, target in ACP_TOOL_TARGET.items()}
    registry.update(discover_local_acp_agents())
    registry.update(parse_extra_acp_agents_env())
    if stdout is not None:
        update_acp_discovery_cache(stdout, company_dir)
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
