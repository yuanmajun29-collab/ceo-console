# CEO Console 测试覆盖矩阵

## 后端 API

- 首页与缓存头：`/`、全 API `Cache-Control: no-store`
- 项目管理：创建、归档、恢复、删除、非法项目名与路径穿越阻断
- 任务管理：创建、筛选、排序、编辑、删除、批量更新、CSV 导出
- 任务闭环：智能路由、调度启动、重试、人工通过、人工驳回
- 指挥台：评审队列、失败调度、超时任务、待路由任务的优先级排序
- 报表：运营报表汇总项目、任务、仓库、决策日志
- 设置：保存、归一化、持久化、恢复默认、工具重测
- 健康检查：运行配置、目录权限、工具状态、ACP 脚本状态

## ACP 五端互通

- `acp-agent` / `acp-all-status` 发现
- `/api/acp/summary` 轻量状态
- `/api/acp/status` 完整体检输出解析
- 五端工具 ACP target 映射：
  - Cursor -> `cursor`
  - Antigravity -> `antigravity`
  - Claude Code -> `claude`
  - Codex -> `codex`
  - Gemini -> `gemini`
- 后台调度优先通过 `acp-agent` 包装执行
- Cursor 交互模式不会被误判为后台无头可执行

## 项目治理与仓库

- `docs/执行清单.md` 完成率解析
- `docs/ADR-*.md` 数量统计
- `CLAUDE.md`、`.cursorrules`、`.agent-coordinator` 治理资产识别
- 顶层 Git 仓库扫描
- 嵌套 Git 子仓库扫描
- Git dirty/clean、分支、远端、最近提交、异常状态处理

## 调度 Worker

- 成功执行后进入待人工审查
- Cursor 不支持无头时自动回退可调度工具
- 无可用工具时进入 unsupported
- 超时任务终止并记录失败原因

## 前端契约

- 核心模块 DOM id 存在性：
  - 项目治理
  - AI 工具与 ACP
  - CEO 指挥台
  - 决策日志
  - 报表中心
  - 设置中心
  - 数据看板
  - 代码仓库
  - 工作队列
  - 任务详情
- 核心 JS 函数存在性：
  - `loadAll`
  - `createTask`
  - `routeTask`
  - `dispatchTask`
  - `reviewTask`
  - `saveSettings`
  - `loadAcpStatus`
  - `renderAnalytics`

## 浏览器 E2E

- 创建项目
- 创建任务
- 看板导航
- 调度任务进入待审查
- 审查通过进入已完成

如果本机 Playwright 浏览器二进制未安装，E2E 会自动跳过，避免把环境缺失误报为业务失败。
