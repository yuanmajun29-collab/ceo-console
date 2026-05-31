<script setup lang="ts">
defineProps<{ title?: string; description?: string; icon?: string }>();
</script>

<template>
  <div class="empty">
    <div class="icon">{{ icon ?? "◌" }}</div>
    <div class="title">{{ title ?? "空空如也" }}</div>
    <div v-if="description" class="desc">{{ description }}</div>
    <div class="actions"><slot /></div>
  </div>
</template>

<style scoped>
.empty {
  text-align: center;
  padding: 36px 16px;
  border: 1px dashed #e2e8f0;
  border-radius: 10px;
  background: #fafbfc;
  color: #64748b;
}
.icon {
  font-size: 28px;
  margin-bottom: 8px;
  opacity: 0.5;
}
.title {
  font-size: 14px;
  font-weight: 600;
  color: #475569;
}
.desc {
  font-size: 12px;
  margin-top: 4px;
}
.actions {
  margin-top: 14px;
}
</style>
