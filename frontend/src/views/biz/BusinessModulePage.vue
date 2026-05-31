<script setup lang="ts">
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useDashboardStore } from "@/stores/dashboard";
import { useUiStore } from "@/stores/ui";
import { endpoints } from "@/api/endpoints";
import KpiCard from "@/components/KpiCard.vue";
import SectionCard from "@/components/SectionCard.vue";
import DecisionQueueList from "@/components/DecisionQueueList.vue";
import TaskRow from "@/components/TaskRow.vue";
import { useMessage } from "naive-ui";

type ModuleKey = "project" | "customer" | "finance" | "marketing";

const props = defineProps<{
  moduleKey: ModuleKey;
  kpiExtras?: Array<{ label: string; value: string | number; hint?: string; tone?: "blue" | "green" | "orange" | "red" | "muted" }>;
}>();

const store = useDashboardStore();
const ui = useUiStore();
const { tasks } = storeToRefs(store);
const message = useMessage();

const module = computed(() => store.moduleByKey.get(props.moduleKey));
const moduleTasks = computed(() => store.tasksOfModule(props.moduleKey));

const decisionQueue = computed(() => {
  const queue = store.operatingSystem?.decision_queue ?? [];
  const taskTypes = new Set(module.value?.task_types ?? []);
  return queue.filter((q) => taskTypes.has(q.task.task_type));
});

const stats = computed(() => module.value?.stats ?? { total: 0, active: 0, review: 0, failed: 0 });
const route = computed(() => module.value?.route);

const filter = ref<"all" | "active" | "review" | "failed">("active");
const filteredTasks = computed(() => {
  const all = moduleTasks.value;
  switch (filter.value) {
    case "active":
      return all.filter((t) => t.status !== "已完成");
    case "review":
      return all.filter((t) => t.status === "待人工审查");
    case "failed":
      return all.filter((t) => ["failed", "unsupported"].includes(t.execution_state));
    default:
      return all;
  }
});

const creating = ref(false);
async function createCruiseTask() {
  if (!module.value) return;
  creating.value = true;
  try {
    const template = module.value.task_template;
    await endpoints.createTask({
      title: template.title,
      project: tasks.value[0]?.project ?? module.value.toolchain[0] ?? "default",
      assignee_ai: "Other",
      task_type: module.value.default_task_type,
      priority: template.priority,
      ai_instruction: template.instruction,
      expected_output: template.expected_output,
      auto_route: true,
    });
    message.success("巡航任务已创建");
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    creating.value = false;
  }
}

