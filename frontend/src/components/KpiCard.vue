<script setup lang="ts">
defineProps<{
  label: string;
  value: string | number;
  hint?: string;
  tone?: "blue" | "green" | "orange" | "red" | "muted";
}>();
</script>

<template>
  <div class="kpi" :class="['tone-' + (tone ?? 'blue')]">
    <div class="kpi-label">{{ label }}</div>
    <div class="kpi-value">{{ value }}</div>
    <div class="kpi-hint">{{ hint ?? "" }}</div>
  </div>
</template>

<style scoped>
.kpi {
  background: #fff;
  border: 1px solid #dfe6ef;
  border-radius: 8px;
  padding: 14px 16px;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.kpi-label {
  color: #64748b;
  font-size: 12px;
}
.kpi-value {
  font-size: 26px;
  font-weight: 900;
  letter-spacing: -0.01em;
  line-height: 1;
}
.kpi-hint {
  font-size: 11px;
  color: #94a3b8;
  min-height: 14px;
}
.tone-blue .kpi-value {
  color: #0b67f0;
}
.tone-green .kpi-value {
  color: #16a34a;
}
.tone-orange .kpi-value {
  color: #f97316;
}
.tone-red .kpi-value {
  color: #e11d48;
}
.tone-muted .kpi-value {
  color: #475569;
}
</style>
