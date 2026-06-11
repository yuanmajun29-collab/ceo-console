<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { useDashboardStore } from "@/stores/dashboard";
import { api } from "@/api/client";
import type { ToolsStatus } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import SectionCard from "@/components/SectionCard.vue";
import MetricBar from "@/components/MetricBar.vue";

interface AcpSummary {
  ok: boolean;
  company_dir: string;
  scripts: {
    agent: { exists: boolean; executable: boolean; path: string };
    status: { exists: boolean; executable: boolean; path: string };
  };
  discovery: {
    refreshed: boolean;
    skipped: boolean;
    last_checked_at: string | null;
    added_tools: string[];
    removed_tools: string[];
    stderr: string;
  };
  tools: Record<
    string,
    {
      name: string;
      target: string;
      configured: boolean;
      builtin: boolean;
      source: string;
    }
  >;
}

const store = useDashboardStore();
const message = useMessage();
const acpData = ref<AcpSummary | null>(null);
const refreshing = ref(false);
const launchingTool = ref<string | null>(null);

async function loadAcp() {
  try {
    acpData.value = await api.get<AcpSummary>("/api/acp/summary");
  } catch (err) {
    message.error((err as Error).message);
  }
}

async function refreshAll() {
  refreshing.value = true;
  try {
    await api.post<{ ok: boolean }>("/api/settings/refresh-tools", {});
    await Promise.all([loadAcp(), store.loadAll()]);
    message.success("已刷新");
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    refreshing.value = false;
  }
}

async function launchTool(name: string) {
  launchingTool.value = name;
  try {
    const resp = await api.post<{ ok: boolean; message?: string; error?: string }>(
      "/api/tools/launch",
      { tool: name }
    );
    message.success(resp.message ?? `启动 ${name}...`);
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    launchingTool.value = null;
  }
}

onMounted(() => {
  loadAcp();
});

const tools = computed<[string, ToolsStatus[string]][]>(() =>
  Object.entries(store.tools)
);
const runnableCount = computed(() => tools.value.filter(([, t]) => t.runnable).length);
const acpConfigured = computed(
  () => Object.values(acpData.value?.tools ?? {}).filter((t) => t.configured).length
);
const acpTotal = computed(() => Object.values(acpData.value?.tools ?? {}).length);

function statusTone(t: ToolsStatus[string]): "success" | "warning" | "error" | "default" {
  if (t.runnable) return "success";
  if (t.available) return "warning";
  return "error";
}
function statusLabel(t: ToolsStatus[string]): string {
  if (t.runnable) return "可调度";
  if (t.available) return "已发现但不可后台";
  return "未配置";
}
</script>

