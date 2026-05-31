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
}

const message = useMessage();
const data = ref<HealthData | null>(null);
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    data.value = await api.get<HealthData>("/api/health");
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const overall = computed<{ tone: "success" | "warning" | "error"; label: string }>(() => {
  if (!data.value) return { tone: "warning", label: "未知" };
  const launchdOk = data.value.launchd.loaded;
  const dirOk = Object.values(data.value.paths).some((p) => p.accessible);
  const pmOk = data.value.pm_script.exists;
  const acpOk = data.value.acp.agent.exists && data.value.acp.agent.executable;
  const score = [launchdOk, dirOk, pmOk, acpOk].filter(Boolean).length;
  if (score === 4) return { tone: "success", label: "全部正常" };
  if (score >= 2) return { tone: "warning", label: "部分受限" };
  return { tone: "error", label: "需要修复" };
});
</script>

<template>
  <PageHeader
    title="环境与健康"
    :subtitle="data ? `检测于 ${data.now}` : '后台诊断'"
  >
    <template #extra>
      <n-tag :type="overall.tone" :bordered="false">{{ overall.label }}</n-tag>
      <n-button size="small" type="primary" :loading="loading" @click="load">重新检测</n-button>
    </template>
  </PageHeader>

  <template v-if="data">
    <SectionCard title="运行时配置" subtitle="环境变量 / 命令行参数解析后的值">
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
          <span>当前公司目录</span>
          <b>{{ data.company_dir_in_use }}</b>
          <code>来源：{{ data.company_source }}</code>
        </div>
      </div>
    </SectionCard>

    <SectionCard title="目录可达性" subtitle="一人公司项目根目录三级回退">
      <div class="grid">
        <div v-for="(p, key) in data.paths" :key="key" class="stat">
          <span>{{ key }}</span>
          <b :class="p.accessible ? 'ok' : 'fail'">{{ p.accessible ? "可访问" : "不可访问" }}</b>
          <code>{{ p.path }}</code>
        </div>
      </div>
    </SectionCard>

    <SectionCard title="脚本与服务">
      <div class="grid">
        <div class="stat">
          <span>pm 脚本</span>
          <b :class="data.pm_script.exists ? 'ok' : 'fail'">{{ data.pm_script.exists ? "存在" : "缺失" }}</b>
          <code>{{ data.pm_script.path }}</code>
        </div>
        <div class="stat">
          <span>acp-agent</span>
          <b :class="data.acp.agent.exists ? 'ok' : 'fail'">
            {{ data.acp.agent.exists ? (data.acp.agent.executable ? "可执行" : "存在但非可执行") : "缺失" }}
          </b>
          <code>{{ data.acp.agent.path }}</code>
        </div>
        <div class="stat">
          <span>acp-all-status</span>
          <b :class="data.acp.status.exists ? 'ok' : 'fail'">
            {{ data.acp.status.exists ? (data.acp.status.executable ? "可执行" : "存在但非可执行") : "缺失" }}
          </b>
          <code>{{ data.acp.status.path }}</code>
        </div>
        <div class="stat">
          <span>launchd</span>
          <b :class="data.launchd.loaded ? 'ok' : 'fail'">
            {{ data.launchd.loaded ? `已加载（PID ${data.launchd.pid ?? "-"}）` : "未加载" }}
          </b>
          <code>{{ data.launchd.label }}</code>
        </div>
      </div>
    </SectionCard>

    <SectionCard title="工具命令解析" subtitle="resolve_tool_command 探测结果">
      <table class="report-table">
        <thead>
          <tr>
            <th>工具</th>
            <th>可用</th>
            <th>命令路径</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(t, name) in data.tools" :key="name">
            <td><b>{{ name }}</b></td>
            <td>
              <n-tag size="small" :type="t.available ? 'success' : 'default'" :bordered="false">
                {{ t.available ? "可用" : "未发现" }}
              </n-tag>
            </td>
            <td><code>{{ t.command ?? "-" }}</code></td>
          </tr>
        </tbody>
      </table>
    </SectionCard>

    <SectionCard title="当前设置" subtitle="data/settings.json + 默认值">
      <pre class="settings-json">{{ JSON.stringify(data.settings, null, 2) }}</pre>
    </SectionCard>
  </template>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
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
  padding: 6px 8px;
  font-weight: 600;
  color: #475569;
  background: #f8fafc;
}
.report-table td {
  padding: 8px;
  border-bottom: 1px solid #f1f5f9;
}
.report-table code {
  font-size: 11px;
  color: #475569;
  word-break: break-all;
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
