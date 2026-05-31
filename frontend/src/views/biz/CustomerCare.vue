<script setup lang="ts">
import { computed } from "vue";
import { useDashboardStore } from "@/stores/dashboard";
import BusinessModulePage from "./BusinessModulePage.vue";

const store = useDashboardStore();

const kpiExtras = computed(() => {
  const tasks = store.tasksOfModule("customer");
  const triage = tasks.filter((t) => t.task_type === "customer_triage").length;
  const contract = tasks.filter((t) => t.task_type === "contract_review").length;
  // 销售管道用任务标题/备注里的关键词做轻量识别，等接入真实 CRM 后再替换
  const haystack = (t: { title: string; notes: string | null; ai_instruction: string | null }) =>
    `${t.title} ${t.notes ?? ""} ${t.ai_instruction ?? ""}`.toLowerCase();
  const leads = tasks.filter((t) => /lead|线索|询价|inquiry/i.test(haystack(t))).length;
  const renewals = tasks.filter((t) => /renew|续费|续约/i.test(haystack(t))).length;
  return [
    { label: "客户分诊任务", value: triage, tone: "blue" as const, hint: "情绪/退款/Bug" },
    { label: "合同审查任务", value: contract, tone: "orange" as const, hint: "高风险等待" },
    { label: "销售线索", value: leads, tone: "green" as const, hint: "关键词匹配" },
    { label: "续费提醒", value: renewals, tone: "muted" as const, hint: "关键词匹配" },
  ];
});
</script>

<template>
  <BusinessModulePage module-key="customer" :kpi-extras="kpiExtras" />
</template>
