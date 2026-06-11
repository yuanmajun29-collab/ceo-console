<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useMessage } from "naive-ui";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader.vue";
import SectionCard from "@/components/SectionCard.vue";

interface HubMemory {
  memory: string;
  user: string;
  memory_mtime: string;
}

interface HubSkill {
  name: string;
  category: string;
  description: string;
}

interface HubAgent {
  name: string;
  description: string;
}

interface CoordinatorRow {
  key: string;
  value: string;
  setBy: string;
  reason: string;
  time: string;
}

const message = useMessage();
const loading = ref(false);
const activeTab = ref("state");
const autoRefresh = ref(true);
const exporting = ref(false);
const memory = ref<HubMemory>({ memory: "", user: "", memory_mtime: "" });
const skills = ref<HubSkill[]>([]);
const agents = ref<HubAgent[]>([]);
const coordinatorState = ref<Record<string, unknown>>({});
const skillQuery = ref("");
const agentQuery = ref("");
const selectedAgent = ref<HubAgent | null>(null);
const routingMarkdown = ref("");
let refreshTimer: number | undefined;
let eventSource: EventSource | undefined;

const stateColumns = [
  { title: "键", key: "key", width: 160 },
  {
    title: "值",
    key: "value",
    render(row: CoordinatorRow) {
      return h("code", { class: "table-code" }, row.value);
    },
  },
  { title: "人", key: "setBy", width: 100 },
  { title: "因", key: "reason", width: 220 },
  { title: "时", key: "time", width: 150 },
];

function stringifyValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function normalizeStateRow(key: string, raw: unknown): CoordinatorRow {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const data = raw as Record<string, unknown>;
    return {
      key,
      value: stringifyValue(data.value ?? data.current ?? data.new_value ?? raw),
      setBy: stringifyValue(data.tool ?? data.set_by ?? data.source ?? ""),
      reason: stringifyValue(data.reason ?? ""),
      time: stringifyValue(data.time ?? data.updated_at ?? data.timestamp ?? ""),
    };
  }
  return { key, value: stringifyValue(raw), setBy: "", reason: "", time: "" };
}

function startCoordinatorPolling() {
  if (refreshTimer) return;
  refreshTimer = globalThis.setInterval(() => {
    if (autoRefresh.value) {
      loadAll().catch((err) => message.error((err as Error).message));
    }
  }, 10000);
}

function stopPolling() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer);
    refreshTimer = undefined;
  }
}

const stateRows = computed(() =>
  Object.entries(coordinatorState.value).map(([key, value]) => normalizeStateRow(key, value))
);

const memoryPreview = computed(() =>
  [memory.value.user, memory.value.memory].filter(Boolean).join("\n\n").slice(0, 2000)
);

const filteredSkills = computed(() => {
  const q = skillQuery.value.trim().toLowerCase();
  const rows = q
    ? skills.value.filter((s) =>
        `${s.name} ${s.category} ${s.description}`.toLowerCase().includes(q)
      )
    : skills.value;
  return rows.reduce<Record<string, HubSkill[]>>((acc, skill) => {
    const key = skill.category || "uncategorized";
    acc[key] = [...(acc[key] ?? []), skill];
    return acc;
  }, {});
});

const filteredAgents = computed(() => {
  const q = agentQuery.value.trim().toLowerCase();
  if (!q) return agents.value;
  return agents.value.filter((a) => `${a.name} ${a.description}`.toLowerCase().includes(q));
});

const agentModalVisible = computed({
  get: () => selectedAgent.value !== null,
  set: (show: boolean) => {
    if (!show) selectedAgent.value = null;
  },
});

const activeExportTab = computed(() => (activeTab.value === "state" ? "coordinator" : activeTab.value));

const routingRows = computed(() => {
  const rows: Array<Record<string, string>> = [];
  const lines = routingMarkdown.value.split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("|") || !trimmed.endsWith("|")) continue;
    if (/^\|[\s:-]+\|/.test(trimmed)) continue;
    const cells = trimmed
      .slice(1, -1)
      .split("|")
      .map((cell) => cell.trim());
    if (cells.length < 2 || cells.some((cell) => /^-+$/.test(cell))) continue;
    if (rows.length === 0 && cells.some((cell) => /工具|任务|场景|Tool|Task/i.test(cell))) {
      rows.push({ a: cells[0] ?? "", b: cells[1] ?? "", c: cells[2] ?? "", d: cells[3] ?? "", header: "1" });
    } else {
      rows.push({ a: cells[0] ?? "", b: cells[1] ?? "", c: cells[2] ?? "", d: cells[3] ?? "" });
    }
  }
  return rows;
});

async function exportCurrentTab() {
  exporting.value = true;
  try {
    const data = await api.post<{ ok: boolean; path: string }>(`/api/hub/export/${activeExportTab.value}`, {});
    message.success(`已导出到 ${data.path}`);
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    exporting.value = false;
  }
}

watch(autoRefresh, (enabled) => {
  if (enabled) {
    startCoordinatorPolling();
    loadAll();
  } else {
    stopPolling();
  }
});

async function loadCoordinator() {
  const data = await api.get<{ state: Record<string, unknown> }>("/api/hub/coordinator");
  coordinatorState.value = data.state ?? {};
}

