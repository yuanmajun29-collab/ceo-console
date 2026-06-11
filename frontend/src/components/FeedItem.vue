<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { FeedAction, FeedItem } from "@/api/types";

const props = defineProps<{
  item: FeedItem;
  active?: boolean;
  expanded?: boolean;
}>();

const emit = defineEmits<{
  (e: "toggle", id: string): void;
  (e: "select", id: string): void;
  (e: "navigate", delta: number): void;
  (e: "action", item: FeedItem, action: FeedAction): void;
}>();

const expandedNames = ref<string[]>(props.expanded ? ["details"] : []);

const priorityType = computed(() => {
  if (props.item.priority === "P0" || props.item.priority === "high") return "error";
  if (props.item.priority === "P1" || props.item.priority === "warning") return "warning";
  return "default";
});

const priorityIcon = computed(() => {
  if (props.item.priority === "P0" || props.item.priority === "high") return "🔴";
  if (props.item.priority === "P1" || props.item.priority === "warning") return "🟡";
  return "⚪";
});

const typeLabel = computed(() => {
  const labels: Record<string, string> = {
    risk: "险",
    task: "务",
    git: "码",
    memory: "忆",
    coordinator: "享",
  };
  return labels[props.item.type] ?? props.item.type;
});

const timeLabel = computed(() => {
  const parsed = new Date(props.item.timestamp);
  if (Number.isNaN(parsed.getTime())) return props.item.timestamp;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
});

watch(
  () => props.expanded,
  (expanded) => {
    expandedNames.value = expanded ? ["details"] : [];
  }
);

function runKind(kind: string) {
  const action = props.item.actions.find((candidate) => candidate.kind === kind);
  if (action) emit("action", props.item, action);
}

function actionIcon(action: FeedAction) {
  if (action.kind === "execute") return "▶";
  if (action.kind === "ignore") return "×";
  if (action.kind === "snooze") return "⏱";
  return "…";
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "j") {
    event.preventDefault();
    emit("navigate", 1);
  } else if (event.key === "k") {
    event.preventDefault();
    emit("navigate", -1);
  } else if (event.key === "Enter") {
    event.preventDefault();
    emit("toggle", props.item.id);
  } else if (event.key === "e") {
    event.preventDefault();
    runKind("execute");
  } else if (event.key === "i") {
    event.preventDefault();
    runKind("ignore");
  }
}
</script>

<template>
  <n-card
    class="feed-item"
    :class="{ active }"
    size="small"
    embedded
    :bordered="false"
    tabindex="0"
    @keydown="onKeydown"
    @focus="emit('select', item.id)"
  >
    <n-collapse
      :expanded-names="expandedNames"
      display-directive="show"
      @update:expanded-names="emit('toggle', item.id)"
    >
      <n-collapse-item name="details">
        <template #header>
          <n-thing class="feed-summary">
            <template #avatar>
              <n-tag size="small" :type="priorityType" :bordered="false">{{ priorityIcon }}</n-tag>
            </template>
            <template #header>
              <span class="summary-text">{{ item.summary }}</span>
            </template>
            <template #description>
              <span>{{ timeLabel }}</span>
              <span>{{ typeLabel }}</span>
              <span>{{ item.source }}</span>
            </template>
          </n-thing>
        </template>

        <div class="details-layer">
          <p class="details-text">{{ item.details }}</p>
          <div class="suggestion">
            <n-tag size="small" type="info" :bordered="false">AI</n-tag>
            <span>{{ item.ai_suggestion.action }}</span>
            <small>{{ item.ai_suggestion.reason }}</small>
          </div>
          <div class="actions-layer">
            <n-button
              v-for="action in item.actions"
              :key="action.id"
              size="small"
              secondary
              :title="action.label"
              @click.stop="emit('action', item, action)"
            >
              <template #icon>{{ actionIcon(action) }}</template>
            </n-button>
          </div>
        </div>
      </n-collapse-item>
    </n-collapse>
  </n-card>
</template>

<style scoped>
.feed-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  outline: none;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.feed-item.active,
.feed-item:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

.feed-summary {
  width: 100%;
}

:deep(.n-thing-main__description) {
  display: flex;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
  color: var(--muted);
  font-size: 11px;
  white-space: nowrap;
}

.summary-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  font-size: 14px;
  font-weight: 650;
  line-height: 1.25;
}

.details-layer {
  display: grid;
  gap: 8px;
  padding: 2px 0 2px 42px;
}

.details-text {
  margin: 0;
  max-width: 840px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
}

.suggestion {
  display: grid;
  gap: 3px;
  color: var(--text);
  font-size: 12px;
}

.suggestion small {
  color: var(--muted);
  line-height: 1.45;
}

.actions-layer {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