async function dispatchTask(id: number) {
  try {
    await endpoints.dispatchTask(id);
    message.success("已发起调度");
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function retryTask(id: number) {
  try {
    await endpoints.retryTask(id);
    message.success("已重新调度");
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function approveTask(id: number) {
  try {
    await endpoints.reviewTask(id, "approve");
    message.success("已通过");
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}
async function rejectTask(id: number) {
  try {
    await endpoints.reviewTask(id, "reject", "驾驶舱驳回");
    message.warning("已驳回，任务回到待分配");
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}
</script>

<template>
  <div v-if="!module" class="loading">{{ store.loading ? "加载中..." : "未识别的业务板块" }}</div>
  <div v-else class="page">
    <header class="page-head">
      <div>
        <h1>{{ module.name }}</h1>
        <p class="tagline">{{ module.tagline }}</p>
      </div>
      <n-button type="primary" :loading="creating" @click="createCruiseTask">
        创建巡航任务
      </n-button>
    </header>

    <div class="kpi-strip">
      <KpiCard label="本域任务总数" :value="stats.total" tone="blue" :hint="`活跃 ${stats.active}`" />
      <KpiCard label="待人工审查" :value="stats.review" tone="orange" hint="CEO 验收" />
      <KpiCard label="调度失败" :value="stats.failed" tone="red" hint="需要介入" />
      <KpiCard label="主执行工具" :value="route?.primary_tool ?? '-'" tone="muted" :hint="route?.fallback_applied ? '已回退' : '可调度'" />
      <template v-for="(extra, i) in kpiExtras ?? []" :key="i">
        <KpiCard v-bind="extra" />
      </template>
    </div>

    <slot name="pre-content" />

    <div class="grid">
      <div class="col-main">
        <SectionCard
          title="待 CEO 决策"
          :subtitle="`本域内 ${decisionQueue.length} 项等待你出场`"
        >
          <DecisionQueueList :items="decisionQueue" @open="(id) => ui.openTask(id)" />
        </SectionCard>

        <SectionCard title="本域任务" :subtitle="`共 ${moduleTasks.length} 个任务`">
          <template #extra>
            <n-radio-group v-model:value="filter" size="small">
              <n-radio-button value="active">活跃</n-radio-button>
              <n-radio-button value="review">待审查</n-radio-button>
              <n-radio-button value="failed">失败</n-radio-button>
              <n-radio-button value="all">全部</n-radio-button>
            </n-radio-group>
          </template>
          <div v-if="filteredTasks.length === 0" class="empty">
            空。点右上「创建巡航任务」让平台开始工作。
          </div>
          <TaskRow
            v-for="task in filteredTasks"
            :key="task.id"
            :task="task"
            @dispatch="dispatchTask"
            @retry="retryTask"
            @approve="approveTask"
            @reject="rejectTask"
          />
        </SectionCard>
      </div>

      <div class="col-side">
        <SectionCard title="工具链路" subtitle="Token 优先 + 可用性回退">
          <div class="toolchain">
            <n-tag v-for="t in module.toolchain" :key="t" :bordered="false" size="small">
              {{ t }}
            </n-tag>
          </div>
          <div v-if="route" class="route">
            <div class="route-line">
              <span>主：</span><b>{{ route.primary_tool }}</b>
            </div>
            <div class="route-line">
              <span>链：</span><span>{{ route.execution_chain.join(" → ") || "—" }}</span>
            </div>
            <div class="route-line">
              <span>推荐：</span><span>{{ route.recommended_tool }}</span>
            </div>
            <p class="reason">{{ route.reason }}</p>
            <div v-if="route.skipped_tools.length" class="skipped">
              <div class="skipped-title">已跳过</div>
              <div v-for="s in route.skipped_tools" :key="s.tool">
                <b>{{ s.tool }}</b>：{{ s.reason }}
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="CEO 出场动作">
          <ul class="actions">
            <li v-for="a in module.ceo_actions" :key="a">{{ a }}</li>
          </ul>
        </SectionCard>

        <SectionCard title="巡航任务模板" subtitle="点右上一键创建">
          <div class="template">
            <div><b>{{ module.task_template.title }}</b></div>
            <p class="instr">{{ module.task_template.instruction }}</p>
            <div class="expected">
              <span>预期产物</span>
              <p>{{ module.task_template.expected_output }}</p>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.loading {
  padding: 40px;
  text-align: center;
  color: #94a3b8;
}
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.page-head h1 {
  font-size: 22px;
  margin: 0;
}
.tagline {
  color: #64748b;
  margin: 4px 0 0;
  font-size: 13px;
}
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(280px, 1fr);
  gap: 16px;
  align-items: flex-start;
}
.col-main,
.col-side {
  min-width: 0;
}
.empty {
  padding: 28px;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
  border: 1px dashed #e2e8f0;
  border-radius: 8px;
  background: #fafbfc;
}
.toolchain {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.route {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.route-line {
  display: flex;
  gap: 6px;
}
.route-line span {
  color: #64748b;
}
.reason {
  margin: 6px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}
.skipped {
  margin-top: 10px;
  padding: 8px 10px;
  background: #fffbeb;
  border-radius: 6px;
  font-size: 12px;
  color: #92400e;
}
.skipped-title {
  font-weight: 700;
  margin-bottom: 4px;
}
.actions {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #334155;
  font-size: 13px;
}
.template .instr {
  margin: 6px 0 8px;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}
.expected span {
  font-size: 11px;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.expected p {
  margin: 4px 0 0;
  font-size: 12px;
  color: #334155;
}

@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
