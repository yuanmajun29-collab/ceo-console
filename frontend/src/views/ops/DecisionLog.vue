<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useMessage } from "naive-ui";
import { useDashboardStore } from "@/stores/dashboard";
import { endpoints } from "@/api/endpoints";
import type { DecisionLog } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import SectionCard from "@/components/SectionCard.vue";
import EmptyState from "@/components/EmptyState.vue";

const store = useDashboardStore();
const message = useMessage();

const items = ref<DecisionLog[]>([]);
const projectFilter = ref<string | null>(null);
const loading = ref(false);
const showCreate = ref(false);

const projects = computed(() => {
  const s = new Set(store.tasks.map((t) => t.project));
  return Array.from(s).sort();
});

async function fetchLogs() {
  loading.value = true;
  try {
    items.value = await endpoints.decisionLogs(
      projectFilter.value ?? undefined,
      50
    );
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    loading.value = false;
  }
}

watch(projectFilter, () => fetchLogs());
onMounted(fetchLogs);

const form = ref({
  project: "",
  decision: "",
  context: "",
  reason: "",
  impact: "",
});

async function submit() {
  if (!form.value.project || !form.value.decision) {
    message.error("项目和决策必填");
    return;
  }
  try {
    await endpoints.createDecisionLog({ ...form.value });
    message.success("决策已记录");
    form.value = { project: "", decision: "", context: "", reason: "", impact: "" };
    showCreate.value = false;
    await fetchLogs();
  } catch (err) {
    message.error((err as Error).message);
  }
}

function dayLabel(ts: string): string {
  return ts.slice(0, 10);
}
function timeLabel(ts: string): string {
  return ts.slice(11, 16);
}

const grouped = computed(() => {
  const map = new Map<string, DecisionLog[]>();
  for (const it of items.value) {
    const k = dayLabel(it.created_at);
    if (!map.has(k)) map.set(k, []);
    map.get(k)!.push(it);
  }
  return Array.from(map.entries());
});
</script>

<template>
  <PageHeader
    title="决策日志"
    :subtitle="`已记录 ${items.length} 条 CEO 决策`"
  >
    <template #extra>
      <n-select
        v-model:value="projectFilter"
        :options="projects.map((p) => ({ label: p, value: p }))"
        placeholder="按项目筛选"
        size="small"
        clearable
        style="width: 200px"
      />
      <n-button size="small" type="primary" @click="showCreate = true">＋ 记录决策</n-button>
    </template>
  </PageHeader>

  <EmptyState
    v-if="!loading && items.length === 0"
    icon="□"
    title="还没有决策记录"
    description="CEO 的关键判断会成为下次 AI 执行的上下文"
  >
    <n-button type="primary" @click="showCreate = true">现在记一条</n-button>
  </EmptyState>

  <div v-else class="timeline">
    <div v-for="[day, group] in grouped" :key="day" class="day-block">
      <div class="day-label">
        <span class="day-text">{{ day }}</span>
        <span class="day-count">{{ group.length }} 条</span>
      </div>
      <div class="day-items">
        <div v-for="item in group" :key="item.id" class="entry">
          <div class="entry-rail">
            <div class="rail-dot" />
            <div class="rail-line" />
          </div>
          <div class="entry-body">
            <div class="entry-head">
              <span class="time">{{ timeLabel(item.created_at) }}</span>
              <n-tag size="tiny" type="info" :bordered="false">{{ item.project }}</n-tag>
            </div>
            <div class="entry-title">{{ item.decision }}</div>
            <div v-if="item.context || item.reason || item.impact" class="entry-detail">
              <div v-if="item.context"><b>背景：</b>{{ item.context }}</div>
              <div v-if="item.reason"><b>理由：</b>{{ item.reason }}</div>
              <div v-if="item.impact"><b>影响：</b>{{ item.impact }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <n-modal
    v-model:show="showCreate"
    preset="card"
    title="记录决策"
    style="max-width: 560px"
  >
    <n-form label-placement="top" :model="form">
      <n-form-item label="项目" required>
        <n-select
          v-model:value="form.project"
          :options="projects.map((p) => ({ label: p, value: p }))"
          placeholder="选择项目"
          filterable
          tag
        />
      </n-form-item>
      <n-form-item label="决策内容" required>
        <n-input v-model:value="form.decision" placeholder="例如：采用方案 B 重构网关" />
      </n-form-item>
      <n-form-item label="背景">
        <n-input
          v-model:value="form.context"
          type="textarea"
          placeholder="为什么会出现这个决策点"
          :autosize="{ minRows: 2, maxRows: 4 }"
        />
      </n-form-item>
      <n-form-item label="理由">
        <n-input
          v-model:value="form.reason"
          type="textarea"
          placeholder="为什么选这个方向，不选其他"
          :autosize="{ minRows: 2, maxRows: 4 }"
        />
      </n-form-item>
      <n-form-item label="影响">
        <n-input
          v-model:value="form.impact"
          type="textarea"
          placeholder="对后续工作的约束 / 范围"
          :autosize="{ minRows: 2, maxRows: 4 }"
        />
      </n-form-item>
    </n-form>
    <template #footer>
      <div style="display:flex; justify-content:flex-end; gap:8px">
        <n-button @click="showCreate = false">取消</n-button>
        <n-button type="primary" @click="submit">保存</n-button>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.timeline {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.day-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.day-label {
  display: flex;
  align-items: center;
  gap: 8px;
  position: sticky;
  top: 0;
  background: #f4f7fb;
  padding: 6px 4px;
  z-index: 1;
}
.day-text {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.day-count {
  font-size: 11px;
  color: #94a3b8;
}
.day-items {
  display: flex;
  flex-direction: column;
}
.entry {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 8px;
}
.entry-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 6px;
}
.rail-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #0b67f0;
  flex-shrink: 0;
}
.rail-line {
  width: 2px;
  flex: 1;
  background: #e2e8f0;
  margin-top: 4px;
  min-height: 16px;
}
.entry-body {
  padding: 0 0 18px 0;
  min-width: 0;
}
.entry-head {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 4px;
}
.time {
  font-size: 11px;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.entry-title {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}
.entry-detail {
  margin-top: 6px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 12px;
  color: #475569;
  line-height: 1.6;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.entry-detail b {
  color: #0f172a;
}
</style>
