<script setup lang="ts">
import type { DecisionQueueItem } from "@/api/types";

defineProps<{ items: DecisionQueueItem[] }>();
defineEmits<{ (e: "open", id: number): void }>();

function actionLabel(action: string): string {
  switch (action) {
    case "approve_or_reject":
      return "通过 / 驳回";
    case "retry_or_rewrite":
      return "重试 / 重写";
    case "reprioritize":
      return "重排优先级";
    default:
      return action;
  }
}
</script>

<template>
  <div class="queue">
    <div v-if="items.length === 0" class="empty">当前没有待决策项 🎉</div>
    <div
      v-for="item in items"
      :key="item.task.id"
      class="queue-row"
      @click="$emit('open', item.task.id)"
    >
      <n-tag size="small" :type="item.level === 'P0' ? 'error' : 'warning'">
        {{ item.level }}
      </n-tag>
      <div class="queue-body">
        <div class="queue-title">{{ item.task.title }}</div>
        <div class="queue-meta">
          <span>{{ item.task.project }}</span>
          <span class="sep">·</span>
          <span>{{ item.reason }}</span>
        </div>
      </div>
      <div class="queue-action">{{ actionLabel(item.action) }}</div>
    </div>
  </div>
</template>

<style scoped>
.queue {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.queue-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid #edf1f6;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  transition: background 0.15s;
}
.queue-row:hover {
  background: #f1f5fb;
}
.queue-body {
  min-width: 0;
}
.queue-title {
  font-weight: 600;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queue-meta {
  font-size: 12px;
  color: #64748b;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.queue-meta .sep {
  color: #cbd5e1;
}
.queue-action {
  font-size: 12px;
  color: #0b67f0;
  font-weight: 600;
  white-space: nowrap;
}
.empty {
  padding: 18px;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
  border: 1px dashed #e2e8f0;
  border-radius: 8px;
  background: #fafbfc;
}
</style>
