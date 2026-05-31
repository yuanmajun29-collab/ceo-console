import { defineStore } from "pinia";
import { ref } from "vue";

export const useUiStore = defineStore("ui", () => {
  const showCreateTask = ref(false);
  const openTaskId = ref<number | null>(null);
  const showTaskDrawer = ref(false);
  const showCommandPalette = ref(false);

  function openCreateTask() {
    showCreateTask.value = true;
  }
  function openTask(id: number) {
    openTaskId.value = id;
    showTaskDrawer.value = true;
  }
  function closeTask() {
    showTaskDrawer.value = false;
  }
  function openCommandPalette() {
    showCommandPalette.value = true;
  }
  function closeCommandPalette() {
    showCommandPalette.value = false;
  }

  return {
    showCreateTask,
    openTaskId,
    showTaskDrawer,
    showCommandPalette,
    openCreateTask,
    openTask,
    closeTask,
    openCommandPalette,
    closeCommandPalette,
  };
});
