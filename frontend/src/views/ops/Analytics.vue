<script setup lang="ts">
import { computed } from "vue";
import { useDashboardStore } from "@/stores/dashboard";
import PageHeader from "@/components/PageHeader.vue";
import SectionCard from "@/components/SectionCard.vue";
import KpiCard from "@/components/KpiCard.vue";
import EChart from "@/components/EChart.vue";
import type { EChartsOption } from "echarts";

const store = useDashboardStore();

const TYPE_LABEL: Record<string, string> = {
  market_research: "市场调研",
  architecture: "架构设计",
  fullstack: "全栈研发",
  code_edit: "代码修改",
  testing: "测试验证",
  docs: "文档交付",
  security_review: "安全审查",
  quality_review: "质量审查",
  delivery: "交付打包",
  customer_triage: "客户分诊",
  contract_review: "合同审查",
  bookkeeping: "财务记账",
  finance_report: "财务问诊",
  marketing_content: "营销内容",
  social_monitor: "社媒监听",
};

const overallStats = computed(() => {
  const tasks = store.tasks;
  const total = tasks.length;
  const done = tasks.filter((t) => t.status === "已完成").length;
  const review = tasks.filter((t) => t.status === "待人工审查").length;
  const running = tasks.filter((t) => t.execution_state === "running").length;
  const failed = tasks.filter((t) => ["failed", "unsupported"].includes(t.execution_state)).length;
  return {
    total,
    done,
    doneRate: total ? Math.round((done / total) * 100) : 0,
    review,
    running,
    failed,
    failureRate: total ? Math.round((failed / total) * 100) : 0,
  };
});

const trendOption = computed<EChartsOption>(() => {
  const days = 14;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const dayKeys: string[] = [];
  const dayLabels: string[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    dayKeys.push(key);
    dayLabels.push(`${d.getMonth() + 1}/${d.getDate()}`);
  }

  const completed = new Array(days).fill(0);
  const created = new Array(days).fill(0);
  const failed = new Array(days).fill(0);
  for (const t of store.tasks) {
    const cKey = (t.created_at ?? "").slice(0, 10);
    const cIdx = dayKeys.indexOf(cKey);
    if (cIdx >= 0) created[cIdx] += 1;

    if (t.status === "已完成") {
      const uKey = (t.reviewed_at ?? t.updated_at ?? "").slice(0, 10);
      const uIdx = dayKeys.indexOf(uKey);
      if (uIdx >= 0) completed[uIdx] += 1;
    }
    if (["failed", "unsupported"].includes(t.execution_state)) {
      const fKey = (t.execution_finished_at ?? t.updated_at ?? "").slice(0, 10);
      const fIdx = dayKeys.indexOf(fKey);
      if (fIdx >= 0) failed[fIdx] += 1;
    }
  }

  return {
    grid: { left: 40, right: 16, top: 40, bottom: 30 },
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { fontSize: 12 } },
    xAxis: {
      type: "category",
      data: dayLabels,
      axisLabel: { fontSize: 11, color: "#64748b" },
      axisLine: { lineStyle: { color: "#e2e8f0" } },
    },
    yAxis: {
      type: "value",
      axisLabel: { fontSize: 11, color: "#64748b" },
      splitLine: { lineStyle: { color: "#f1f5f9" } },
    },
    series: [
      {
        name: "新建",
        type: "line",
        smooth: true,
        data: created,
        itemStyle: { color: "#0b67f0" },
        areaStyle: { color: "rgba(11, 103, 240, 0.08)" },
        symbol: "circle",
        symbolSize: 6,
      },
      {
        name: "完成",
        type: "line",
        smooth: true,
        data: completed,
        itemStyle: { color: "#16a34a" },
        areaStyle: { color: "rgba(22, 163, 74, 0.08)" },
        symbol: "circle",
        symbolSize: 6,
      },
      {
        name: "失败",
        type: "line",
        smooth: true,
        data: failed,
        itemStyle: { color: "#dc2626" },
        symbol: "circle",
        symbolSize: 6,
      },
    ],
  };
});

const typeDistributionOption = computed<EChartsOption>(() => {
  const map = new Map<string, number>();
  for (const t of store.tasks) {
    map.set(t.task_type, (map.get(t.task_type) ?? 0) + 1);
  }
  const data = Array.from(map.entries())
    .sort(([, a], [, b]) => b - a)
    .map(([type, count]) => ({ name: TYPE_LABEL[type] ?? type, value: count }));

  return {
    tooltip: { trigger: "item", formatter: "{b}<br/>{c} 个 ({d}%)" },
    legend: {
      orient: "vertical",
      right: 0,
      top: "middle",
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { fontSize: 11, color: "#475569" },
    },
    series: [
      {
        name: "任务类型",
        type: "pie",
        radius: ["46%", "72%"],
        center: ["32%", "50%"],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 4,
          borderColor: "#fff",
          borderWidth: 2,
        },
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 13, fontWeight: 700 },
          scaleSize: 6,
        },
        data,
      },
    ],
    color: [
      "#0b67f0",
      "#16a34a",
      "#f97316",
      "#8b5cf6",
      "#ec4899",
      "#14b8a6",
      "#f59e0b",
      "#06b6d4",
      "#dc2626",
      "#84cc16",
      "#6366f1",
      "#d946ef",
      "#22d3ee",
      "#eab308",
      "#a855f7",
    ],
  };
});

