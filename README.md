# CEO Console：一人公司 AI 操作系统

本地优先的 AI 公司指挥平台，目标是整合 `Cursor / Antigravity / OpenClaw / Hermes / Claude Code / Gemini / Codex / DeepSeek V4-Pro` 的工具能力，把“一人公司”CEO 打造成超级 AI 智能体。

平台负责公司项目从创建、设计、开发、管理、进度推进到项目交付的自动化执行；CEO 只负责方向、优先级、风险接受、关键节点决策与最终验收。

## 核心目标

- 将 CEO 的一句目标转化为项目、计划、里程碑、任务、验收标准和风险清单
- 根据任务类型、工具擅长点、ACP 可用性和 Token 成本，自动选择并调度 Cursor、Antigravity/OpenClaw、Hermes、Claude Code、Gemini、Codex 或 DeepSeek V4-Pro
- 自动推进项目执行、记录过程日志、沉淀审计事件、暴露风险提醒
- 对失败任务进行重试、回退、反馈调整和人工评审闭环
- 在关键决策点才打断 CEO，让 CEO 从“任务操作员”回到“战略决策者”
- 将项目、客户、财务、营销四个经营域统一到 Web 驾驶舱，CEO 只做“看 / 说 / 点”

更多产品愿景见：

- [`VISION.md`](VISION.md)
- [`docs/architecture-ai-company-os.md`](docs/architecture-ai-company-os.md)
- [`docs/operations-and-dispatch-playbook.md`](docs/operations-and-dispatch-playbook.md)

## 与 `one-person-company.sh` 的关系

- 项目目录规则：优先 `~/company`（非 Desktop，规避 TCC 权限问题），再回退 `~/Desktop/company` 与 `~/公司根目录`
- 项目管理动作：调用 `~/ai-team-template/初始化脚本/pm`
- 因此创建/归档/删除逻辑与脚本体系保持一致

## 核心功能

- 项目总览：活跃/归档项目、规则文件与协同状态
- 项目管理：创建、归档、恢复、删除（通过 `pm` 执行）
- 项目治理：展示项目任务总量、活跃任务、风险、最近更新
- 一人公司经营驾驶舱：按项目交付、客户管理、财务问诊、营销推广展示巡航任务、工具链和待决策队列
- 任务看板：待分配 / AI执行中 / 待人工审查 / 已完成
- 任务筛选：按关键词、项目、状态、优先级、执行状态筛选
- 任务批量操作：批量改状态
- 任务调度：可对任务触发 `Cursor / Antigravity / OpenClaw / Hermes / Claude / Codex / Gemini / DeepSeek V4-Pro` 自动执行或路由
- 调度反馈：记录执行状态、命令、输出、错误、开始/结束时间、调度次数
- 调度重试：失败或受限任务可重置并再次调度
- 项目保护：删除仍有未完成任务的项目时需要二次强制确认
- 审计事件：规划中（将在后续里程碑补齐独立事件表与查询 API）
- 活动流：规划中（将基于审计事件实现）
- 数据导出：任务 CSV 导出
- 自动提示：超时任务、即将到期任务、调度失败任务提醒（含浏览器通知）

## 启动

```bash
cd ~/company/ceo-console
python3 -m pip install -r requirements.txt
python3 server.py
```

浏览器打开：

- [http://127.0.0.1:5050](http://127.0.0.1:5050)

可选环境变量：

```bash
CEO_CONSOLE_HOST=127.0.0.1
CEO_CONSOLE_PORT=5050
CEO_CONSOLE_DISPATCH_TIMEOUT_SECONDS=1800
```

## 源码结构

- `server.py`：兼容启动入口，保持 `python3 server.py` 与旧测试导入方式可用
- `src/config.py`：路径、环境变量、设置与基础校验
- `src/db.py`：SQLite 初始化与连接
- `src/projects.py`：项目扫描、治理评分与 Git 仓库操作
- `src/tasks.py`：任务查询、状态同步、执行报告模型
- `src/tools.py`：AI 工具探测、ACP 命令、Token 优先路由
- `src/dispatch.py`：后台任务执行器与运行日志
- `src/routes.py`：Flask 页面与 API 路由
- `src/app.py`：应用组装与模块导出

## 常驻服务（launchd）

安装并立即启动：

```bash
cd ~/company/ceo-console
./scripts/install-launchd.sh
```

卸载：

```bash
cd ~/company/ceo-console
./scripts/uninstall-launchd.sh
```

查看状态：

```bash
./scripts/status-launchd.sh
```

日志文件：

- `data/launchd.out.log`
- `data/launchd.err.log`

## 主要 API

- `GET /api/projects`
- `POST /api/projects`（创建项目）
- `POST /api/projects/<name>/archive`
- `POST /api/projects/<name>/unarchive`
- `DELETE /api/projects/<name>`（需 `confirm_name`）
- `GET /api/tools/status`
- `GET /api/company-operating-system`
- `GET /api/tasks`
- `GET /api/tasks?q=&project=&status=&priority=&execution_state=`
- `GET /api/tasks/export`
- `POST /api/tasks`
- `POST /api/tasks/bulk`
- `PATCH /api/tasks/<id>`
- `DELETE /api/tasks/<id>`
- `POST /api/tasks/<id>/dispatch`
- `POST /api/tasks/<id>/retry`
- `GET /api/dashboard-summary`
- `GET /api/daily-brief`

> 说明：`GET /api/audit-events` 仍在规划中，当前版本暂未提供该接口。

## 数据文件

- `data/ceo_console.db`：SQLite 任务数据库（自动创建）