<template>
  <PageHeader
    title="AI 工具与 ACP"
    :subtitle="`${runnableCount}/${tools.length} 可调度 · ACP 配置 ${acpConfigured}/${acpTotal}`"
  >
    <template #extra>
      <n-button size="small" :loading="refreshing" type="primary" @click="refreshAll">
        重新体检
      </n-button>
    </template>
  </PageHeader>

  <SectionCard
    title="工具调度面板"
    subtitle="Token 优先 + 可用性预检 + ACP 注入"
  >
    <div class="grid">
      <div v-for="[name, t] in tools" :key="name" class="card">
        <header class="card-head">
          <div class="card-title-row">
            <div class="card-name">{{ name }}</div>
            <n-tag
              size="small"
              :type="statusTone(t)"
              :bordered="false"
            >
              {{ statusLabel(t) }}
            </n-tag>
          </div>
          <div class="card-meta">
            <span v-if="t.acp_target">ACP target · {{ t.acp_target }}</span>
            <span v-else class="muted">无 ACP target</span>
            <span class="sep">·</span>
            <span>{{ t.dynamic_acp ? "动态发现" : "内置" }}</span>
          </div>
        </header>

        <div class="quota">
          <MetricBar
            v-if="t.quota?.percent !== null && t.quota?.percent !== undefined"
            :value="t.quota.percent ?? 0"
            :max="100"
            :tone="(t.quota.percent ?? 100) > 30 ? 'green' : 'orange'"
            :label="`额度 · ${t.quota.label}`"
          />
          <div v-else class="quota-label">额度 · {{ t.quota?.label ?? "未接入" }}</div>
        </div>

        <div class="diag">
          <div v-if="t.command" class="diag-line">
            <span>命令</span>
            <code>{{ t.command }}</code>
          </div>
          <div v-if="t.candidates?.length" class="diag-line">
            <span>候选</span>
            <code>{{ t.candidates.join(", ") }}</code>
          </div>
          <div v-if="t.reason" class="diag-reason">{{ t.reason }}</div>
        </div>

        <footer class="card-foot">
          <div class="card-actions">
            <n-button
              size="tiny"
              secondary
              :loading="launchingTool === name"
              @click="launchTool(name)"
            >
              启动
            </n-button>
            <a
              v-if="t.quota?.recharge_url"
              :href="t.quota.recharge_url"
              target="_blank"
              class="link"
              rel="noreferrer noopener"
            >
              充值/账单 ↗
            </a>
          </div>
          <span class="source-tag">来源 · {{ t.source }}</span>
        </footer>
      </div>
    </div>
  </SectionCard>

  <SectionCard title="ACP 互通诊断" :subtitle="acpData?.company_dir">
    <template v-if="acpData">
      <div class="acp-grid">
        <div class="acp-stat">
          <span>acp-agent 脚本</span>
          <b :class="acpData.scripts.agent.exists ? 'ok' : 'fail'">
            {{ acpData.scripts.agent.exists ? "存在" : "缺失" }}
            {{ acpData.scripts.agent.executable ? "（可执行）" : "" }}
          </b>
          <code>{{ acpData.scripts.agent.path }}</code>
        </div>
        <div class="acp-stat">
          <span>acp-all-status 脚本</span>
          <b :class="acpData.scripts.status.exists ? 'ok' : 'fail'">
            {{ acpData.scripts.status.exists ? "存在" : "缺失" }}
            {{ acpData.scripts.status.executable ? "（可执行）" : "" }}
          </b>
          <code>{{ acpData.scripts.status.path }}</code>
        </div>
        <div class="acp-stat">
          <span>最近体检</span>
          <b>{{ acpData.discovery.last_checked_at ?? "-" }}</b>
          <code>
            刷新 · {{ acpData.discovery.refreshed ? "是" : "跳过" }}
          </code>
        </div>
      </div>
      <div v-if="acpData.discovery.stderr" class="acp-stderr">
        <b>stderr：</b>{{ acpData.discovery.stderr }}
      </div>
      <div class="acp-tools">
        <div
          v-for="(t, name) in acpData.tools"
          :key="name"
          class="acp-chip"
          :class="{ configured: t.configured }"
        >
          <b>{{ name }}</b>
          <span>{{ t.target }}</span>
          <small>{{ t.source }}</small>
        </div>
      </div>
    </template>
  </SectionCard>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}
.card {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 14px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.card-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-name {
  font-size: 15px;
  font-weight: 700;
}
.card-meta {
  font-size: 11px;
  color: #64748b;
  display: flex;
  gap: 4px;
  align-items: center;
}
.card-meta .muted {
  color: #94a3b8;
}
.card-meta .sep {
  color: #cbd5e1;
}
.quota-label {
  font-size: 12px;
  color: #475569;
}
.diag {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
}
.diag-line {
  display: flex;
  gap: 6px;
}
.diag-line span {
  color: #94a3b8;
  flex-shrink: 0;
}
.diag-line code {
  background: #f8fafc;
  padding: 1px 6px;
  border-radius: 4px;
  color: #334155;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.diag-reason {
  margin-top: 4px;
  font-size: 11px;
  color: #475569;
  background: #fffbeb;
  padding: 6px 8px;
  border-radius: 4px;
}
.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid #f1f5f9;
  padding-top: 8px;
  gap: 10px;
}
.card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.link {
  font-size: 11px;
  color: #0b67f0;
  text-decoration: none;
}
.link:hover {
  text-decoration: underline;
}
.source-tag {
  font-size: 10px;
  color: #94a3b8;
}
.acp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}
.acp-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  background: #f8fafc;
  border-radius: 6px;
}
.acp-stat span {
  font-size: 11px;
  color: #64748b;
}
.acp-stat b.ok {
  color: #16a34a;
}
.acp-stat b.fail {
  color: #dc2626;
}
.acp-stat code {
  font-size: 10px;
  color: #475569;
  word-break: break-all;
}
.acp-stderr {
  padding: 8px 10px;
  background: #fef2f2;
  border-radius: 6px;
  color: #b91c1c;
  font-size: 12px;
  margin-bottom: 12px;
}
.acp-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.acp-chip {
  display: flex;
  flex-direction: column;
  gap: 1px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 6px 10px;
  background: #fafbfc;
  min-width: 120px;
}
.acp-chip.configured {
  border-color: #86efac;
  background: #f0fdf4;
}
.acp-chip b {
  font-size: 12px;
}
.acp-chip span {
  font-size: 10px;
  color: #475569;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.acp-chip small {
  font-size: 9px;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
</style>
