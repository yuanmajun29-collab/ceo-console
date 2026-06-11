<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader.vue";
import SectionCard from "@/components/SectionCard.vue";

interface HealthData {
  now: string;
  company_dir_in_use: string;
  company_source: string;
  paths: Record<string, { path: string; accessible: boolean }>;
  pm_script: { path: string; exists: boolean };
  acp: {
    agent: { path: string; exists: boolean; executable: boolean };
    status: { path: string; exists: boolean; executable: boolean };
  };
  launchd: { label: string; loaded: boolean; pid?: string; exit_code?: string };
  runtime_config: { host: string; port: number; dispatch_timeout_seconds: number };
  settings: Record<string, unknown>;
  tools: Record<string, { available: boolean; command: string | null }>;
  obsidian: { knowledge_base_path: string; inbox_path: string; hint: string };
}

interface ToolHealthRow {
  tool: string;
  status: "ok" | "degraded" | "unavailable" | "unknown" | string;
  last_ok_at: string | null;
  last_check_at: string | null;
  last_error: string | null;
  ok_count: number;
  fail_count: number;
}

interface ToolHealthData {
  generated_at: string;
  count: number;
  degraded_count: number;
  tools: ToolHealthRow[];
  risks: Array<Record<string, unknown>>;
}

const message = useMessage();
const data = ref<HealthData | null>(null);
const toolHealth = ref<ToolHealthData | null>(null);
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    const [healthData, toolHealthData] = await Promise.all([
      api.get<HealthData>("/api/health"),
      api.get<ToolHealthData>("/api/tool-health"),
    ]);
    data.value = healthData;
    toolHealth.value = toolHealthData;
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const overall = computed<{ tone: "success" | "warning" | "error"; label: string }>(() => {
  if (!data.value) return { tone: "warning", label: "⚠️" };
  const launchdOk = data.value.launchd.loaded;
  const dirOk = Object.values(data.value.paths).some((p) => p.accessible);
  const pmOk = data.value.pm_script.exists;
  const acpOk = data.value.acp.agent.exists && data.value.acp.agent.executable;
  const score = [launchdOk, dirOk, pmOk, acpOk].filter(Boolean).length;
  if (score === 4) return { tone: "success", label: "✅" };
  if (score >= 2) return { tone: "warning", label: "⚠️" };
  return { tone: "error", label: "❌" };
});

function toolStatusType(status: string) {
  if (status === "ok") return "success";
  if (status === "degraded") return "warning";
  if (status === "unavailable") return "error";
  return "default";
}

function statusIcon(ok: boolean) {
  return ok ? "✅" : "❌";
}

function execIcon(exists: boolean, executable?: boolean) {
  if (!exists) return "❌";
  return executable === false ? "⚠️" : "✅";
}

function toolStatusLabel(status: string) {
  if (status === "ok") return "✅";
  if (status === "degraded") return "⚠️";
  if (status === "unavailable") return "❌";
  return "？";
}
</script>

