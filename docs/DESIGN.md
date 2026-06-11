# CEO Console — 设计文档 & 使用说明

> 一人公司的 AI 操作系统
> 运行在 http://127.0.0.1:5050

---

# 一、架构总览

```
用户（浏览器） → http://127.0.0.1:5050
                    │
            Flask 后端 (src/)
            ├── routes.py         ← 76 个 API 端点
            ├── feed.py           ← 信息流聚合
            ├── commander.py      ← AI 智能路由
            ├── daily_brief.py    ← 每日简报
            ├── tool_health.py    ← API Key 有效性检测
            ├── subscription_reminders.py ← 续费提醒
            ├── risk_monitor.py   ← 风险检测
            ├── search.py         ← 统一搜索
            ├── scheduler.py      ← 定时任务
            ├── tools.py          ← 工具探测/ACP
            └── coordinator_writer.py ← 跨工具状态同步
                    │
            Vue 3 前端 (frontend/src/)
            ├── views/            ← 20 个页面
            ├── components/       ← 组件（FeedItem/Sidebar 等）
            └── stores/           ← 状态管理
                    │
            SQLite (data/ceo_console.db)
            ├── tasks             ← 任务
            ├── decision_logs     ← 决策日志
            ├── finance_*         ← 财务
            ├── cron_jobs         ← 定时任务
            └── tool_health       ← 工具健康记录
```

---

## 二、导航结构

```
🏠 首页                         信息流（看全部动态）

▶ 指挥                         AI Commander（说意图 → 自动执行）

📋 运营（直接展开）
    ├ ☷ 任务                    任务中心
    ├ ☑ 审查                    审查中心
    ├ 📚 知识                    知识中心（记忆/技能/人格/状态/路由表）
    ├ ◉ 状态                    工具状态面板
    └ ☁ 健康                    系统健康 + 工具 Key 检测 + 续费提醒

📦 业务（折叠）
    ├ 📊 总览                    业务模块聚合页
    ├ 📦 项目                    项目交付
    ├ 🤝 客户                    客户管理
    ├ 💰 财务                    收支/订阅/OCR
    └ 📣 营销                    内容推广

🔧 支持（折叠）
    ├ ⌘ 代码                    仓库
    ├ ▣ 数据                    分析
    ├ ☰ 报表                    报告
    ├ □ 决策                    决策日志
    └ ⚙ 设置                    系统设置
```

---

## 三、功能模块

### 3.1 首页（信息流）

- **入口**: 打开浏览器即见
- **内容**: 聚合来自 Hermes 记忆、Coordinator 状态、Git 日志、任务、风险、续费提醒的数据
- **操作**: 每条信息流的 `▶` 按钮直接执行（调用 Commander），按 `e` 键快速执行选中项
- **今日焦点**: 首页顶部 AI 推荐的今天最重要 3 件事
- **微指标**: 底部显示项目/任务/风险/审查数量

### 3.2 AI Commander（指挥）

- **入口**: 侧边栏 `▶ 指挥`
- **用途**: 说一句话，系统自动判断用哪个工具、怎么执行
- **示例**:
  - "检查 ccec 项目状态" → 自动路由到 Claude Code
  - "看看本月花了多少钱" → 自动路由到财务查询
  - "以安全工程师审查 Dockerfile" → 自动路由到 OpenClaw
- **路由逻辑**: `commander.py` — 分析意图 → 匹配任务类型 → 分配最优工具链

### 3.3 知识中心

- **5 个标签页**:
  1. 📊 状态 — Coordinator 当前所有键值
  2. 🧠 记忆 — Hermes 最新持久记忆
  3. 🧰 技能 — 101 个 Hermes 技能（可搜索）
  4. 🎭 人格 — 184 个 The Agency 专家角色（可搜索）
  5. 📋 路由 — 跨工具技能路由表
- **导出**: 支持导出为 Markdown

### 3.4 工具健康（Key 监测）

- **入口**: `/app/health` 或侧边栏 `☁ 健康`
- **检测方式**: 实际调 API 验证 Key（非检查文件存在）
- **覆盖工具**:
  - Hermes / PilotDeck — 调 DeepSeek API (200/401/429)
  - Claude Code — 检查 Claude.app 是否存在
  - Codex — 检查 Codex.app 是否存在
  - Cursor — 检查 Cursor.app + CLI
  - Gemini CLI — CLI 命令检测
  - OpenClaw / Antigravity / Obsidian — 可用性检测
- **自动检测**: 后台每 30 分钟自动重检
- **失效告警**: Key 过期自动出现在信息流和风险中

### 3.5 续费提醒

- **入口**: `/app/health`
- **默认记录**: 6 个工具（Hermes/PilotDeck/Claude/Codex/Cursor/Gemini）
- **提醒规则**: 到期前 N 天开始在信息流中显示
- **操作**: 点击直接跳转续费链接
- **自定义**: 可修改到期日/提前天数/续费链接

### 3.6 每日简报

- **入口**: 首页信息流中
- **内容**: 项目状态 + 财务状况 + 任务概览 + 风险 + 建议
- **性能**: 首次 ~30 秒生成（遍历 Git 日志），后续调用秒回（2 分钟缓存）

### 3.7 业务模块

| 模块 | 功能 |
|------|------|
| 项目交付 | 项目列表、治理评分、交付周期 |
| 客户管理 | 客户关系 |
| 财务诊断 | 收支流水、订阅管理、OCR 票据识别 |
| 营销增长 | 内容推广 |

### 3.8 跨工具协同

CEO Console 通过 Agent Coordinator 与以下 8 个 AI 工具互通：
- **Hermes**（大脑/编排）
- **Cursor**（IDE 编码）
- **Claude Code**（大代码库重构）
- **Codex**（自动化开发）
- **Gemini CLI**（内容生成/分析）
- **Antigravity**（备用）
- **OpenClaw**（人格化 Agent）
- **PilotDeck**（后台常驻）

互通方式：
- 每个工具读取共享知识 `~/.hermes/skills/.../references/`
- CEO Console 通过 `/api/hub/*` 展示最新状态
- Coordinator 双向同步状态变更

---

## 四、快捷操作

| 快捷键 | 作用 |
|--------|------|
| `j` / `k` | 信息流上下导航 |
| `Enter` | 展开/折叠信息流条目 |
| `e` | 执行选中的信息流操作 |
| `i` | 忽略选中的信息流条目 |
| `⌘K` | 打开命令面板（搜索页面/工具/任务） |

---

## 五、常见操作

### 查看今天要做什么
→ 打开浏览器 → 首页信息流可见今日焦点

### 查看工具有没有到期
→ 侧边栏 → 健康 → 工具健康分区

### 设置续费提醒
→ 侧边栏 → 健康 → 续费提醒 → 修改到期日

### 说一句话让系统执行
→ 侧边栏 → 指挥 → 输入意图 → 自动路由

### 搜索全部资料
→ 首页 ⌘K 面板 → 输入关键词 → 跨任务/项目/记忆/技能/人格搜索

### 查看各 AI 工具状态
→ 侧边栏 → 状态（工具面板）或 健康（Key 检测）

---

## 六、技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12 + Flask |
| 前端 | Vue 3 + TypeScript + Naive UI + Vite |
| 数据库 | SQLite |
| 进程管理 | launchd（开机自启） |

## 七、开发

```bash
# 启动开发
cd ~/company/ceo-console && python3 server.py

# 前端构建
cd ~/company/ceo-console/frontend && npm run build

# 重启服务
launchctl bootout gui/$(id -u)/com.oneperson.ceo-console  # 停
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.oneperson.ceo-console.plist  # 启
```
