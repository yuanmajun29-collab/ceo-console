<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { endpoints } from "@/api/endpoints";
import type { AgiForMeTask, CommanderStatus, Task } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import SectionCard from "@/components/SectionCard.vue";

const message = useMessage();
const intent = ref("");
const context = ref("");
const loading = ref(false);
const refreshing = ref(false);
const status = ref<CommanderStatus | null>(null);
const agiTasks = ref<AgiForMeTask[]>([]);
const selectedAgiId = ref<string | null>(null);
const selectedTaskId = ref<number | null>(null);
let timer: number | undefined;

const tasks = computed(() => status.value?.tasks ?? []);
const selectedAgiTask = computed(() => agiTasks.value.find((task) => task.id === selectedAgiId.value) ?? agiTasks.value[0] ?? null);
const selectedTask = computed(() => tasks.value.find((task) => task.id === selectedTaskId.value) ?? tasks.value[0] ?? null);
const progressLines = computed(() => {
  const progress = selectedTask.value?.execution_progress || "";
  return progress.split("\n").filter(Boolean).slice(-80);
});

function rowProps(row: Task) {
  return {
    class: selectedTask.value?.id === row.id ? "active-row" : "",
    onClick: () => {
      selectedTaskId.value = row.id;
    },
  };
}

function taskIcon(task: Task) {
  const tool = (task.assignee_ai || "").toLowerCase();
  if (tool.includes("codex")) return "⌘";
  if (tool.includes("claude")) return "C";
  if (tool.includes("gemini")) return "G";
  if (tool.includes("cursor")) return "↯";
  return "AI";
}

function stateIcon(state: string) {
  if (/done|success|complete|完成|成功/i.test(state)) return "✅";
  if (/fail|error|失败|错误/i.test(state)) return "❌";
  if (/running|progress|执行|运行/i.test(state)) return "⏳";
  return "·";
}

async function loadStatus() {
  refreshing.value = true;
  try {
    status.value = await endpoints.commanderStatus();
    agiTasks.value = (await endpoints.agiTasks()).tasks;
    if (!selectedTaskId.value && status.value.tasks[0]) {
      selectedTaskId.value = status.value.tasks[0].id;
    }
    if (!selectedAgiId.value && agiTasks.value[0]) {
      selectedAgiId.value = agiTasks.value[0].id;
    }
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    refreshing.value = false;
  }
}

async function execute() {
  const value = intent.value.trim();
  if (!value) {
    message.warning("请输入要执行的目标");
    return;
  }
  loading.value = true;
  try {
    const result = await endpoints.createAgiTask({ intent: value, context: context.value });
    selectedAgiId.value = result.id;
    intent.value = "";
    context.value = "";
    message.success(`AGI 任务 ${result.id} 已创建，状态：${result.status}`);
    await loadStatus();
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    loading.value = false;
  }
}

async function dispatchAgi(task: AgiForMeTask) {
  try {
    await endpoints.dispatchAgiTask(task.id);
    message.success("已派发 AGI 任务");
    await loadStatus();
  } catch (err) {
    message.error((err as Error).message);
  }
}

async function approveAgi(task: AgiForMeTask) {
  try {
    await endpoints.approveAgiTask(task.id, "CEO Console 人工批准");
    message.success("已记录人工批准");
    await loadStatus();
  } catch (err) {
    message.error((err as Error).message);
  }
}

onMounted(() => {
  loadStatus();
  timer = window.setInterval(loadStatus, 5000);
});

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
});
</script>

