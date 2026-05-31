<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { useMessage } from "naive-ui";
import { endpoints } from "@/api/endpoints";
import type { Task } from "@/api/types";
import { useDashboardStore } from "@/stores/dashboard";
import StatusPill from "./StatusPill.vue";
import MetricBar from "./MetricBar.vue";

type StreamStatus = "idle" | "connecting" | "open" | "closed" | "error";

const props = defineProps<{
  taskId: number | null;
  show: boolean;
}>();
const emit = defineEmits<{
  (e: "update:show", v: boolean): void;
  (e: "changed"): void;
}>();

const store = useDashboardStore();
const message = useMessage();

const task = computed<Task | null>(() => {
  if (!props.taskId) return null;
  return store.tasks.find((t) => t.id === props.taskId) ?? null;
});

const reviewComment = ref("");
const editingScope = ref(false);
const edit = ref({
  acceptance_criteria: "",
  ai_instruction: "",
  locked_scope: "",
  expected_output: "",
});

const liveLog = ref<string>("");
const streamStatus = ref<StreamStatus>("idle");
let eventSource: EventSource | null = null;
let streamingTaskId: number | null = null;

function closeStream() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  if (streamStatus.value === "open" || streamStatus.value === "connecting") {
    streamStatus.value = "closed";
  }
  streamingTaskId = null;
}

function openStream(id: number) {
  closeStream();
  streamingTaskId = id;
  liveLog.value = "";
  streamStatus.value = "connecting";
  const es = new EventSource(`/api/tasks/${id}/log-stream`);
  eventSource = es;

  es.addEventListener("init", (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data);
      liveLog.value = data.content ?? "";
      streamStatus.value = "open";
    } catch {
      streamStatus.value = "error";
    }
  });
  es.addEventListener("append", (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data);
      if (data.content) liveLog.value += data.content;
    } catch {}
  });
  es.addEventListener("rotate", () => {
    liveLog.value = "";
  });
  es.addEventListener("done", () => {
    closeStream();
    store.loadAll();
  });
  es.addEventListener("timeout", () => {
    closeStream();
  });
  es.onerror = () => {
    streamStatus.value = "error";
    closeStream();
  };
}

watch(
  () => props.taskId,
  (id) => {
    if (id && task.value) {
      edit.value = {
        acceptance_criteria: task.value.acceptance_criteria ?? "",
        ai_instruction: task.value.ai_instruction ?? "",
        locked_scope: task.value.locked_scope ?? "",
        expected_output: task.value.expected_output ?? "",
      };
    }
    reviewComment.value = "";
    editingScope.value = false;
    liveLog.value = "";
    streamStatus.value = "idle";
  }
);

// Auto-open SSE stream when a running task is shown; auto-close on drawer
// close or state change away from running.
watch(
  [() => props.show, () => props.taskId, () => task.value?.execution_state],
  ([show, id, state]) => {
    const shouldStream =
      show && id !== null && state === "running";
    if (shouldStream && streamingTaskId !== id) {
      openStream(id as number);
    } else if (!shouldStream && eventSource) {
      closeStream();
    }
  },
  { immediate: true }
);

onUnmounted(() => closeStream());

const progress = computed(() => {
  if (!task.value) return 0;
  if (task.value.status === "已完成") return 100;
  if (task.value.execution_state === "succeeded") return 100;
  if (["failed", "unsupported"].includes(task.value.execution_state)) return 100;
  if (task.value.execution_state === "running") {
    const lines = (task.value.execution_progress ?? "").split(/\r?\n/).filter(Boolean).length;
    return Math.min(95, 20 + lines * 6);
  }
  return 0;
});

function logTail(text: string | null, lines = 40): string {
  if (!text) return "（暂无日志）";
  return text.split(/\r?\n/).slice(-lines).join("\n");
}

async function close() {
  emit("update:show", false);
}

