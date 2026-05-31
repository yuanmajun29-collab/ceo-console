<script setup lang="ts">
import { computed } from "vue";
import type { ExecutionState, TaskStatus } from "@/api/types";

const props = defineProps<{
  status?: TaskStatus | string;
  execution?: ExecutionState | string;
}>();

const map = {
  待分配: { tone: "default", label: "待分配" },
  AI执行中: { tone: "info", label: "执行中" },
  待人工审查: { tone: "warning", label: "待评审" },
  已完成: { tone: "success", label: "已完成" },
  idle: { tone: "default", label: "空闲" },
  running: { tone: "info", label: "运行中" },
  succeeded: { tone: "success", label: "成功" },
  failed: { tone: "error", label: "失败" },
  unsupported: { tone: "error", label: "不支持" },
} as const;

const entry = computed(() => {
  const key = (props.execution ?? props.status ?? "") as keyof typeof map;
  return map[key] ?? { tone: "default", label: key || "-" };
});
</script>

<template>
  <n-tag :type="entry.tone as any" size="small" :bordered="false">
    {{ entry.label }}
  </n-tag>
</template>
