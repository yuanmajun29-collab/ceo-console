<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useMessage } from "naive-ui";
import { useDashboardStore } from "@/stores/dashboard";
import { endpoints } from "@/api/endpoints";
import type { Task } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import EmptyState from "@/components/EmptyState.vue";
import StatusPill from "@/components/StatusPill.vue";
import SectionCard from "@/components/SectionCard.vue";

const store = useDashboardStore();
const message = useMessage();

const reviewTasks = computed(() =>
  store.tasks.filter((t) => t.status === "待人工审查")
);

const failedTasks = computed(() =>
  store.tasks.filter((t) =>
    ["failed", "unsupported"].includes(t.execution_state)
  )
);

const selectedId = ref<number | null>(null);
const comment = ref("");
const tab = ref<"review" | "failed">("review");

watch(reviewTasks, (list) => {
  if (selectedId.value && !list.some((t) => t.id === selectedId.value) && tab.value === "review") {
    selectedId.value = list[0]?.id ?? null;
  } else if (!selectedId.value) {
    selectedId.value = list[0]?.id ?? null;
  }
});

const current = computed<Task | null>(() => {
  const id = selectedId.value;
  if (!id) return null;
  return store.tasks.find((t) => t.id === id) ?? null;
});

const activeList = computed(() => (tab.value === "review" ? reviewTasks.value : failedTasks.value));

watch(tab, () => {
  selectedId.value = activeList.value[0]?.id ?? null;
});

async function decide(decision: "approve" | "reject") {
  if (!current.value) return;
  try {
    await endpoints.reviewTask(current.value.id, decision, comment.value);
    message.success(decision === "approve" ? "已通过" : "已驳回");
    comment.value = "";
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function retry(id: number) {
  try {
    await endpoints.retryTask(id);
    message.success("已重新调度");
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}

function logTail(text: string | null, lines = 30): string {
  if (!text) return "（暂无日志）";
  const split = text.split(/\r?\n/);
  return split.slice(-lines).join("\n");
}
</script>

<template>
  <PageHeader
    title="评审中心"
    :subtitle="`待评审 ${reviewTasks.length} · 调度失败 ${failedTasks.length}`"
  >
    <template #extra>
      <n-radio-group v-model:value="tab" size="small">
        <n-radio-button value="review">待评审 {{ reviewTasks.length }}</n-radio-button>
        <n-radio-button value="failed">调度失败 {{ failedTasks.length }}</n-radio-button>
      </n-radio-group>
      <n-button size="small" type="primary" @click="store.loadAll()">刷新</n-button>
    </template>
  </PageHeader>

  <div class="layout">
    <aside class="list">
      <EmptyState
        v-if="activeList.length === 0"
        icon="✓"
        title="队列已清空"
        description="所有任务都已闭环或暂无失败任务"
      />
      <div
        v-for="t in activeList"
        :key="t.id"
        class="item"
        :class="{ active: t.id === selectedId }"
        @click="selectedId = t.id"
      >
        <div class="item-head">
          <n-tag
            size="tiny"
            :type="t.priority === 'P0' ? 'error' : t.priority === 'P1' ? 'warning' : 'default'"
            :bordered="false"
          >
            {{ t.priority }}
          </n-tag>
          <div class="item-title">{{ t.title }}</div>
        </div>
        <div class="item-meta">
          <span class="proj">{{ t.project }}</span>
          <span class="sep">·</span>
          <span>{{ t.assignee_ai }}</span>
        </div>
        <div class="item-foot">
          <StatusPill :execution="t.execution_state" />
          <span class="when">{{ t.updated_at }}</span>
        </div>
      </div>
    </aside>

    <main class="detail">
      <EmptyState
        v-if="!current"
        icon="◌"
        title="选择左侧任务查看详情"
      />
      <template v-else>
        <SectionCard :title="current.title" :subtitle="`#${current.id} · ${current.project}`">
          <template #extra>
            <n-button
              v-if="tab === 'failed'"
              size="small"
              type="warning"
              @click="retry(current.id)"
            >
              重新调度
            </n-button>
          </template>
          <div class="kv-grid">
            <div><span>状态</span><b>{{ current.status }}</b></div>
            <div><span>执行</span><b>{{ current.execution_state }}</b></div>
            <div><span>实际工具</span><b>{{ current.execution_tool ?? "-" }}</b></div>
            <div><span>优先级</span><b>{{ current.priority }}</b></div>
            <div><span>截止</span><b>{{ current.due_at ?? "-" }}</b></div>
            <div><span>更新</span><b>{{ current.updated_at }}</b></div>
          </div>
        </SectionCard>

        <SectionCard
          v-if="current.routing_reason"
          title="路由依据"
          subtitle="Token 优先链路 + 可用性"
        >
          <p class="reason">{{ current.routing_reason }}</p>
        </SectionCard>

        <SectionCard
          v-if="current.acceptance_criteria"
          title="验收标准"
        >
          <p class="reason">{{ current.acceptance_criteria }}</p>
        </SectionCard>

        <SectionCard
          v-if="current.execution_error"
          title="失败原因"
        >
          <pre class="err">{{ current.execution_error }}</pre>
        </SectionCard>

        <SectionCard title="执行日志（尾段）" :subtitle="`节选 30 行`">
          <pre class="log">{{ logTail(current.execution_output) }}</pre>
        </SectionCard>

        <SectionCard v-if="tab === 'review'" title="评审决定">
          <n-input
            v-model:value="comment"
            type="textarea"
            placeholder="评审意见（驳回时必填理由）"
            :autosize="{ minRows: 3, maxRows: 6 }"
          />
          <div class="decision-actions">
            <n-button type="primary" @click="decide('approve')">通过 · 关闭任务</n-button>
            <n-button type="error" ghost @click="decide('reject')">驳回 · 回到待分配</n-button>
          </div>
        </SectionCard>
      </template>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 16px;
  align-items: flex-start;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: calc(100vh - 200px);
  overflow-y: auto;
  padding-right: 4px;
}
.item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.item:hover {
  background: #f8fafc;
}
.item.active {
  border-color: #0b67f0;
  box-shadow: 0 0 0 3px rgba(11, 103, 240, 0.12);
}
.item-head {
  display: flex;
  gap: 6px;
  align-items: flex-start;
}
.item-title {
  font-size: 13px;
  font-weight: 600;
  flex: 1;
  line-height: 1.4;
}
.item-meta {
  font-size: 11px;
  color: #64748b;
  margin-top: 4px;
  display: flex;
  gap: 4px;
}
.item-meta .proj {
  color: #0b67f0;
  font-weight: 600;
}
.item-meta .sep {
  color: #cbd5e1;
}
.item-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
}
.when {
  font-size: 10px;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.detail {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}
.kv-grid div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  background: #f8fafc;
  border-radius: 6px;
}
.kv-grid span {
  font-size: 11px;
  color: #64748b;
}
.kv-grid b {
  font-size: 13px;
  color: #0f172a;
}
.reason {
  margin: 0;
  font-size: 13px;
  color: #334155;
  line-height: 1.6;
}
.err {
  margin: 0;
  font-size: 12px;
  color: #b91c1c;
  background: #fef2f2;
  padding: 10px 12px;
  border-radius: 6px;
  white-space: pre-wrap;
  overflow-x: auto;
}
.log {
  margin: 0;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #0f172a;
  color: #cbd5e1;
  padding: 10px 12px;
  border-radius: 6px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  line-height: 1.5;
}
.decision-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .list {
    max-height: none;
  }
}
</style>