async function dispatchTask() {
  if (!task.value) return;
  try {
    await endpoints.dispatchTask(task.value.id);
    message.success("已发起调度");
    await store.loadAll();
    emit("changed");
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function retryTask() {
  if (!task.value) return;
  try {
    await endpoints.retryTask(task.value.id);
    message.success("已重新调度");
    await store.loadAll();
    emit("changed");
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function routeTask() {
  if (!task.value) return;
  try {
    const r = await endpoints.routeTask(task.value.id);
    message.success(`已路由到 ${r.tool}`);
    await store.loadAll();
    emit("changed");
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function review(decision: "approve" | "reject") {
  if (!task.value) return;
  try {
    await endpoints.reviewTask(task.value.id, decision, reviewComment.value);
    message.success(decision === "approve" ? "已通过" : "已驳回");
    reviewComment.value = "";
    await store.loadAll();
    emit("changed");
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function saveScope() {
  if (!task.value) return;
  try {
    await endpoints.patchTask(task.value.id, { ...edit.value });
    message.success("已保存");
    editingScope.value = false;
    await store.loadAll();
    emit("changed");
  } catch (err) {
    message.error((err as Error).message);
  }
}
</script>

<template>
  <n-drawer
    :show="show"
    :width="540"
    placement="right"
    :auto-focus="false"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <n-drawer-content :title="task?.title ?? '任务详情'" closable>
      <template v-if="!task">
        <div class="empty">未找到该任务</div>
      </template>
      <template v-else>
        <header class="head">
          <div class="head-row">
            <n-tag
              size="small"
              :type="task.priority === 'P0' ? 'error' : task.priority === 'P1' ? 'warning' : 'default'"
              :bordered="false"
            >
              {{ task.priority }}
            </n-tag>
            <StatusPill :status="task.status" />
            <StatusPill :execution="task.execution_state" />
            <span class="muted">#{{ task.id }}</span>
          </div>
          <div class="head-meta">
            <span><b>{{ task.project }}</b></span>
            <span class="sep">·</span>
            <span>{{ task.task_type }}</span>
            <span class="sep">·</span>
            <span>{{ task.assignee_ai }}</span>
            <span v-if="task.execution_tool && task.execution_tool !== task.assignee_ai" class="sep">·</span>
            <span v-if="task.execution_tool && task.execution_tool !== task.assignee_ai">
              实际 {{ task.execution_tool }}
            </span>
          </div>
        </header>

        <section v-if="task.execution_state !== 'idle'" class="block">
          <div class="block-title">AI 执行进度</div>
          <MetricBar
            :value="progress"
            :tone="
              task.execution_state === 'failed' || task.execution_state === 'unsupported'
                ? 'red'
                : task.execution_state === 'succeeded'
                  ? 'green'
                  : 'blue'
            "
            :label="`已完成 ${progress}%`"
          />
          <div class="time-row">
            <span>开始 {{ task.execution_started_at ?? "-" }}</span>
            <span v-if="task.execution_finished_at">结束 {{ task.execution_finished_at }}</span>
          </div>
        </section>

        <section v-if="task.routing_reason" class="block">
          <div class="block-title">路由依据</div>
          <p class="reason">{{ task.routing_reason }}</p>
        </section>

        <section v-if="task.execution_error" class="block">
          <div class="block-title">失败原因</div>
          <pre class="err">{{ task.execution_error }}</pre>
        </section>

        <section class="block">
          <div class="block-title">
            执行日志
            <span class="log-status">
              <span
                v-if="streamStatus === 'open'"
                class="dot live"
                title="实时流连接中"
              />
              <span v-if="streamStatus === 'open'" class="muted">实时流 · 自动追加</span>
              <span v-else-if="streamStatus === 'connecting'" class="muted">连接中…</span>
              <span v-else-if="streamStatus === 'error'" class="muted error">连接失败</span>
              <span v-else-if="streamStatus === 'closed'" class="muted">流已关闭</span>
              <span v-else class="muted">尾段 40 行</span>
            </span>
          </div>
          <pre class="log" :class="{ 'log-live': streamStatus === 'open' }">{{ liveLog || logTail(task.execution_output) }}</pre>
        </section>

        <section class="block">
          <div class="block-title">
            任务字段
            <n-button v-if="!editingScope" size="tiny" ghost @click="editingScope = true">
              编辑
            </n-button>
            <span v-else class="edit-actions">
              <n-button size="tiny" @click="editingScope = false">取消</n-button>
              <n-button size="tiny" type="primary" @click="saveScope">保存</n-button>
            </span>
          </div>
          <template v-if="editingScope">
            <n-form label-placement="top" size="small">
              <n-form-item label="验收标准">
                <n-input
                  v-model:value="edit.acceptance_criteria"
                  type="textarea"
                  :autosize="{ minRows: 2, maxRows: 4 }"
                />
              </n-form-item>
              <n-form-item label="给 AI 的指令">
                <n-input
                  v-model:value="edit.ai_instruction"
                  type="textarea"
                  :autosize="{ minRows: 2, maxRows: 4 }"
                />
              </n-form-item>
              <n-form-item label="锁定范围">
                <n-input v-model:value="edit.locked_scope" />
              </n-form-item>
              <n-form-item label="预期产物">
                <n-input v-model:value="edit.expected_output" />
              </n-form-item>
            </n-form>
          </template>
          <div v-else class="kv-list">
            <div v-if="task.acceptance_criteria">
              <span>验收标准</span>
              <p>{{ task.acceptance_criteria }}</p>
            </div>
            <div v-if="task.ai_instruction">
              <span>给 AI 的指令</span>
              <p>{{ task.ai_instruction }}</p>
            </div>
            <div v-if="task.locked_scope">
              <span>锁定范围</span>
              <p>{{ task.locked_scope }}</p>
            </div>
            <div v-if="task.expected_output">
              <span>预期产物</span>
              <p>{{ task.expected_output }}</p>
            </div>
            <div v-if="task.due_at"><span>截止</span><p>{{ task.due_at }}</p></div>
            <div><span>创建</span><p>{{ task.created_at }}</p></div>
            <div><span>更新</span><p>{{ task.updated_at }}</p></div>
          </div>
        </section>

        <section v-if="task.status === '待人工审查'" class="block review-block">
          <div class="block-title">人工审查</div>
          <n-input
            v-model:value="reviewComment"
            type="textarea"
            placeholder="评审意见（驳回时必填理由）"
            :autosize="{ minRows: 2, maxRows: 4 }"
          />
          <div class="review-actions">
            <n-button type="primary" @click="review('approve')">通过 · 关闭</n-button>
            <n-button type="error" ghost @click="review('reject')">驳回 · 重开</n-button>
          </div>
        </section>
      </template>

      <template #footer>
        <div class="footer-bar">
          <n-button v-if="task" ghost @click="routeTask">智能路由</n-button>
          <n-button
            v-if="task && task.execution_state === 'idle' && task.status === '待分配'"
            type="primary"
            @click="dispatchTask"
          >
            开始执行
          </n-button>
          <n-button
            v-if="task && ['failed', 'unsupported'].includes(task.execution_state)"
            type="warning"
            @click="retryTask"
          >
            重新调度
          </n-button>
          <div style="flex:1" />
          <n-button @click="close">关闭</n-button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.empty {
  padding: 40px;
  text-align: center;
  color: #94a3b8;
}
.head {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e5e7eb;
}
.head-row {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.head-meta {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  color: #475569;
  flex-wrap: wrap;
}
.head-meta b {
  color: #0b67f0;
}
.head-meta .sep {
  color: #cbd5e1;
}
.muted {
  color: #94a3b8;
  font-size: 12px;
}
.block {
  padding: 14px 0;
  border-bottom: 1px solid #f1f5f9;
}
.block:last-of-type {
  border-bottom: 0;
}
.block-title {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.block-title .muted {
  text-transform: none;
  letter-spacing: 0;
  font-weight: 400;
}
.edit-actions {
  display: flex;
  gap: 4px;
}
.time-row {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: #94a3b8;
  margin-top: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.reason {
  margin: 0;
  font-size: 13px;
  color: #334155;
  line-height: 1.6;
  background: #f8fafc;
  padding: 8px 10px;
  border-radius: 6px;
  border-left: 3px solid #0b67f0;
}
.err {
  margin: 0;
  font-size: 12px;
  color: #b91c1c;
  background: #fef2f2;
  padding: 8px 10px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
}
.log {
  margin: 0;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #0f172a;
  color: #cbd5e1;
  padding: 10px 12px;
  border-radius: 6px;
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  line-height: 1.5;
}
.log-live {
  border: 1px solid rgba(34, 197, 94, 0.4);
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.08);
}
.log-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}
.log-status .muted {
  text-transform: none;
  letter-spacing: 0;
  font-weight: 400;
  color: #94a3b8;
}
.log-status .muted.error {
  color: #dc2626;
}
.dot.live {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.5);
  animation: pulse 1.6s ease-out infinite;
}
@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.5);
  }
  70% {
    box-shadow: 0 0 0 8px rgba(34, 197, 94, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0);
  }
}
.kv-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.kv-list div {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr);
  gap: 8px;
}
.kv-list span {
  color: #94a3b8;
  font-size: 12px;
}
.kv-list p {
  margin: 0;
  font-size: 13px;
  color: #0f172a;
  line-height: 1.5;
}
.review-block {
  background: #fffbeb;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid #fde68a;
}
.review-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.footer-bar {
  display: flex;
  gap: 8px;
  width: 100%;
}
</style>
