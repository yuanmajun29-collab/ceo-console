import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { endpoints } from "@/api/endpoints";
import type {
  CompanyOperatingSystem,
  DailyBrief,
  DashboardSummary,
  Task,
  ToolsStatus,
} from "@/api/types";

export const useDashboardStore = defineStore("dashboard", () => {
  const summary = ref<DashboardSummary | null>(null);
  const brief = ref<DailyBrief | null>(null);
  const operatingSystem = ref<CompanyOperatingSystem | null>(null);
  const tasks = ref<Task[]>([]);
  const tools = ref<ToolsStatus>({});
  const loading = ref(false);
  const lastError = ref<string | null>(null);
  const lastLoadedAt = ref<string | null>(null);

  async function loadAll() {
    loading.value = true;
    lastError.value = null;
    try {
      const [s, b, os, t, tl] = await Promise.all([
        endpoints.dashboardSummary(),
        endpoints.dailyBrief(),
        endpoints.companyOperatingSystem(),
        endpoints.tasks(),
        endpoints.toolsStatus(),
      ]);
      summary.value = s;
      brief.value = b;
      operatingSystem.value = os;
      tasks.value = t;
      tools.value = tl;
      lastLoadedAt.value = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    } catch (err) {
      lastError.value = (err as Error).message;
      throw err;
    } finally {
      loading.value = false;
    }
  }

  const moduleByKey = computed(() => {
    const map = new Map<string, CompanyOperatingSystem["modules"][number]>();
    for (const m of operatingSystem.value?.modules ?? []) {
      map.set(m.key, m);
    }
    return map;
  });

  const domains = computed(() => operatingSystem.value?.domains ?? []);

  function tasksOfModule(key: "project" | "customer" | "finance" | "marketing"): Task[] {
    const types = new Set(moduleByKey.value.get(key)?.task_types ?? []);
    return tasks.value.filter((t) => types.has(t.task_type));
  }

  function modulesOfDomain(domainKey: string) {
    return (operatingSystem.value?.modules ?? []).filter((m) => m.domain === domainKey);
  }

  return {
    summary,
    brief,
    operatingSystem,
    tasks,
    tools,
    loading,
    lastError,
    lastLoadedAt,
    moduleByKey,
    domains,
    loadAll,
    tasksOfModule,
    modulesOfDomain,
  };
});
