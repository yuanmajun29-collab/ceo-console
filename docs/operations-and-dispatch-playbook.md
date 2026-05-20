# CEO Operations and AI Tool Dispatch Playbook

This playbook defines how the one-person-company CEO operates projects through CEO Console and dispatches Cursor, Antigravity, Claude Code, Gemini, and Codex.

The principle is simple:

> The CEO makes decisions. The platform coordinates AI execution.

## 1. CEO Control Framework

CEO Console should manage the company through three control surfaces.

### 1.1 Project Panorama

Purpose: keep every project visible and prevent project decay.

Required fields:

- Project name
- Stage: incubation, active, maintenance, archived
- AI project manager: primary tool or agent responsible for execution
- Weekly priority: P0, P1, P2
- Deadline
- Current risk level
- Last update
- Next CEO decision checkpoint

Weekly rule:

- Review all active projects.
- Promote only a few projects to P0/P1.
- Archive projects that no longer matter with `pm archive`.

### 1.2 Task Board

Purpose: turn vague ideas into task cards that AI tools can execute.

Task flow:

```text
待分配 -> AI执行中 -> 待人工审查 -> 已完成
```

Task card format:

- Title
- Project
- Assigned AI tool
- Priority
- Due time
- Instruction to AI
- Acceptance criteria
- Locked files or modules
- Review feedback

Instruction quality rule:

- A task must have a specific, verifiable goal.
- Acceptance criteria should describe what must be true when the task is done.
- If a human cannot review the output, the task is too vague.

### 1.3 Decision Log

Purpose: preserve human judgment as the shared memory layer.

Record a decision when:

- The CEO rejects an AI proposal.
- The CEO chooses architecture, product direction, or tradeoff.
- A project changes priority.
- A risk is accepted.
- A delivery is approved.

Decision format:

```text
Date:
Project:
Decision:
Context:
Reason:
Impact:
Follow-up tasks:
```

AI tools should read project decision logs before major implementation work.

## 2. Command-Style Project Dispatch Flow

Project execution should behave like command dispatch, not chaotic AI chatting.

### Phase 1: Concept and Design

CEO responsibility:

- Define why the project exists.
- Define success criteria.
- Approve or reject the proposed direction.

Tool dispatch:

| Tool | Role | Best Use |
| --- | --- | --- |
| Gemini | Market researcher / broad analyst | Competitor scan, reference implementation research, alternative approaches |
| Claude Code | System architect | Technical design, data model, module boundary, architecture decisions |

Output artifacts:

- Project brief
- Technical proposal
- Risk list
- Acceptance criteria
- Decision log entries under `docs/decisions/`

CEO checkpoint:

- Approve the technical direction before development starts.

### Phase 2: Core Development

CEO responsibility:

- Split approved design into independently executable work packages.
- Avoid letting multiple tools edit the same files at the same time.

Tool dispatch:

| Tool | Role | Best Use |
| --- | --- | --- |
| Antigravity / OpenClaw | Main full-stack executor | Independent feature modules, end-to-end local implementation |
| Cursor | Precision editor | Small fixes, style cleanup, IDE-centered refactor, local code navigation |
| Codex | Coding operator / sweeper | Tests, docs, repetitive edits, API polish, repository work |
| Claude Code | Deep implementer | Complex logic, architecture-sensitive code, code review fixes |
| Gemini | Fast reasoning assistant | Quick checks, external comparison, broad sanity review |

Development rule:

- Every task has a write scope.
- Every task has acceptance criteria.
- Every task must produce a short implementation summary and verification result.

### Phase 3: Review and Acceptance

CEO responsibility:

- Never skip human review for important deliverables.
- Approve, reject, or redirect work.

Cross-review loop:

| Reviewer | Review Focus |
| --- | --- |
| Gemini | Security, broad risk, missing edge cases |
| Claude Code | Code quality, maintainability, architecture fit |
| Codex | Tests, docs, integration consistency |
| CEO | Product correctness, business fit, final acceptance |

After approval:

- Update task status to complete.
- Update project milestone state.
- Record key decisions.
- Package delivery evidence.

## 3. Daily Operating Loop

Timebox: 10 minutes.

1. Open CEO Console.
2. Check risk cards.
3. Review tasks in `待人工审查`.
4. Approve or reject with feedback.
5. Check failed dispatches.
6. Retry safe failures or rewrite unclear tasks.
7. Confirm today’s P0/P1 priorities.

Daily rule:

- Do not start more work until review bottlenecks are cleared.

## 4. Weekly Operating Loop

Timebox: 30 minutes.

1. Review project panorama.
2. Archive stale projects.
3. Promote only the most important projects.
4. Review recurring AI failure patterns.
5. Update `CLAUDE.md`, project rules, or global rules if the same issue repeats.
6. Write decision log entries for major product or architecture choices.
7. Select next week’s P0/P1 outcomes.

Weekly rule:

- A project without a next action is either archived or rewritten.

## 5. Exception Management

### AI produces unusable output

Likely cause:

- Context is stale.
- Task instruction is vague.
- Project rules are incomplete.

Control actions:

- Rewrite the task with sharper acceptance criteria.
- Start a clean context.
- Provide only the relevant files.
- Check shared project state.
- Update `CLAUDE.md` if this failure repeats.

### Multiple tools conflict on the same file

Likely cause:

- Work scopes were not isolated.

Control actions:

- Treat Git as the source of truth.
- Require latest code before dispatch.
- Add locked files/modules to task cards.
- Do not dispatch two tools to the same module unless one is review-only.

### Project count becomes overwhelming

Likely cause:

- Too many active initiatives.

Control actions:

- Archive stale projects.
- Limit active P0/P1 work.
- Write short retrospectives for completed projects.
- Convert repeated lessons into project rules and templates.

## 6. Tool Routing Rules

Default routing:

| Task Type | Primary Tool | Fallback |
| --- | --- | --- |
| Market scan / alternatives | Gemini | Claude Code |
| Architecture / data model | Claude Code | Codex |
| Full-stack feature | Antigravity | Claude Code |
| Local code edit / refactor | Cursor | Codex |
| Tests / docs / repetitive code changes | Codex | Claude Code |
| Security or broad risk review | Gemini | Claude Code |
| Final code-quality review | Claude Code | Codex |

Escalation rule:

- If the chosen tool is unavailable or cannot run headlessly, fall back to Claude Code or Gemini when possible.
- If two attempts fail, escalate to CEO with the error summary and suggested next action.

## 7. What CEO Console Should Automate Next

Near-term platform features:

- Project panorama fields in the database.
- Decision log model and UI.
- Task card instruction and acceptance templates.
- File/module lock field.
- Tool routing matrix in code.
- Dispatch preflight checks.
- Review checklist per task type.
- Delivery package generator.
- Daily and weekly brief generator.

