<script setup lang="ts">
import { onMounted } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();

onMounted(() => {
  const focus = (route.query.focus as string | undefined) ?? "";
  const target = focus ? `/legacy#${legacyAnchor(focus)}` : "/legacy";
  window.location.replace(target);
});

function legacyAnchor(focus: string): string {
  const map: Record<string, string> = {
    tasks: "taskCenterSection",
    review: "detail",
    decisions: "decisions",
    tools: "toolsSection",
    repos: "repositories",
    analytics: "analytics",
    reports: "reports",
    health: "toolsSection",
    settings: "settings",
  };
  return map[focus] ?? "";
}
</script>

<template>
  <div class="bridge">正在打开经典控制台...</div>
</template>

<style scoped>
.bridge {
  padding: 60px;
  text-align: center;
  color: #94a3b8;
}
</style>
