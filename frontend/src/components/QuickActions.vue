<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useDashboardStore } from "@/stores/dashboard";
import { useUiStore } from "@/stores/ui";

interface Action {
  icon: string;
  title: string;
  description: string;
  badge?: number | null;
  tone: "primary" | "warning" | "danger" | "default";
  onClick: () => void;
}

const router = useRouter();
const store = useDashboardStore();
const ui = useUiStore();

const counts = computed(() => store.summary?.counts ?? { 待分配: 0, AI执行中: 0, 待人工审查: 0, 已完成: 0 });
const failedCount = computed(() => store.summary?.failed_dispatch_count ?? 0);
const overdueCount = computed(() => store.summary?.overdue_count ?? 0);
const runnableTools = computed(() => Object.values(store.tools).filter((t) => t.runnable).length);

const actions = computed<Action[]>(() => [
  {
    icon: "＋",
    title: "新建任务",
    description: "把目标说给 AI",
    tone: "primary",
    onClick: () => ui.openCreateTask(),
  },
  {
    icon: "☑",
    title: "评审待办",
    description: counts.value["待人工审查"] ? "AI 已交付，等你出场" : "无待评审",
    badge: counts.value["待人工审查"] || null,
    tone: counts.value["待人工审查"] ? "warning" : "default",
    onClick: () => router.push("/review"),
  },
  {
    icon: "!",
    title: "处理失败",
    description: failedCount.value ? "调度失败，需要重试或重写" : "无失败任务",
    badge: failedCount.value || null,
    tone: failedCount.value ? "danger" : "default",
    onClick: () => router.push("/review"),
  },
  {
    icon: "☷",
    title: "调度待分配",
    description: counts.value["待分配"] ? "批量启动 AI 执行" : "队列已空",
    badge: counts.value["待分配"] || null,
    tone: counts.value["待分配"] ? "primary" : "default",
    onClick: () => router.push("/tasks"),
  },
  {
    icon: "⏰",
    title: "超时任务",
    description: overdueCount.value ? "需要重排优先级" : "无超时",
    badge: overdueCount.value || null,
    tone: overdueCount.value ? "warning" : "default",
    onClick: () => router.push("/tasks"),
  },
  {
    icon: "◉",
    title: "工具体检",
    description: `${runnableTools.value} 个工具可调度`,
    tone: "default",
    onClick: () => router.push("/tools"),
  },
  {
    icon: "□",
    title: "记录决策",
    description: "把关键判断留给下次 AI",
    tone: "default",
    onClick: () => router.push("/decisions"),
  },
  {
    icon: "▣",
    title: "看趋势",
    description: "14 天完成 / 失败曲线",
    tone: "default",
    onClick: () => router.push("/analytics"),
  },
]);
</script>

<template>
  <div class="quick-actions">
    <button
      v-for="(a, i) in actions"
      :key="i"
      :class="['action', 'tone-' + a.tone]"
      @click="a.onClick"
    >
      <div class="action-icon">{{ a.icon }}</div>
      <div class="action-body">
        <div class="action-title">
          {{ a.title }}
          <span v-if="a.badge" class="badge">{{ a.badge }}</span>
        </div>
        <div class="action-desc">{{ a.description }}</div>
      </div>
    </button>
  </div>
</template>

<style scoped>
.quick-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}
.action {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid #e5e7eb;
  cursor: pointer;
  text-align: left;
  font: inherit;
  transition: transform 0.12s, border-color 0.12s, box-shadow 0.12s;
  align-items: center;
}
.action:hover {
  border-color: #0b67f0;
  box-shadow: 0 6px 18px rgba(11, 103, 240, 0.1);
  transform: translateY(-1px);
}
.action:active {
  transform: translateY(0);
}
.action-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 16px;
  flex-shrink: 0;
  background: #eef6ff;
  color: #0b67f0;
  font-weight: 700;
}
.action-body {
  min-width: 0;
  flex: 1;
}
.action-title {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 6px;
}
.action-desc {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.badge {
  background: #ef233c;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 999px;
  min-width: 18px;
  text-align: center;
}
.tone-primary .action-icon {
  background: #dbeafe;
  color: #1d4ed8;
}
.tone-warning .action-icon {
  background: #fef3c7;
  color: #b45309;
}
.tone-warning {
  border-color: #fde68a;
}
.tone-danger .action-icon {
  background: #fee2e2;
  color: #b91c1c;
}
.tone-danger {
  border-color: #fecaca;
}
.tone-default .action-icon {
  background: #f1f5f9;
  color: #475569;
}
</style>
