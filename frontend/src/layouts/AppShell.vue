<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useDashboardStore } from "@/stores/dashboard";
import { useUiStore } from "@/stores/ui";
import Sidebar from "@/components/Sidebar.vue";
import TopBar from "@/components/TopBar.vue";
import TaskDetailDrawer from "@/components/TaskDetailDrawer.vue";
import CreateTaskModal from "@/components/CreateTaskModal.vue";
import CommandPalette from "@/components/CommandPalette.vue";

const store = useDashboardStore();
const ui = useUiStore();
const { showCreateTask, openTaskId, showTaskDrawer, showCommandPalette } = storeToRefs(ui);
const route = useRoute();
const refreshing = ref(false);
let timer: number | null = null;

async function refresh() {
  refreshing.value = true;
  try {
    await store.loadAll();
  } catch {
    // surfaced via store.lastError
  } finally {
    refreshing.value = false;
  }
}

function onTaskCreated(id: number) {
  ui.openTask(id);
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  return false;
}

function onGlobalKeydown(e: KeyboardEvent) {
  const meta = e.metaKey || e.ctrlKey;

  // Cmd/Ctrl+K → command palette (overrides browser default in Chrome too)
  if (meta && (e.key === "k" || e.key === "K")) {
    e.preventDefault();
    ui.openCommandPalette();
    return;
  }

  // Cmd/Ctrl+N → create task (only if not typing in form)
  if (meta && (e.key === "n" || e.key === "N") && !isTypingTarget(e.target)) {
    e.preventDefault();
    ui.openCreateTask();
    return;
  }

  // Bare "/" or "?" — quick search shortcuts (only outside inputs)
  if (!meta && !isTypingTarget(e.target)) {
    if (e.key === "/") {
      e.preventDefault();
      ui.openCommandPalette();
    }
  }
}

onMounted(async () => {
  window.addEventListener("keydown", onGlobalKeydown);
  await refresh();
  timer = window.setInterval(refresh, 30_000);
});

onUnmounted(() => {
  window.removeEventListener("keydown", onGlobalKeydown);
  if (timer !== null) window.clearInterval(timer);
});
</script>

<template>
  <div class="shell">
    <Sidebar />
    <div class="main">
      <TopBar
        :refreshing="refreshing"
        @refresh="refresh"
        @create-task="ui.openCreateTask()"
        @open-palette="ui.openCommandPalette()"
      />
      <div class="content">
        <router-view :key="route.fullPath" />
      </div>
    </div>

    <TaskDetailDrawer
      :task-id="openTaskId"
      :show="showTaskDrawer"
      @update:show="(v: boolean) => (showTaskDrawer = v)"
      @changed="refresh()"
    />
    <CreateTaskModal
      :show="showCreateTask"
      @update:show="(v: boolean) => (showCreateTask = v)"
      @created="onTaskCreated"
    />
    <CommandPalette
      :show="showCommandPalette"
      @update:show="(v: boolean) => (showCommandPalette = v)"
    />
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  min-height: 100vh;
}
.main {
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.content {
  padding: 20px 24px 40px;
  flex: 1;
  min-width: 0;
}
</style>
