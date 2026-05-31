<script setup lang="ts">
import { computed } from "vue";
import type { Task } from "@/api/types";

const props = defineProps<{ task: Task }>();
const emit = defineEmits<{
  (e: "dispatch", id: number): void;
  (e: "retry", id: number): void;
  (e: "approve", id: number): void;
  (e: "reject", id: number): void;
}>();

const statusTone = computed(() => {
  switch (props.task.status) {
    case "已完成":
      return "success";
    case "待人工审查":
      return "warning";
    case "AI执行中":
      return "info";
    default:
      return "default";
  }
});

const priorityTone = computed(() => {
  switch (props.task.priority) {
    case "P0":
      return "error";
    case "P1":
      return "warning";
    default:
      return "default";
  }
});

const isReview = computed(() => props.task.status === "待人工审查");
const isFailed = computed(() =>
  ["failed", "unsupported"].includes(props.task.execution_state)
);
const isIdle = computed(
  () => props.task.execution_state === "idle" && props.task.status === "待分配"
);
</script>

<template>
  <div class="row">
    <div class="row-main">
      <div class="row-title">
        <n-tag size="small" :type="priorityTone">{{ task.priority }}</n-tag>
        <span class="title-text">{{ task.title }}</span>
      </div>
      <div class="row-meta">
        <span class="project">{{ task.project }}</span>
        <span class="sep">·</span>
        <span>{{ task.assignee_ai }}</span>
        <span v-if="task.due_at" class="sep">·</span>
        <span v-if="task.due_at">截止 {{ task.due_at }}</span>
      </div>
      <div v-if="task.routing_reason" class="routing">{{ task.routing_reason }}</div>
      <div v-if="task.execution_error" class="error">{{ task.execution_error }}</div>
    </div>
    <div class="row-side">
      <n-tag :type="statusTone" size="small">{{ task.status }}</n-tag>
      <div class="actions">
        <n-button
          v-if="isIdle"
          size="tiny"
          type="primary"
          @click="emit('dispatch', task.id)"
        >
          执行
        </n-button>
        <n-button
          v-if="isFailed"
          size="tiny"
          type="warning"
          @click="emit('retry', task.id)"
        >
          重试
        </n-button>
        <n-button
          v-if="isReview"
          size="tiny"
          type="primary"
          @click="emit('approve', task.id)"
        >
          通过
        </n-button>
        <n-button
          v-if="isReview"
          size="tiny"
          type="error"
          ghost
          @click="emit('reject', task.id)"
        >
          驳回
        </n-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  padding: 12px 14px;
  border: 1px solid #edf1f6;
  border-radius: 8px;
  background: #fff;
}
.row + .row {
  margin-top: 8px;
}
.row-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.row-title {
  display: flex;
  gap: 8px;
  align-items: center;
}
.title-text {
  font-weight: 600;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row-meta {
  font-size: 12px;
  color: #64748b;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.row-meta .project {
  color: #0b67f0;
  font-weight: 600;
}
.row-meta .sep {
  color: #cbd5e1;
}
.routing {
  font-size: 12px;
  color: #475569;
  background: #f8fafc;
  padding: 6px 8px;
  border-radius: 6px;
  border-left: 3px solid #0b67f0;
}
.error {
  font-size: 12px;
  color: #b91c1c;
  background: #fef2f2;
  padding: 6px 8px;
  border-radius: 6px;
}
.row-side {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-end;
}
.actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
</style>
