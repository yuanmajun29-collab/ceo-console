<script setup lang="ts">
import { computed, h, ref } from "vue";
import { storeToRefs } from "pinia";
import { NButton, NTag, useDialog, useMessage, type DataTableColumns } from "naive-ui";
import { api } from "@/api/client";
import { useDashboardStore } from "@/stores/dashboard";
import { useUiStore } from "@/stores/ui";
import { endpoints } from "@/api/endpoints";
import type { Priority, Task, TaskStatus } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import SectionCard from "@/components/SectionCard.vue";
import StatusPill from "@/components/StatusPill.vue";
import EmptyState from "@/components/EmptyState.vue";

const store = useDashboardStore();
const ui = useUiStore();
const { tasks } = storeToRefs(store);
const message = useMessage();
const dialog = useDialog();

const selectedIds = ref<number[]>([]);
const bulkRunning = ref(false);

const selectedTasks = computed(() =>
  store.tasks.filter((t) => selectedIds.value.includes(t.id))
);

const bulkDispatchable = computed(() =>
  selectedTasks.value.filter(
    (t) => t.execution_state === "idle" && t.status === "待分配"
  ).length
);
const bulkRetryable = computed(() =>
  selectedTasks.value.filter((t) =>
    ["failed", "unsupported"].includes(t.execution_state)
  ).length
);
const bulkReviewable = computed(() =>
  selectedTasks.value.filter((t) => t.status === "待人工审查").length
);

function summarizeSkipped(skipped: Array<{ id: number; reason: string }>): string {
  if (!skipped.length) return "";
  const head = skipped.slice(0, 3).map((s) => `#${s.id}（${s.reason}）`).join("，");
  return skipped.length > 3 ? `${head}，等 ${skipped.length} 个` : head;
}

async function bulkDispatch() {
  if (selectedIds.value.length === 0) return;
  dialog.warning({
    title: `调度 ${selectedIds.value.length} 个任务？`,
    content: "服务端会逐个校验并启动后台 worker，单次最多 50 个。",
    positiveText: "开始调度",
    negativeText: "取消",
    onPositiveClick: async () => {
      bulkRunning.value = true;
      try {
        const res = await endpoints.bulkDispatch(selectedIds.value);
        const note = res.skipped.length
          ? `跳过 ${res.skipped.length}：${summarizeSkipped(res.skipped)}`
          : "";
        if (res.queued_count > 0) {
          message.success(`已发起 ${res.queued_count} 个调度${note ? "；" + note : ""}`);
        } else {
          message.warning(note || "没有可调度任务");
        }
        selectedIds.value = [];
        await store.loadAll();
      } catch (err) {
        message.error((err as Error).message);
      } finally {
        bulkRunning.value = false;
      }
    },
  });
}

async function bulkRetry() {
  if (selectedIds.value.length === 0) return;
  bulkRunning.value = true;
  try {
    const res = await endpoints.bulkRetry(selectedIds.value);
    const note = res.skipped.length
      ? `跳过 ${res.skipped.length}：${summarizeSkipped(res.skipped)}`
      : "";
    if (res.queued_count > 0) {
      message.success(`已重试 ${res.queued_count} 个${note ? "；" + note : ""}`);
    } else {
      message.warning(note || "没有可重试任务");
    }
    selectedIds.value = [];
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    bulkRunning.value = false;
  }
}

async function bulkApprove() {
  if (selectedIds.value.length === 0) return;
  dialog.warning({
    title: `批量通过 ${selectedIds.value.length} 个任务？`,
    content: "建议仅对低风险任务使用批量通过。高风险任务请单独评审。服务端会自动跳过非「待人工审查」状态的任务。",
    positiveText: "全部通过",
    negativeText: "取消",
    onPositiveClick: async () => {
      bulkRunning.value = true;
      try {
        const res = await endpoints.bulkReview(selectedIds.value, "approve", "批量通过");
        const note = res.skipped.length
          ? `跳过 ${res.skipped.length}：${summarizeSkipped(res.skipped)}`
          : "";
        if (res.applied_count > 0) {
          message.success(`已通过 ${res.applied_count} 个${note ? "；" + note : ""}`);
        } else {
          message.warning(note || "没有可评审任务");
        }
        selectedIds.value = [];
        await store.loadAll();
      } catch (err) {
        message.error((err as Error).message);
      } finally {
        bulkRunning.value = false;
      }
    },
  });
}

