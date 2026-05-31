<script setup lang="ts">
import { computed } from "vue";
import { useDashboardStore } from "@/stores/dashboard";
import BusinessModulePage from "./BusinessModulePage.vue";

const store = useDashboardStore();
const kpiExtras = computed(() => {
  const tasks = store.tasksOfModule("marketing");
  const content = tasks.filter((t) => t.task_type === "marketing_content").length;
  const social = tasks.filter((t) => t.task_type === "social_monitor").length;
  return [
    { label: "内容车间任务", value: content, tone: "blue" as const, hint: "DeepSeek 初稿" },
    { label: "社媒监听任务", value: social, tone: "orange" as const, hint: "Gemini 发现" },
  ];
});
</script>

<template>
  <BusinessModulePage module-key="marketing" :kpi-extras="kpiExtras" />
</template>