<template>
  <PageHeader
    title="健康"
    :subtitle="data ? data.now : ''"
  >
    <template #extra>
      <n-tag :type="overall.tone" :bordered="false">{{ overall.label }}</n-tag>
      <n-button size="small" type="primary" :loading="loading" title="重新检测" @click="load">
        <template #icon>↻</template>
      </n-button>
    </template>
  </PageHeader>

  <template v-if="data">
    <SectionCard title="运行">
      <div class="grid">
        <div class="stat">
          <span>host</span>
          <b>{{ data.runtime_config.host }}</b>
        </div>
        <div class="stat">
          <span>port</span>
          <b>{{ data.runtime_config.port }}</b>
        </div>
        <div class="stat">
          <span>dispatch_timeout</span>
          <b>{{ data.runtime_config.dispatch_timeout_seconds }}s</b>
        </div>
        <div class="stat">
          <span>📁</span>
          <b>{{ data.company_dir_in_use }}</b>
          <code>{{ data.company_source }}</code>
        </div>
      </div>
    </SectionCard>

    <SectionCard title="目录">
      <div class="grid">
        <div v-for="(p, key) in data.paths" :key="key" class="stat">
          <span>{{ key }}</span>
          <b :class="p.accessible ? 'ok' : 'fail'">{{ statusIcon(p.accessible) }}</b>
          <code>{{ p.path }}</code>
        </div>
      </div>
    </SectionCard>

    <SectionCard title="Obsidian">
      <div class="grid">
        <div class="stat">
          <span>📓</span>
          <b>{{ data.obsidian.knowledge_base_path }}</b>
          <code>knowledge-base</code>
        </div>
        <div class="stat">
          <span>→</span>
          <b>{{ data.obsidian.inbox_path }}</b>
          <code>inbox</code>
        </div>
      </div>
    </SectionCard>

    <SectionCard title="脚本">
      <div class="grid">
        <div class="stat">
          <span>🛠 pm</span>
          <b :class="data.pm_script.exists ? 'ok' : 'fail'">{{ statusIcon(data.pm_script.exists) }}</b>
          <code>{{ data.pm_script.path }}</code>
        </div>
        <div class="stat">
          <span>acp-agent</span>
          <b :class="data.acp.agent.exists ? 'ok' : 'fail'">
            {{ execIcon(data.acp.agent.exists, data.acp.agent.executable) }}
          </b>
          <code>{{ data.acp.agent.path }}</code>
        </div>
        <div class="stat">
          <span>acp-all-status</span>
          <b :class="data.acp.status.exists ? 'ok' : 'fail'">
            {{ execIcon(data.acp.status.exists, data.acp.status.executable) }}
          </b>
          <code>{{ data.acp.status.path }}</code>
        </div>
        <div class="stat">
          <span>launchd</span>
          <b :class="data.launchd.loaded ? 'ok' : 'fail'">
            {{ data.launchd.loaded ? `✅ ${data.launchd.pid ?? "-"}` : "❌" }}
          </b>
          <code>{{ data.launchd.label }}</code>
        </div>
      </div>
    </SectionCard>

    <SectionCard title="命令">
      <table class="report-table">
        <thead>
          <tr>
            <th>工具</th>
            <th>态</th>
            <th>路径</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(t, name) in data.tools" :key="name">
            <td><b>{{ name }}</b></td>
            <td>
              <n-tag size="small" :type="t.available ? 'success' : 'default'" :bordered="false">
                {{ statusIcon(t.available) }}
              </n-tag>
            </td>
            <td><code>{{ t.command ?? "-" }}</code></td>
          </tr>
        </tbody>
      </table>
    </SectionCard>

    <SectionCard
      title="工具"
      :subtitle="toolHealth ? `${toolHealth.count} · ${toolHealth.degraded_count}` : ''"
    >
      <div v-if="!toolHealth" class="empty"><n-spin size="small" /></div>
      <table v-else class="report-table">
        <thead>
          <tr>
            <th>工具</th>
            <th>态</th>
            <th>OK</th>
            <th>Fail</th>
            <th>Err</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="tool in toolHealth.tools" :key="tool.tool">
            <td><b>{{ tool.tool }}</b></td>
            <td>
              <n-tag size="small" :type="toolStatusType(tool.status)" :bordered="false">
                {{ toolStatusLabel(tool.status) }}
              </n-tag>
            </td>
            <td><code>{{ tool.last_ok_at ?? "-" }}</code></td>
            <td>
              <b :class="tool.fail_count > 0 ? 'fail' : 'ok'">{{ tool.fail_count }}</b>
            </td>
            <td><code>{{ tool.last_error ?? "-" }}</code></td>
          </tr>
        </tbody>
      </table>
    </SectionCard>

    <SectionCard title="设置">
      <pre class="settings-json">{{ JSON.stringify(data.settings, null, 2) }}</pre>
    </SectionCard>
  </template>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 8px;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px 10px;
  background: #f8fafc;
  border-radius: 8px;
}
.stat span {
  font-size: 11px;
  color: #64748b;
}
.stat b {
  font-size: 14px;
  color: #0f172a;
}
.stat b.ok {
  color: #16a34a;
}
.stat b.fail {
  color: #dc2626;
}
.stat code {
  font-size: 10px;
  color: #475569;
  word-break: break-all;
}
.report-table {
  width: 100%;
  font-size: 12px;
  border-collapse: collapse;
}
.report-table th {
  text-align: left;
  padding: 5px 8px;
  font-weight: 600;
  color: #475569;
  background: #f8fafc;
}
.report-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #f1f5f9;
}
.report-table code {
  font-size: 11px;
  color: #475569;
  word-break: break-all;
}
.empty {
  padding: 16px 0;
  color: #64748b;
  font-size: 13px;
}
.settings-json {
  margin: 0;
  font-size: 11px;
  background: #0f172a;
  color: #cbd5e1;
  padding: 12px;
  border-radius: 6px;
  white-space: pre-wrap;
  line-height: 1.6;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
</style>
