<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { endpoints } from "@/api/endpoints";
import type { FeedAction, FeedItem, FeedResponse } from "@/api/types";
import FeedItemView from "@/components/FeedItem.vue";
import { useUiStore } from "@/stores/ui";

const message = useMessage();
const ui = useUiStore();

const feed = ref<FeedResponse | null>(null);
const loading = ref(false);
const executingId = ref("");
const selectedIndex = ref(0);
const expandedId = ref<string | null>(null);
const dismissed = ref(new Set<string>());

const items = computed(() => (feed.value?.items ?? []).filter((item) => !dismissed.value.has(item.id)));
const focusItems = computed(() => (feed.value?.today_focus ?? []).filter((item) => !dismissed.value.has(item.id)));
const selectedItem = computed(() => items.value[selectedIndex.value] ?? null);
const metrics = computed(
  () =>
    feed.value?.metrics ?? {
      projects: 0,
      tasks: 0,
      risks: 0,
      review: 0,
      unread: 0,
    }
);

function priorityDot(priority: string) {
  if (priority === "P0" || priority === "high") return "🔴";
  if (priority === "P1" || priority === "warning") return "🟡";
  return "⚪";
}

function actionIcon(action: FeedAction) {
  if (action.kind === "execute") return "▶";
  if (action.kind === "ignore") return "×";
  if (action.kind === "snooze") return "⏱";
  return "…";
}

function primaryAction(item: FeedItem) {
  return item.actions.find((action) => action.kind === "execute") ?? item.actions[0];
}

async function loadFeed() {
  loading.value = true;
  try {
    feed.value = await endpoints.feed();
    selectedIndex.value = 0;
    expandedId.value = null;
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    loading.value = false;
  }
}

function toggleItem(id: string) {
  expandedId.value = expandedId.value === id ? null : id;
  selectItem(id);
}

function selectItem(id: string) {
  const index = items.value.findIndex((item) => item.id === id);
  if (index >= 0) selectedIndex.value = index;
}

function focusSelected() {
  nextTick(() => {
    const target = document.querySelector<HTMLElement>(`[data-feed-index="${selectedIndex.value}"] .feed-item`);
    target?.focus();
  });
}

function navigate(delta: number) {
  if (!items.value.length) return;
  selectedIndex.value = Math.min(Math.max(selectedIndex.value + delta, 0), items.value.length - 1);
  focusSelected();
}