<template>
  <PageHeader
    title="AI Commander"
    :subtitle="`${status?.counts.total ?? 0} · ${status?.counts.running ?? 0}`"
  >
    <template #extra>
      <n-button size="small" :loading="refreshing" title="刷新" @click="loadStatus">
        <template #icon>↻</template>
      </n-button>
    </template>
  </PageHeader>

  <div class="commander">
    <SectionCard title="AGI for Me 统一入口">
      <div class="input-stack">
        <n-input
          v-model:value="intent"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 4 }"
          placeholder="输入目标，系统将判断权限、选择 AI 并按需召集 Council"
        />
        <n-input
          v-model:value="context"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 3 }"
          placeholder="补充上下文"
        />
        <div class="actions">
          <n-button type="primary" :loading="loading" title="创建治理任务" @click="execute">
            创建 AGI 任务
          </n-button>
        </div>
      </div>
    </SectionCard>

    <SectionCard title="AGI 治理队列" :subtitle="`${agiTasks.length} 个任务`">
      <div class="agi-grid">
        <button
          v-for="task in agiTasks"
          :key="task.id"
          class="agi-card"
          :class="{ active: selectedAgiTask?.id === task.id }"
          type="button"
          @click="selectedAgiId = task.id"
        >
          <div class="agi-title"><b>{{ task.intent }}</b><span>{{ task.status }}</span></div>
          <div class="agi-meta">
            <n-tag size="small" :type="task.authority === 'L3' ? 'error' : 'success'">{{ task.authority }}</n-tag>
            <span>{{ task.assigned_tools.join(" · ") }}</span>
            <span v-if="task.council_required">
              Council {{ task.council?.responded?.length ?? 0 }}/{{ task.council?.quorum ?? 3 }}
            </span>
          </div>
        </button>
      </div>
      <div v-if="selectedAgiTask" class="agi-actions">
        <span>{{ selectedAgiTask.authority_reason }}</span>
        <n-button
          v-if="selectedAgiTask.status === 'awaiting_approval'"
          size="small"
          type="warning"
          @click="approveAgi(selectedAgiTask)"
        >人工批准</n-button>
        <n-button
          v-if="selectedAgiTask.status === 'planned'"
          size="small"
          type="primary"
          @click="dispatchAgi(selectedAgiTask)"
        >派发</n-button>
        <n-tag v-if="selectedAgiTask.council?.quorum_met" size="small" type="success">Quorum 已达成</n-tag>
      </div>
    </SectionCard>

    <div class="grid">
      <SectionCard title="下层执行队列">
        <div class="queue-list">
          <button
            v-for="task in tasks"
            :key="task.id"
            class="queue-row"
            :class="{ active: selectedTask?.id === task.id }"
            type="button"
            @click="rowProps(task).onClick()"
          >
            <span class="tool">{{ taskIcon(task) }}</span>
            <span class="state">{{ stateIcon(task.execution_state) }}</span>
            <b>#{{ task.id }}</b>
            <span>{{ task.title }}</span>
          </button>
        </div>
      </SectionCard>

      <SectionCard
        title="日志"
        :subtitle="selectedTask ? `#${selectedTask.id} · ${selectedTask.execution_state}` : ''"
      >
        <div v-if="selectedTask" class="task-meta">
          <n-tag size="small" type="info">{{ selectedTask.assignee_ai }}</n-tag>
          <span>{{ selectedTask.routing_reason || "-" }}</span>
        </div>
        <pre class="log-box">{{ progressLines.join("\n") || "-" }}</pre>
        <div v-if="selectedTask?.execution_error" class="error-box">
          {{ selectedTask.execution_error }}
        </div>
      </SectionCard>
    </div>
  </div>
</template>

<style scoped>
.commander {
  display: grid;
  gap: 16px;
}
.input-stack {
  display: grid;
  gap: 8px;
}
.actions {
  display: flex;
  justify-content: flex-end;
}
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.75fr);
  gap: 12px;
  align-items: start;
}
.agi-grid {
  display: grid;
  gap: 8px;
}
.agi-card {
  display: grid;
  gap: 6px;
  width: 100%;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}
.agi-card.active {
  border-color: #2563eb;
  background: #eff6ff;
}
.agi-title,
.agi-meta,
.agi-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}
.agi-meta,
.agi-actions {
  justify-content: flex-start;
  color: #64748b;
  font-size: 12px;
}
.agi-actions {
  margin-top: 10px;
  flex-wrap: wrap;
}
.queue-list {
  display: grid;
  gap: 6px;
}
.queue-row {
  display: grid;
  grid-template-columns: 32px 24px 56px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  width: 100%;
  padding: 7px 9px;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  background: #fff;
  color: #475569;
  text-align: left;
  cursor: pointer;
}
.queue-row.active {
  border-color: #2563eb;
  background: #eff6ff;
}
.queue-row b,
.queue-row span:last-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool {
  display: grid;
  place-items: center;
  min-width: 0;
  height: 24px;
  border-radius: 6px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 800;
}
.state {
  text-align: center;
}
.task-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
  color: #64748b;
  font-size: 12px;
}
.log-box {
  min-height: 300px;
  max-height: 520px;
  overflow: auto;
  margin: 0;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #0f172a;
  color: #dbeafe;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
}
.error-box {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fef2f2;
  color: #991b1b;
  font-size: 12px;
}
@media (max-width: 980px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 640px) {
  .actions {
    justify-content: stretch;
  }
  .actions :deep(.n-button) {
    width: 100%;
  }
  .task-meta {
    align-items: flex-start;
    flex-direction: column;
  }
  .log-box {
    min-height: 260px;
    max-height: 420px;
  }
}
</style>
