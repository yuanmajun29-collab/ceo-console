<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>();
</script>

<template>
  <section class="card">
    <header class="card-head">
      <div>
        <div class="card-title">{{ title }}</div>
        <div v-if="subtitle" class="card-subtitle">{{ subtitle }}</div>
      </div>
      <div class="card-extra">
        <slot name="extra" />
      </div>
    </header>
    <div class="card-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.card {
  background: #fff;
  border: 1px solid #dfe6ef;
  border-radius: 10px;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
  overflow: hidden;
}
.card + .card {
  margin-top: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #edf1f6;
  gap: 12px;
}
.card-title {
  font-weight: 800;
  font-size: 14px;
}
.card-subtitle {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}
.card-body {
  padding: 14px 16px;
}
</style>