async function loadAll() {
  loading.value = true;
  try {
    const [memoryData, skillsData, agentsData, routingData] = await Promise.all([
      api.get<HubMemory>("/api/hub/memory"),
      api.get<{ skills: HubSkill[] }>("/api/hub/skills"),
      api.get<{ agents: HubAgent[] }>("/api/hub/agents"),
      api.get<{ markdown: string }>("/api/hub/cross-tool-routing"),
      loadCoordinator(),
    ]);
    memory.value = memoryData;
    skills.value = skillsData.skills ?? [];
    agents.value = agentsData.agents ?? [];
    routingMarkdown.value = routingData.markdown ?? "";
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  loadAll();
  startCoordinatorPolling();
  if ("EventSource" in window) {
    eventSource = new EventSource("/api/events");
    eventSource.onmessage = (event) => {
      if (!autoRefresh.value) return;
      try {
        const data = JSON.parse(event.data) as { type?: string; path?: string };
        if (data.type === "file_change") {
          loadAll();
        }
      } catch {}
    };
    eventSource.onerror = () => {
      eventSource?.close();
      eventSource = undefined;
      startCoordinatorPolling();
    };
    return;
  }
});

onBeforeUnmount(() => {
  eventSource?.close();
  stopPolling();
});
</script>

<template>
  <PageHeader
    title="知识中心"
    :subtitle="`${skills.length} · ${agents.length} · ${stateRows.length}`"
  >
    <template #extra>
      <n-switch v-model:value="autoRefresh" size="small">
        <template #checked>自</template>
        <template #unchecked>手</template>
      </n-switch>
      <n-button size="small" :loading="exporting" title="导出 MD" @click="exportCurrentTab">
        <template #icon>⇩</template>
      </n-button>
      <n-button size="small" type="primary" :loading="loading" title="刷新" @click="loadAll">
        <template #icon>↻</template>
      </n-button>
    </template>
  </PageHeader>

  <SectionCard title="知识中心">
    <n-tabs v-model:value="activeTab" type="line" animated>
      <n-tab-pane name="state" tab="📊 态">
        <n-data-table
          :columns="stateColumns"
          :data="stateRows"
          :pagination="{ pageSize: 12 }"
          size="small"
        />
      </n-tab-pane>

      <n-tab-pane name="memory" tab="🧠 记">
        <div class="memory-meta">{{ memory.memory_mtime || "-" }}</div>
        <pre class="memory-box">{{ memoryPreview || "-" }}</pre>
      </n-tab-pane>

      <n-tab-pane name="skills" tab="🧰 技">
        <n-input v-model:value="skillQuery" placeholder="搜索" clearable />
        <div class="category-list">
          <section v-for="(items, category) in filteredSkills" :key="category" class="category">
            <header>
              <n-tag size="small" :bordered="false">{{ category }}</n-tag>
              <span>{{ items.length }}</span>
            </header>
            <div class="skill-grid">
              <article v-for="skill in items" :key="`${category}-${skill.name}`" class="skill-card">
                <n-tag size="small" type="info" :bordered="false">{{ skill.category }}</n-tag>
                <h3>{{ skill.name }}</h3>
                <p>{{ skill.description || "-" }}</p>
              </article>
            </div>
          </section>
        </div>
      </n-tab-pane>

      <n-tab-pane name="agents" tab="🎭 人">
        <n-input v-model:value="agentQuery" placeholder="搜索" clearable />
        <div class="agent-grid">
          <button
            v-for="agent in filteredAgents"
            :key="agent.name"
            class="agent-card"
            type="button"
            @click="selectedAgent = agent"
          >
            <b>{{ agent.name }}</b>
            <span>{{ agent.description || "-" }}</span>
          </button>
        </div>
      </n-tab-pane>

      <n-tab-pane name="routing" tab="🗺 路">
        <div v-if="routingRows.length" class="routing-table-wrap">
          <table class="routing-table">
            <tbody>
              <tr v-for="(row, index) in routingRows" :key="index" :class="{ header: row.header }">
                <td>{{ row.a }}</td>
                <td>{{ row.b }}</td>
                <td v-if="row.c">{{ row.c }}</td>
                <td v-if="row.d">{{ row.d }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <pre v-else class="routing-box">{{ routingMarkdown || "-" }}</pre>
      </n-tab-pane>
    </n-tabs>
  </SectionCard>

  <n-modal
    v-model:show="agentModalVisible"
    preset="card"
    :title="selectedAgent?.name"
    style="max-width: 620px"
  >
    <p class="agent-description">{{ selectedAgent?.description || "-" }}</p>
  </n-modal>
</template>

<style scoped>
.memory-meta {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 8px;
}
.memory-box,
.routing-box {
  margin: 0;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f8fafc;
  color: #1f2937;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  max-height: 520px;
  overflow: auto;
}
.category-list {
  display: grid;
  gap: 12px;
  margin-top: 10px;
}
.category header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  color: #64748b;
  font-size: 12px;
}
.skill-grid,
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 8px;
}
.skill-card,
.agent-card {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  padding: 10px;
  min-height: 96px;
}
.skill-card h3 {
  margin: 6px 0 4px;
  font-size: 14px;
}
.skill-card p,
.agent-card span,
.agent-description {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.45;
}
.agent-grid {
  margin-top: 10px;
}
.agent-card {
  text-align: left;
  cursor: pointer;
}
.agent-card:hover {
  border-color: #0b63e5;
  background: #f8fbff;
}
.agent-card b {
  display: block;
  margin-bottom: 4px;
  color: #0f172a;
  font-size: 13px;
}
.routing-table-wrap {
  overflow-x: auto;
}
.routing-table {
  min-width: 680px;
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.routing-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: top;
}
.routing-table tr.header td {
  background: #f8fafc;
  color: #475569;
  font-weight: 700;
}
:deep(.table-code) {
  display: block;
  max-width: 520px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
}
</style>
