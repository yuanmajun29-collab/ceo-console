# AI as Me

CEO Console 的 AI as Me 是一个受授权、可审计的决策代理，不是假冒用户身份。

## 默认模式

权威配置位于：

`~/Documents/Obsidian Vault/02-工作人格与偏好/AI-as-Me/authority.yaml`

默认 `mode: shadow`，只输出建议并记录决策，不执行任务。

| 模式 | 最大权限 | 行为 |
|---|---|---|
| `shadow` | L0 | 只分析和记录 |
| `copilot` | L1 | 生成草稿，等待批准 |
| `delegated` | L2 | 仅执行明确允许的内部可撤销动作 |

L3 包含付款、合同签署、外部发送、公开发布、删除和凭证操作，永远必须人工审批。
第一版只有 `dispatch_task` 接通执行适配器；其他动作即使进入授权列表，也会在
执行适配器完成前保持建议模式。

## API

```bash
curl -X POST http://127.0.0.1:5050/api/ai-as-me/decide \
  -H 'Content-Type: application/json' \
  -d '{"intent":"创建任务检查项目风险","execute":false}'

curl http://127.0.0.1:5050/api/ai-as-me/status

curl -X POST http://127.0.0.1:5050/api/ai-as-me/feedback \
  -H 'Content-Type: application/json' \
  -d '{"decision_id":1,"feedback":"approve","comment":"符合我的判断"}'
```

反馈支持 `approve`、`reject`、`modify`，后续相似决策会参考历史反馈调整置信度。
批准会写入 `AI-as-Me/decision-cases/`；驳回和修改会写入
`AI-as-Me/corrections/`，并通过 Company AI-OS 同步到其他设备。