async function handleAction(item: FeedItem, action: FeedAction) {
  if (action.kind === "ignore") {
    dismissed.value = new Set([...dismissed.value, item.id]);
    message.info("已忽略该条信息。");
    if (selectedIndex.value >= items.value.length) selectedIndex.value = Math.max(0, items.value.length - 1);
    return;
  }
  if (action.kind === "snooze") {
    message.info("已推迟，下一次刷新仍会保留原始信息。");
    return;
  }

  const taskId = item.metadata?.task_id;
  if (typeof taskId === "number") {
    ui.openTask(taskId);
    return;
  }

  const intent = action.intent || item.ai_suggestion.action || item.summary;
  executingId.value = `${item.id}:${action.id}`;
  try {
    const result = await endpoints.commanderExecute({ intent, context: item.details });
    message.success(`已派发给 ${result.tool}，任务 #${result.task_id}`);
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    executingId.value = "";
  }
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

function onKeydown(event: KeyboardEvent) {
  if (isTypingTarget(event.target)) return;
  if (event.key === "j") {
    event.preventDefault();
    navigate(1);
  } else if (event.key === "k") {
    event.preventDefault();
    navigate(-1);
  } else if (event.key === "Enter" && selectedItem.value) {
    event.preventDefault();
    toggleItem(selectedItem.value.id);
  } else if (event.key === "e" && selectedItem.value) {
    event.preventDefault();
    const action = selectedItem.value.actions.find((candidate) => candidate.kind === "execute");
    if (action) handleAction(selectedItem.value, action);
  } else if (event.key === "i" && selectedItem.value) {
    event.preventDefault();
    const action = selectedItem.value.actions.find((candidate) => candidate.kind === "ignore");
    if (action) handleAction(selectedItem.value, action);
  }
}

onMounted(() => {
  window.addEventListener("keydown", onKeydown);
  loadFeed();
});

onUnmounted(() => {
  window.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <div class="cockpit-feed">
    <header class="feed-header">
      <button class="command-input" type="button" @click="ui.openCommandPalette()">
        <span>🔍 搜索</span>
      </button>
      <n-button secondary title="快速操作" @click="ui.openCreateTask()">
        <template #icon>⚡</template>
      </n-button>
    </header>

    <section class="focus-section">
      <div class="section-head">
        <div>
          <h1>今日焦点</h1>
        </div>
        <n-button size="small" :loading="loading" title="刷新" @click="loadFeed">
          <template #icon>↻</template>
        </n-button>
      </div>

      <div v-if="loading && !feed" class="empty"><n-spin size="small" /></div>
      <div v-else-if="focusItems.length" class="focus-list">
        <n-card
          v-for="item in focusItems"
          :key="item.id"
          class="focus-card"
          size="small"
          :bordered="false"
          @click="toggleItem(item.id)"
        >
          <div class="focus-line">
            <span>{{ priorityDot(item.priority) }}</span>
            <b>{{ item.summary }}</b>
            <small>{{ item.ai_suggestion.reason }}</small>
          </div>
          <div v-if="primaryAction(item)" class="focus-actions">
            <n-button
              :key="primaryAction(item)?.id"
              size="tiny"
              secondary
              :loading="executingId === `${item.id}:${primaryAction(item)?.id}`"
              :title="primaryAction(item)?.label"
              @click.stop="primaryAction(item) && handleAction(item, primaryAction(item)!)"
            >
              <template #icon>{{ primaryAction(item) ? actionIcon(primaryAction(item)!) : "▶" }}</template>
            </n-button>
          </div>
        </n-card>
      </div>
      <div v-else class="empty">-</div>
    </section>

    <section class="feed-section">
      <div class="section-head">
        <div>
          <h2>实时信息流</h2>
        </div>
        <n-tag size="small" :bordered="false">{{ items.length }}</n-tag>
      </div>

      <div class="feed-list">
        <div v-for="(item, index) in items" :key="item.id" :data-feed-index="index">
          <FeedItemView
            :item="item"
            :active="index === selectedIndex"
            :expanded="expandedId === item.id"
            @toggle="toggleItem"
            @select="selectItem"
            @navigate="navigate"
            @action="handleAction"
          />
        </div>
      </div>
    </section>

    <footer class="micro-metrics">
      <span>📦 <b>{{ metrics.projects }}</b></span>
      <span>☑ <b>{{ metrics.tasks }}</b></span>
      <span>⚠ <b>{{ metrics.risks }}</b></span>
      <span>审 <b>{{ metrics.review }}</b></span>
      <span>✉ <b>{{ metrics.unread }}</b></span>
    </footer>
  </div>
</template>

<style scoped>
.cockpit-feed {
  --surface: #ffffff;
  --border: #d8e0ec;
  --text: #101827;
  --muted: #5b6678;
  display: grid;
  gap: 12px;
  padding-bottom: 54px;
}

.feed-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.command-input {
  flex: 1;
  min-width: 0;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--muted);
  text-align: left;
  font-size: 14px;
  cursor: pointer;
}

.focus-section,
.feed-section {
  display: grid;
  gap: 12px;
}

.section-head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 12px;
}

.section-head h1,
.section-head h2 {
  margin: 0;
  color: var(--text);
  letter-spacing: 0;
}

.section-head h1 {
  font-size: 22px;
}

.section-head h2 {
  font-size: 18px;
}

.focus-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.focus-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  cursor: pointer;
}

.focus-line {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 6px;
  align-items: center;
}

.focus-line b,
.focus-line small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-line b {
  color: var(--text);
  font-size: 13px;
}

.focus-line small {
  grid-column: 2;
  color: var(--muted);
  font-size: 11px;
}

.focus-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 6px;
}

.feed-list {
  display: grid;
  gap: 8px;
}

.empty {
  padding: 12px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.58);
}

.micro-metrics {
  position: fixed;
  right: 24px;
  bottom: 0;
  left: 96px;
  z-index: 10;
  display: flex;
  justify-content: center;
  gap: 18px;
  padding: 8px 16px;
  border-top: 1px solid var(--border);
  background: rgba(244, 247, 251, 0.94);
  color: var(--muted);
  font-size: 12px;
  backdrop-filter: blur(10px);
}

.micro-metrics b {
  color: var(--text);
}

@media (max-width: 920px) {
  .focus-list {
    grid-template-columns: 1fr;
  }

  .micro-metrics {
    left: 0;
    right: 0;
    gap: 12px;
  }
}

@media (max-width: 620px) {
  .feed-header,
  .section-head {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