async function bulkSetStatus(newStatus: "待分配" | "AI执行中" | "待人工审查" | "已完成") {
  if (selectedIds.value.length === 0) return;
  try {
    await api.post<{ ok: boolean; updated_count: number }>("/api/tasks/bulk", {
      ids: selectedIds.value,
      status: newStatus,
    });
    message.success(`已将 ${selectedIds.value.length} 个任务改为「${newStatus}」`);
    selectedIds.value = [];
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}

function clearSelection() {
  selectedIds.value = [];
}

const view = ref<"kanban" | "table">("kanban");
const search = ref("");
const projectFilter = ref<string | null>(null);
const priorityFilter = ref<Priority | null>(null);
const aiFilter = ref<string | null>(null);

const projects = computed(() => {
  const s = new Set(tasks.value.map((t) => t.project));
  return Array.from(s).sort();
});
const aiNames = computed(() => {
  const s = new Set(tasks.value.map((t) => t.assignee_ai));
  return Array.from(s).sort();
});

const filtered = computed(() =>
  tasks.value.filter((t) => {
    if (search.value) {
      const q = search.value.toLowerCase();
      if (
        !t.title.toLowerCase().includes(q) &&
        !t.project.toLowerCase().includes(q) &&
        !(t.notes ?? "").toLowerCase().includes(q)
      )
        return false;
    }
    if (projectFilter.value && t.project !== projectFilter.value) return false;
    if (priorityFilter.value && t.priority !== priorityFilter.value) return false;
    if (aiFilter.value && t.assignee_ai !== aiFilter.value) return false;
    return true;
  })
);

const columns: TaskStatus[] = ["待分配", "AI执行中", "待人工审查", "已完成"];
const grouped = computed(() => {
  const buckets: Record<TaskStatus, Task[]> = {
    待分配: [],
    AI执行中: [],
    待人工审查: [],
    已完成: [],
  };
  for (const t of filtered.value) buckets[t.status].push(t);
  return buckets;
});

async function dispatchTask(id: number) {
  try {
    await endpoints.dispatchTask(id);
    message.success("已发起调度");
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function retryTask(id: number) {
  try {
    await endpoints.retryTask(id);
    message.success("已重新调度");
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function approveTask(id: number) {
  try {
    await endpoints.reviewTask(id, "approve");
    message.success("通过");
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function routeTask(id: number) {
  try {
    const r = await endpoints.routeTask(id);
    message.success(`已路由到 ${r.tool}`);
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}

const tableColumns: DataTableColumns<Task> = [
  { type: "selection", width: 36 },
  {
    title: "标题",
    key: "title",
    render: (row) =>
      h("div", { class: "task-cell clickable", onClick: () => ui.openTask(row.id) }, [
        h("div", { class: "task-title" }, row.title),
        h("div", { class: "task-meta" }, [
          h("span", { class: "task-project" }, row.project),
          " · ",
          h("span", row.task_type),
        ]),
      ]),
  },
  {
    title: "优先级",
    key: "priority",
    width: 80,
    render: (row) =>
      h(
        NTag,
        {
          size: "small",
          type:
            row.priority === "P0" ? "error" : row.priority === "P1" ? "warning" : "default",
          bordered: false,
        },
        { default: () => row.priority }
      ),
  },
  {
    title: "状态",
    key: "status",
    width: 100,
    render: (row) => h(StatusPill, { status: row.status }),
  },
  {
    title: "AI",
    key: "assignee_ai",
    width: 130,
    render: (row) => h("span", { class: "subtle" }, row.assignee_ai),
  },
  {
    title: "执行",
    key: "execution_state",
    width: 110,
    render: (row) => h(StatusPill, { execution: row.execution_state }),
  },
  {
    title: "更新",
    key: "updated_at",
    width: 150,
    render: (row) => h("span", { class: "mono" }, row.updated_at),
  },
  {
    title: "操作",
    key: "actions",
    width: 170,
    render: (row) =>
      h("div", { class: "row-actions" }, [
        row.execution_state === "idle" && row.status === "待分配"
          ? h(
              NButton,
              { size: "tiny", type: "primary", onClick: () => dispatchTask(row.id) },
              { default: () => "执行" }
            )
          : null,
        ["failed", "unsupported"].includes(row.execution_state)
          ? h(
              NButton,
              { size: "tiny", type: "warning", onClick: () => retryTask(row.id) },
              { default: () => "重试" }
            )
          : null,
        row.status === "待人工审查"
          ? h(
              NButton,
              { size: "tiny", type: "primary", onClick: () => approveTask(row.id) },
              { default: () => "通过" }
            )
          : null,
        h(
          NButton,
          { size: "tiny", ghost: true, onClick: () => routeTask(row.id) },
          { default: () => "智能路由" }
        ),
      ]),
  },
];

function clearFilters() {
  search.value = "";
  projectFilter.value = null;
  priorityFilter.value = null;
  aiFilter.value = null;
}

function exportCsv() {
  window.open("/api/tasks/export", "_blank");
}
</script>

<template>
  <PageHeader
    title="任务中心"
    :subtitle="`全量任务：${tasks.length} · 过滤后：${filtered.length}`"
  >
    <template #extra>
      <n-radio-group v-model:value="view" size="small">
        <n-radio-button value="kanban">看板</n-radio-button>
        <n-radio-button value="table">表格</n-radio-button>
      </n-radio-group>
      <n-button size="small" @click="exportCsv">导出 CSV</n-button>
      <n-button size="small" type="primary" @click="store.loadAll()">刷新</n-button>
    </template>
  </PageHeader>

  <div class="filter-bar">
    <n-input
      v-model:value="search"
      size="small"
      placeholder="搜索标题 / 项目 / 备注"
      clearable
      style="max-width: 280px"
    />
    <n-select
      v-model:value="projectFilter"
      :options="projects.map((p) => ({ label: p, value: p }))"
      placeholder="项目"
      size="small"
      clearable
      style="width: 160px"
    />
    <n-select
      v-model:value="priorityFilter"
      :options="[
        { label: 'P0', value: 'P0' },
        { label: 'P1', value: 'P1' },
        { label: 'P2', value: 'P2' },
      ]"
      placeholder="优先级"
      size="small"
      clearable
      style="width: 120px"
    />
    <n-select
      v-model:value="aiFilter"
      :options="aiNames.map((a) => ({ label: a, value: a }))"
      placeholder="AI 执行端"
      size="small"
      clearable
      style="width: 160px"
    />
    <n-button size="small" ghost @click="clearFilters">清空</n-button>
  </div>

  <div v-if="view === 'kanban'" class="kanban">
    <div v-for="col in columns" :key="col" class="kanban-col">
      <div class="col-head">
        <span>{{ col }}</span>
        <span class="count">{{ grouped[col].length }}</span>
      </div>
      <div class="col-body">
        <EmptyState v-if="grouped[col].length === 0" icon="∅" title="无任务" />
        <div
          v-for="t in grouped[col]"
          :key="t.id"
          class="card"
          @click="ui.openTask(t.id)"
        >
          <div class="card-head">
            <n-tag
              size="tiny"
              :type="t.priority === 'P0' ? 'error' : t.priority === 'P1' ? 'warning' : 'default'"
              :bordered="false"
            >
              {{ t.priority }}
            </n-tag>
            <span class="card-title">{{ t.title }}</span>
          </div>
          <div class="card-meta">
            <span class="proj">{{ t.project }}</span>
            <span class="sep">·</span>
            <span>{{ t.assignee_ai }}</span>
          </div>
          <div v-if="t.execution_error" class="card-err">{{ t.execution_error }}</div>
          <div class="card-foot">
            <StatusPill :execution="t.execution_state" />
            <span class="when">{{ t.updated_at }}</span>
          </div>
          <div class="card-actions" @click.stop>
            <n-button
              v-if="t.execution_state === 'idle' && t.status === '待分配'"
              size="tiny"
              type="primary"
              @click="dispatchTask(t.id)"
            >
              执行
            </n-button>
            <n-button
              v-if="['failed', 'unsupported'].includes(t.execution_state)"
              size="tiny"
              type="warning"
              @click="retryTask(t.id)"
            >
              重试
            </n-button>
            <n-button
              v-if="t.status === '待人工审查'"
              size="tiny"
              type="primary"
              @click="approveTask(t.id)"
            >
              通过
            </n-button>
            <n-button size="tiny" ghost @click="routeTask(t.id)">路由</n-button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <SectionCard v-else title="所有任务" :subtitle="`${filtered.length} 行 · 已选 ${selectedIds.length}`">
    <n-data-table
      :columns="tableColumns"
      :data="filtered"
      :pagination="{ pageSize: 20 }"
      :row-key="(row: Task) => row.id"
      :checked-row-keys="selectedIds"
      @update:checked-row-keys="(keys: (string | number)[]) => (selectedIds = keys as number[])"
      striped
      size="small"
    />
  </SectionCard>

  <transition name="slide-up">
    <div v-if="selectedIds.length > 0" class="bulk-bar">
      <div class="bulk-info">
        已选 <b>{{ selectedIds.length }}</b> 个任务
        <span class="bulk-stats">
          <span v-if="bulkDispatchable" class="stat dispatch">可调度 {{ bulkDispatchable }}</span>
          <span v-if="bulkRetryable" class="stat retry">可重试 {{ bulkRetryable }}</span>
          <span v-if="bulkReviewable" class="stat review">可评审 {{ bulkReviewable }}</span>
        </span>
      </div>
      <div class="bulk-actions">
        <n-button
          size="small"
          type="primary"
          :loading="bulkRunning"
          :disabled="!bulkDispatchable"
          @click="bulkDispatch"
        >
          调度选中 ({{ bulkDispatchable }})
        </n-button>
        <n-button
          size="small"
          type="warning"
          :loading="bulkRunning"
          :disabled="!bulkRetryable"
          @click="bulkRetry"
        >
          重试失败 ({{ bulkRetryable }})
        </n-button>
        <n-button
          size="small"
          type="success"
          :loading="bulkRunning"
          :disabled="!bulkReviewable"
          @click="bulkApprove"
        >
          批量通过 ({{ bulkReviewable }})
        </n-button>
        <n-dropdown
          trigger="click"
          :options="[
            { label: '改为 待分配', key: '待分配' },
            { label: '改为 AI执行中', key: 'AI执行中' },
            { label: '改为 待人工审查', key: '待人工审查' },
            { label: '改为 已完成', key: '已完成' },
          ]"
          @select="(key: string) => bulkSetStatus(key as any)"
        >
          <n-button size="small">改状态 ▾</n-button>
        </n-dropdown>
        <div class="bulk-divider" />
        <n-button size="small" ghost @click="clearSelection">取消选择</n-button>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.filter-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.kanban {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.kanban-col {
  background: #f4f7fb;
  border-radius: 10px;
  padding: 10px;
  min-height: 200px;
}
.col-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 4px 10px;
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}
.count {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 11px;
  color: #475569;
}
.col-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.card:hover {
  border-color: #0b67f0;
  box-shadow: 0 2px 10px rgba(11, 103, 240, 0.12);
}
:deep(.task-cell.clickable) {
  cursor: pointer;
}
:deep(.task-cell.clickable:hover) .task-title {
  color: #0b67f0;
}
.card-head {
  display: flex;
  gap: 6px;
  align-items: flex-start;
}
.card-title {
  font-size: 13px;
  font-weight: 600;
  flex: 1;
  line-height: 1.35;
}
.card-meta {
  font-size: 11px;
  color: #64748b;
  display: flex;
  gap: 4px;
}
.card-meta .proj {
  color: #0b67f0;
  font-weight: 600;
}
.card-meta .sep {
  color: #cbd5e1;
}
.card-err {
  font-size: 11px;
  color: #b91c1c;
  background: #fef2f2;
  padding: 4px 6px;
  border-radius: 4px;
}
.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-foot .when {
  font-size: 10px;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.card-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
:deep(.task-cell) .task-title {
  font-weight: 600;
  font-size: 13px;
}
:deep(.task-cell) .task-meta {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}
:deep(.task-cell) .task-project {
  color: #0b67f0;
  font-weight: 600;
}
:deep(.row-actions) {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
:deep(.subtle) {
  color: #475569;
  font-size: 12px;
}
:deep(.mono) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: #64748b;
}

@media (max-width: 1100px) {
  .kanban {
    grid-template-columns: repeat(2, 1fr);
  }
}
.bulk-bar {
  position: fixed;
  left: 50%;
  bottom: 20px;
  transform: translateX(-50%);
  z-index: 50;
  background: #0f172a;
  color: #fff;
  border-radius: 12px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.35);
  max-width: calc(100vw - 32px);
  flex-wrap: wrap;
}
.bulk-info {
  font-size: 13px;
  color: #e2e8f0;
  display: flex;
  align-items: center;
  gap: 12px;
}
.bulk-info b {
  color: #fff;
  font-size: 15px;
  margin: 0 4px;
}
.bulk-stats {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.bulk-stats .stat {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
}
.bulk-stats .stat.dispatch {
  background: rgba(11, 103, 240, 0.3);
}
.bulk-stats .stat.retry {
  background: rgba(249, 115, 22, 0.3);
}
.bulk-stats .stat.review {
  background: rgba(22, 163, 74, 0.3);
}
.bulk-actions {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.bulk-divider {
  width: 1px;
  height: 18px;
  background: rgba(255, 255, 255, 0.15);
  margin: 0 4px;
}
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.25s ease-out, opacity 0.2s;
}
.slide-up-enter-from,
.slide-up-leave-to {
  transform: translate(-50%, 30px);
  opacity: 0;
}
</style>
