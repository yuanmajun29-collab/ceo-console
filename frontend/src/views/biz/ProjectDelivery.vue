<script setup lang="ts">
import { computed } from "vue";
import { useDashboardStore } from "@/stores/dashboard";
import BusinessModulePage from "./BusinessModulePage.vue";

const store = useDashboardStore();
const kpiExtras = computed(() => {
  const tasks = store.tasksOfModule("project");
  const overdue = tasks.filter(
    (t) =>
      t.due_at &&
      t.status !== "已完成" &&
      new Date(t.due_at.replace(" ", "T")) < new Date()
  ).length;
  const projects = new Set(tasks.map((t) => t.project));
  return [
    { label: "覆盖项目数", value: projects.size, tone: "blue" as const, hint: "本域涉及" },
    { label: "本域超时", value: overdue, tone: "red" as const, hint: "已过截止" },
  ];
});
</script>

<template>
  <BusinessModulePage module-key="project" :kpi-extras="kpiExtras" />
</template>
