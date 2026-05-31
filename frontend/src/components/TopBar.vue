<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";
import { useDashboardStore } from "@/stores/dashboard";

defineProps<{ refreshing: boolean }>();
const emit = defineEmits<{
  (e: "refresh"): void;
  (e: "create-task"): void;
  (e: "open-palette"): void;
}>();

const isMac =
  typeof navigator !== "undefined" && /mac/i.test(navigator.platform);
const metaKey = isMac ? "⌘" : "Ctrl";

const route = useRoute();
const store = useDashboardStore();
const clock = ref("");
let timer: number | null = null;

function tick() {
  clock.value = new Date().toLocaleString("zh-CN", { hour12: false });
}

onMounted(() => {
  tick();
  timer = window.setInterval(tick, 1000);
});
onUnmounted(() => {
  if (timer !== null) window.clearInterval(timer);
});

const title = computed(() => (route.meta?.title as string | undefined) ?? "CEO 驾驶舱");

const runningCount = computed(() =>
  store.summary?.running_dispatch_count ?? 0
);
const failedCount = computed(() => store.summary?.failed_dispatch_count ?? 0);
</script>

<template>
  <header class="topbar">
    <div class="title">{{ title }}</div>
    <div class="spacer" />
    <div class="meta">
      <span class="muted">{{ clock }}</span>
      <span class="sep">|</span>
      <span>执行中 <b>{{ runningCount }}</b></span>
      <span class="sep">|</span>
      <span :class="{ alert: failedCount > 0 }">
        失败 <b>{{ failedCount }}</b>
      </span>
    </div>
    <button class="cp-trigger" @click="emit('open-palette')">
      <span class="cp-trigger-icon">⌕</span>
      <span class="cp-trigger-label">搜索 / 跳转…</span>
      <kbd>{{ metaKey }}</kbd><kbd>K</kbd>
    </button>
    <n-button size="small" type="primary" @click="emit('create-task')">
      ＋ 新建任务
    </n-button>
    <n-button
      size="small"
      :loading="refreshing"
      ghost
      @click="emit('refresh')"
    >
      刷新
    </n-button>
  </header>
</template>

<style scoped>
.topbar {
  height: 60px;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid #dfe6ef;
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 20;
  box-shadow: 0 1px 8px rgba(15, 23, 42, 0.04);
}
.title {
  font-size: 17px;
  font-weight: 900;
}
.spacer {
  flex: 1;
}
.meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: #374151;
}
.meta .sep {
  color: #cbd5e1;
}
.meta .muted {
  color: #64748b;
}
.meta .alert {
  color: #e11d48;
  font-weight: 700;
}
.cp-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
  color: #475569;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.cp-trigger:hover {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}
.cp-trigger-icon {
  font-size: 14px;
  opacity: 0.7;
}
.cp-trigger-label {
  margin-right: 4px;
}
.cp-trigger kbd {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 16px;
  padding: 0 4px;
  font-size: 10px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 3px;
  color: #475569;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
</style>
