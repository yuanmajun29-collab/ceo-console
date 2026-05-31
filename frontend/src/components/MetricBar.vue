<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  value: number;
  max?: number;
  tone?: "blue" | "green" | "orange" | "red";
  label?: string;
}>();

const percent = computed(() => {
  const max = props.max ?? 100;
  if (!max) return 0;
  return Math.min(100, Math.max(0, (props.value / max) * 100));
});
</script>

<template>
  <div class="bar-wrap">
    <div v-if="label" class="bar-label">
      <span>{{ label }}</span>
      <b>{{ value }}{{ max ? ` / ${max}` : "" }}</b>
    </div>
    <div class="bar-track">
      <div class="bar-fill" :class="['tone-' + (tone ?? 'blue')]" :style="{ width: percent + '%' }" />
    </div>
  </div>
</template>

<style scoped>
.bar-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.bar-label {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #475569;
}
.bar-label b {
  color: #0f172a;
  font-weight: 700;
}
.bar-track {
  height: 6px;
  border-radius: 999px;
  background: #eef1f5;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s;
}
.tone-blue {
  background: linear-gradient(90deg, #2563eb, #60a5fa);
}
.tone-green {
  background: linear-gradient(90deg, #16a34a, #4ade80);
}
.tone-orange {
  background: linear-gradient(90deg, #f97316, #fbbf24);
}
.tone-red {
  background: linear-gradient(90deg, #dc2626, #f87171);
}
</style>