const aiPerformanceOption = computed<EChartsOption>(() => {
  const map = new Map<string, { total: number; done: number; failed: number }>();
  for (const t of store.tasks) {
    const entry = map.get(t.assignee_ai) ?? { total: 0, done: 0, failed: 0 };
    entry.total += 1;
    if (t.status === "已完成") entry.done += 1;
    if (["failed", "unsupported"].includes(t.execution_state)) entry.failed += 1;
    map.set(t.assignee_ai, entry);
  }
  const list = Array.from(map.entries()).sort(([, a], [, b]) => b.total - a.total);
  const names = list.map(([n]) => n);
  const done = list.map(([, s]) => s.done);
  const failed = list.map(([, s]) => s.failed);
  const other = list.map(([, s]) => s.total - s.done - s.failed);

  return {
    grid: { left: 90, right: 16, top: 40, bottom: 20 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { top: 0, textStyle: { fontSize: 12 } },
    xAxis: {
      type: "value",
      axisLabel: { fontSize: 11, color: "#64748b" },
      splitLine: { lineStyle: { color: "#f1f5f9" } },
    },
    yAxis: {
      type: "category",
      data: names,
      axisLabel: { fontSize: 12, color: "#334155" },
      axisLine: { lineStyle: { color: "#e2e8f0" } },
    },
    series: [
      {
        name: "已完成",
        type: "bar",
        stack: "total",
        data: done,
        itemStyle: { color: "#16a34a" },
        emphasis: { focus: "series" },
      },
      {
        name: "进行中/其他",
        type: "bar",
        stack: "total",
        data: other,
        itemStyle: { color: "#94a3b8" },
        emphasis: { focus: "series" },
      },
      {
        name: "失败",
        type: "bar",
        stack: "total",
        data: failed,
        itemStyle: { color: "#dc2626" },
        emphasis: { focus: "series" },
      },
    ],
  };
});

const projectActivityOption = computed<EChartsOption>(() => {
  const map = new Map<string, number>();
  for (const t of store.tasks) {
    map.set(t.project, (map.get(t.project) ?? 0) + 1);
  }
  const list = Array.from(map.entries()).sort(([, a], [, b]) => b - a).slice(0, 10);
  return {
    grid: { left: 100, right: 24, top: 16, bottom: 20 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: {
      type: "value",
      axisLabel: { fontSize: 11, color: "#64748b" },
      splitLine: { lineStyle: { color: "#f1f5f9" } },
    },
    yAxis: {
      type: "category",
      data: list.map(([n]) => n).reverse(),
      axisLabel: { fontSize: 12, color: "#334155" },
      axisLine: { lineStyle: { color: "#e2e8f0" } },
    },
    series: [
      {
        type: "bar",
        data: list.map(([, c]) => c).reverse(),
        itemStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 1,
            y2: 0,
            colorStops: [
              { offset: 0, color: "#60a5fa" },
              { offset: 1, color: "#0b67f0" },
            ],
          },
          borderRadius: [0, 4, 4, 0],
        },
        label: { show: true, position: "right", fontSize: 11, color: "#475569" },
      },
    ],
  };
});
</script>

<template>
  <PageHeader
    title="数据分析"
    subtitle="任务趋势 · 工具效能 · 项目活跃度"
  />

  <div class="kpi-strip">
    <KpiCard label="任务总数" :value="overallStats.total" tone="blue" :hint="`今日 ${store.summary?.date ?? '-'}`" />
    <KpiCard label="完成率" :value="`${overallStats.doneRate}%`" tone="green" :hint="`已完成 ${overallStats.done}`" />
    <KpiCard label="待评审" :value="overallStats.review" tone="orange" />
    <KpiCard label="执行中" :value="overallStats.running" tone="blue" />
    <KpiCard label="失败率" :value="`${overallStats.failureRate}%`" tone="red" :hint="`失败 ${overallStats.failed}`" />
  </div>

  <SectionCard title="任务趋势" subtitle="近 14 天 · 新建 / 完成 / 失败">
    <EChart :option="trendOption" height="280px" />
  </SectionCard>

  <div class="charts-grid">
    <SectionCard title="任务类型分布" subtitle="按 task_type 聚合">
      <EChart :option="typeDistributionOption" height="320px" />
    </SectionCard>
    <SectionCard title="工具执行效能" subtitle="完成 / 其他 / 失败 堆叠">
      <EChart :option="aiPerformanceOption" height="320px" />
    </SectionCard>
  </div>

  <SectionCard title="项目活跃度 Top 10" subtitle="按任务数量倒序">
    <EChart :option="projectActivityOption" height="320px" />
  </SectionCard>
</template>

<style scoped>
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.charts-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
  margin-top: 14px;
}
@media (max-width: 1100px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }
}
</style>
