<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { useDashboardStore } from "@/stores/dashboard";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader.vue";
import SectionCard from "@/components/SectionCard.vue";
import KpiCard from "@/components/KpiCard.vue";

interface OperationsReport {
  generated_at: string;
  projects: {
    total: number;
    archived: number;
    governance_avg: number;
    items: Array<{ name: string; governance_score: number; phase: string; checklist_completion: number; adr_count: number }>;
  };
  tasks: {
    total: number;
    counts: Record<string, number>;
    failed: number;
    items: unknown[];
  };
  repositories: {
    total: number;
    git: number;
    dirty: number;
    not_git: number;
  };
  decisions: unknown[];
}

const store = useDashboardStore();
const message = useMessage();
const report = ref<OperationsReport | null>(null);
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    report.value = await api.get<OperationsReport>("/api/reports/operations");
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const summary = computed(() => report.value);

function exportTasksCsv() {
  window.open("/api/tasks/export", "_blank");
}
function openJson(path: string) {
  window.open(path, "_blank");
}
</script>

<template>
  <PageHeader
    title="报表中心"
    :subtitle="report?.generated_at ? `生成于 ${report.generated_at}` : '运营报表'"
  >
    <template #extra>
      <n-button size="small" @click="exportTasksCsv">导出任务 CSV</n-button>
      <n-button size="small" type="primary" :loading="loading" @click="load">刷新</n-button>
    </template>
  </PageHeader>

  <div v-if="summary" class="kpi-strip">
    <KpiCard label="项目总数" :value="summary.projects.total" tone="blue" :hint="`归档 ${summary.projects.archived}`" />
    <KpiCard label="平均治理分" :value="summary.projects.governance_avg" tone="green" hint="0-100" />
    <KpiCard label="任务总数" :value="summary.tasks.total" tone="muted" :hint="`失败 ${summary.tasks.failed}`" />
    <KpiCard label="仓库总数" :value="summary.repositories.total" tone="blue" :hint="`Git ${summary.repositories.git} · 脏 ${summary.repositories.dirty}`" />
    <KpiCard label="决策记录" :value="summary.decisions.length" tone="muted" hint="最近 20 条" />
  </div>

  <SectionCard title="任务状态分布" subtitle="按状态聚合">
    <div class="status-grid">
      <div v-for="(count, status) in summary?.tasks.counts ?? {}" :key="status" class="status-card">
        <span>{{ status }}</span>
        <b>{{ count }}</b>
      </div>
    </div>
  </SectionCard>

  <SectionCard title="项目治理排行" subtitle="按治理分降序">
    <table class="report-table">
      <thead>
        <tr>
          <th>项目</th>
          <th>阶段</th>
          <th>治理分</th>
          <th>清单完成</th>
          <th>ADR</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="p in [...(summary?.projects.items ?? [])].sort((a, b) => b.governance_score - a.governance_score)"
          :key="p.name"
        >
          <td><b>{{ p.name }}</b></td>
          <td>{{ p.phase }}</td>
          <td>
            <span :class="['score', p.governance_score >= 70 ? 'good' : p.governance_score >= 40 ? 'mid' : 'low']">
              {{ p.governance_score }}
            </span>
          </td>
          <td>{{ p.checklist_completion }}%</td>
          <td>{{ p.adr_count }}</td>
        </tr>
      </tbody>
    </table>
  </SectionCard>

  <SectionCard title="导出工具" subtitle="便于跨端协作">
    <div class="export-actions">
      <n-button @click="exportTasksCsv">📤 任务 CSV</n-button>
      <n-button @click="openJson('/api/reports/operations')">📋 运营 JSON</n-button>
      <n-button @click="openJson('/api/daily-brief')">📰 日报 JSON</n-button>
      <n-button @click="openJson('/api/operations/command-center')">🎯 指挥台 JSON</n-button>
    </div>
  </SectionCard>
</template>

<style scoped>
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}
.status-card {
  background: #f8fafc;
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.status-card span {
  font-size: 12px;
  color: #64748b;
}
.status-card b {
  font-size: 22px;
  font-weight: 800;
}
.report-table {
  width: 100%;
  font-size: 13px;
  border-collapse: collapse;
}
.report-table th {
  text-align: left;
  padding: 8px;
  font-weight: 600;
  color: #475569;
  background: #f8fafc;
}
.report-table td {
  padding: 8px;
  border-bottom: 1px solid #f1f5f9;
}
.score {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 12px;
}
.score.good {
  background: #dcfce7;
  color: #166534;
}
.score.mid {
  background: #fef3c7;
  color: #92400e;
}
.score.low {
  background: #fee2e2;
  color: #991b1b;
}
.export-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
