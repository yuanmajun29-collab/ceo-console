<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { useRouter } from "vue-router";
import { endpoints } from "@/api/endpoints";
import type { DailyBriefV2, DailyBriefV2Suggestion, RiskAlert } from "@/api/types";
import { useDashboardStore } from "@/stores/dashboard";
import { useUiStore } from "@/stores/ui";
import KpiCard from "@/components/KpiCard.vue";
import SectionCard from "@/components/SectionCard.vue";
import DecisionQueueList from "@/components/DecisionQueueList.vue";
import QuickActions from "@/components/QuickActions.vue";

const store = useDashboardStore();
const ui = useUiStore();
const router = useRouter();
const message = useMessage();
const briefV2 = ref<DailyBriefV2 | null>(null);
const briefLoading = ref(false);
const executingIntent = ref("");
const riskAlerts = ref<RiskAlert[]>([]);
const riskLoading = ref(false);

const counts = computed(() => store.summary?.counts ?? { 待分配: 0, AI执行中: 0, 待人工审查: 0, 已完成: 0 });
const totalTasks = computed(() => store.tasks.length);
const aiRate = computed(() => {
  const total = totalTasks.value;
  return total ? Math.round(((counts.value["已完成"] ?? 0) * 100) / total) : 0;
});
const runnableTools = computed(() => {
  const list = Object.values(store.tools);
  return {
    runnable: list.filter((t) => t.runnable).length,
    total: list.length,
  };
});

const moduleRoutes: Record<string, string> = {
  project: "/biz/project",
  customer: "/biz/customer",
  finance: "/biz/finance",
  marketing: "/biz/marketing",
};

function goModule(key: string) {
  const path = moduleRoutes[key];
  if (path) router.push(path);
}

function openRisk(risk: RiskAlert) {
  if (risk.task_id) {
    ui.openTask(risk.task_id);
    return;
  }
  router.push("/tasks");
}

const decisionQueue = computed(() => store.operatingSystem?.decision_queue ?? []);
const warnings = computed(() => store.brief?.warnings ?? []);
const highRiskCount = computed(() => riskAlerts.value.filter((risk) => risk.level === "high").length);

const principle = computed(
  () =>
    store.operatingSystem?.principle ??
    "CEO 只做三件事：看经营态势、说目标指令、点批准或驳回。"
);

async function loadBriefV2() {
  briefLoading.value = true;
  try {
    briefV2.value = await endpoints.dailyBriefV2();
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    briefLoading.value = false;
  }
}

async function loadRisks() {
  riskLoading.value = true;
  try {
    const data = await endpoints.risks();
    riskAlerts.value = data.risks ?? [];
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    riskLoading.value = false;
  }
}

async function executeSuggestion(suggestion: DailyBriefV2Suggestion) {
  if (suggestion.action?.type === "open_task" && suggestion.action.task_id) {
    ui.openTask(suggestion.action.task_id);
    return;
  }
  const intent = suggestion.intent || suggestion.action?.intent || suggestion.title;
  executingIntent.value = intent;
  try {
    const result = await endpoints.commanderExecute({ intent, context: suggestion.reason });
    message.success(`已派发给 ${result.tool}，任务 #${result.task_id}`);
    router.push("/commander");
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    executingIntent.value = "";
  }
}

onMounted(() => {
  loadBriefV2();
  loadRisks();
});
</script>

<template>
  <div class="home">
    <header class="hero">
      <div>
        <h1>今日驾驶舱</h1>
        <p class="principle">{{ principle }}</p>
      </div>
      <div class="hero-meta">
        <span class="date">{{ store.summary?.date ?? "-" }}</span>
      </div>
    </header>

    <div class="kpi-strip">
      <KpiCard label="活跃项目" :value="store.summary?.active_projects ?? 0" tone="blue" hint="进行中" />
      <KpiCard label="任务总数" :value="totalTasks" tone="muted" :hint="`今日新增按更新时间`" />
      <KpiCard label="AI 完成率" :value="`${aiRate}%`" tone="green" :hint="`已完成 ${counts['已完成']}`" />
      <KpiCard label="执行中" :value="counts['AI执行中']" tone="blue" hint="后台运行" />
      <KpiCard label="待评审" :value="counts['待人工审查']" tone="orange" hint="CEO 出场" />
      <KpiCard label="调度失败" :value="store.summary?.failed_dispatch_count ?? 0" tone="red" hint="需要介入" />
      <KpiCard
        label="可调度工具"
        :value="`${runnableTools.runnable}/${runnableTools.total}`"
        tone="muted"
        hint="ACP + 本地"
      />
    </div>

    <div v-if="warnings.length" class="warnings">
      <div v-for="(w, i) in warnings" :key="i" class="warning">⚠ {{ w }}</div>
    </div>

    <SectionCard
      title="风险预警"
      :subtitle="riskAlerts.length ? `${riskAlerts.length} 项风险 · 高风险 ${highRiskCount} 项` : '项目停滞与任务超期巡检'"
    >
      <template #extra>
        <n-button size="small" :loading="riskLoading" @click="loadRisks">刷新</n-button>
      </template>
      <div v-if="riskLoading && !riskAlerts.length" class="empty">加载中...</div>
      <div v-else-if="riskAlerts.length" class="risk-alerts">
        <article
          v-for="risk in riskAlerts.slice(0, 6)"
          :key="`${risk.type}-${risk.task_id ?? risk.project ?? risk.message}`"
          class="risk-alert"
          :class="{ high: risk.level === 'high' }"
          @click="openRisk(risk)"
        >
          <div>
            <n-tag size="small" :type="risk.level === 'high' ? 'error' : 'warning'" :bordered="false">
              {{ risk.level === "high" ? "高风险" : "预警" }}
            </n-tag>
            <b>{{ risk.message }}</b>
          </div>
          <span v-if="risk.due_at">到期 {{ risk.due_at }}</span>
          <span v-else-if="risk.last_commit_at">最后提交 {{ risk.last_commit_at }}</span>
        </article>
      </div>
      <div v-else class="empty">暂无风险预警。</div>
    </SectionCard>

    <SectionCard
      title="今日简报"
      :subtitle="briefV2 ? `${briefV2.date} · ${briefV2.sections.project_delivery.summary}` : '增强版经营摘要'"
    >
      <div v-if="briefLoading && !briefV2" class="empty">加载中...</div>
      <div v-else-if="briefV2" class="daily-brief">
        <div class="brief-summary">
          <div>
            <span class="summary-label">项目交付</span>
            <b>{{ briefV2.sections.project_delivery.summary }}</b>
          </div>
          <div>
            <span class="summary-label">财务</span>
            <b>{{ briefV2.sections.finance.current_month_net || "-" }}</b>
          </div>
          <div>
            <span class="summary-label">风险</span>
            <b>{{ briefV2.risks.length }} 项</b>
          </div>
          <div>
            <span class="summary-label">共享状态</span>
            <b>{{ briefV2.coordinator.recent.length }} 条</b>
          </div>
        </div>
        <div v-if="briefV2.risks.length" class="risk-list">
          <n-tag
            v-for="risk in briefV2.risks.slice(0, 4)"
            :key="risk.message"
            size="small"
            :type="risk.level === 'high' ? 'error' : 'warning'"
          >
            {{ risk.message }}
          </n-tag>
        </div>
        <div class="suggestions">
          <button
            v-for="suggestion in briefV2.suggestions.slice(0, 4)"
            :key="suggestion.title"
            class="suggestion"
            type="button"
            :disabled="executingIntent === suggestion.intent"
            @click="executeSuggestion(suggestion)"
          >
            <span class="suggestion-priority">{{ suggestion.priority }}</span>
            <span class="suggestion-main">
              <b>{{ suggestion.title }}</b>
              <small>{{ suggestion.reason }}</small>
            </span>
            <span class="suggestion-action">{{ executingIntent === suggestion.intent ? "派发中" : "执行" }}</span>
          </button>
          <div v-if="!briefV2.suggestions.length" class="empty">暂无建议动作。</div>
        </div>
      </div>
    </SectionCard>

    <QuickActions />

    <div class="grid">
      <div class="col-main">
        <SectionCard
          title="待 CEO 决策"
          :subtitle="`${decisionQueue.length} 项等待你出场`"
        >
          <DecisionQueueList :items="decisionQueue" @open="(id) => ui.openTask(id)" />
        </SectionCard>

        <SectionCard
          title="三大经营域全景"
          subtitle="生产与经营 · 营销与销售 · 财务运作"
        >
          <div class="domains">
            <div v-for="d in store.domains" :key="d.key" class="domain-block">
              <div class="domain-head">
                <div>
                  <b class="domain-name">{{ d.name }}</b>
                  <span class="domain-tagline">{{ d.tagline }}</span>
                </div>
                <div class="domain-stats">
                  <span><b>{{ d.stats.total }}</b> 任务</span>
                  <span v-if="d.stats.active" class="active">活跃 {{ d.stats.active }}</span>
                  <span v-if="d.stats.review" class="review">待评 {{ d.stats.review }}</span>
                  <span v-if="d.stats.failed" class="failed">失败 {{ d.stats.failed }}</span>
                </div>
              </div>
              <div class="modules">
                <div
                  v-for="m in store.modulesOfDomain(d.key)"
                  :key="m.key"
                  class="module-card"
                  @click="goModule(m.key)"
                >
                  <div class="module-head">
                    <b>{{ m.name }}</b>
                    <span class="tagline">{{ m.tagline }}</span>
                  </div>
                  <div class="module-stats">
                    <span><b>{{ m.stats.total }}</b>任务</span>
                    <span class="sep">·</span>
                    <span class="active">活跃 {{ m.stats.active }}</span>
                    <span v-if="m.stats.review" class="sep">·</span>
                    <span v-if="m.stats.review" class="review">待评 {{ m.stats.review }}</span>
                    <span v-if="m.stats.failed" class="sep">·</span>
                    <span v-if="m.stats.failed" class="failed">失败 {{ m.stats.failed }}</span>
                  </div>
                  <div class="module-route">
                    <span>主：</span><b>{{ m.route.primary_tool }}</b>
                    <span v-if="m.route.execution_chain.length" class="chain">
                      · {{ m.route.execution_chain.join(" → ") }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </SectionCard>
      </div>

      <div class="col-side">
        <SectionCard title="今日预警">
          <div v-if="!store.brief">{{ store.loading ? "加载中..." : "暂无数据" }}</div>
          <template v-else>
            <div v-if="store.brief.overdue_tasks.length" class="brief-block">
              <div class="brief-title">超时任务（{{ store.brief.overdue_tasks.length }}）</div>
              <div v-for="t in store.brief.overdue_tasks.slice(0, 4)" :key="t.id" class="brief-row">
                <span class="proj">{{ t.project }}</span>
                <span class="title">{{ t.title }}</span>
                <span class="due">{{ t.due_at }}</span>
              </div>
            </div>
            <div v-if="store.brief.failed_dispatch_tasks.length" class="brief-block">
              <div class="brief-title">调度失败（{{ store.brief.failed_dispatch_tasks.length }}）</div>
              <div v-for="t in store.brief.failed_dispatch_tasks.slice(0, 4)" :key="t.id" class="brief-row">
                <span class="proj">{{ t.project }}</span>
                <span class="title">{{ t.title }}</span>
              </div>
            </div>
            <div v-if="store.brief.due_soon_tasks.length" class="brief-block">
              <div class="brief-title">即将到期</div>
              <div v-for="t in store.brief.due_soon_tasks.slice(0, 4)" :key="t.id" class="brief-row">
                <span class="proj">{{ t.project }}</span>
                <span class="title">{{ t.title }}</span>
                <span class="due">{{ t.due_at }}</span>
              </div>
            </div>
            <div
              v-if="
                !store.brief.overdue_tasks.length &&
                !store.brief.failed_dispatch_tasks.length &&
                !store.brief.due_soon_tasks.length
              "
              class="empty"
            >
              无预警，今天可以专注做战略。
            </div>
          </template>
        </SectionCard>

        <SectionCard title="平台分层">
          <ol class="layers">
            <li v-for="(l, i) in store.operatingSystem?.layers ?? []" :key="i">
              <b>{{ l.name }}</b>
              <span>{{ l.role }}</span>
            </li>
          </ol>
        </SectionCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.hero h1 {
  margin: 0;
  font-size: 24px;
}
.principle {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}
.hero-meta .date {
  color: #94a3b8;
  font-size: 12px;
}
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}
.warnings {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.warning {
  padding: 8px 12px;
  border-radius: 6px;
  background: #fff7ed;
  border-left: 3px solid #f97316;
  color: #9a3412;
  font-size: 13px;
}
.daily-brief {
  display: grid;
  gap: 14px;
}
.brief-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}
.brief-summary > div {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  background: #f8fafc;
}
.summary-label {
  display: block;
  color: #64748b;
  font-size: 12px;
  margin-bottom: 4px;
}
.risk-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.risk-alerts {
  display: grid;
  gap: 8px;
}
.risk-alert {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #fed7aa;
  border-left: 3px solid #f97316;
  border-radius: 8px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 12px;
  cursor: pointer;
}
.risk-alert.high {
  border-color: #fecaca;
  border-left-color: #dc2626;
  background: #fef2f2;
  color: #991b1b;
}
.risk-alert > div {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.risk-alert b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.risk-alert span {
  flex-shrink: 0;
  color: #64748b;
}
.suggestions {
  display: grid;
  gap: 8px;
}
.suggestion {
  width: 100%;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) 56px;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  text-align: left;
  cursor: pointer;
}
.suggestion:hover {
  border-color: #0b67f0;
  background: #f8fbff;
}
.suggestion:disabled {
  cursor: wait;
  opacity: 0.7;
}
.suggestion-priority {
  display: grid;
  place-items: center;
  height: 28px;
  border-radius: 6px;
  background: #eff6ff;
  color: #0b67f0;
  font-size: 12px;
  font-weight: 700;
}
.suggestion-main {
  min-width: 0;
  display: grid;
  gap: 2px;
}
.suggestion-main b,
.suggestion-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.suggestion-main small {
  color: #64748b;
}
.suggestion-action {
  justify-self: end;
  color: #0b67f0;
  font-size: 12px;
  font-weight: 700;
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
.domains {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.domain-block {
  border-left: 3px solid #0b67f0;
  padding-left: 12px;
}
.domain-block:nth-child(2) {
  border-left-color: #f97316;
}
.domain-block:nth-child(3) {
  border-left-color: #16a34a;
}
.domain-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.domain-name {
  font-size: 15px;
  letter-spacing: 0.02em;
}
.domain-tagline {
  display: block;
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}
.domain-stats {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: #64748b;
  align-items: center;
}
.domain-stats b {
  color: #0f172a;
  margin-right: 2px;
}
.domain-stats .active {
  color: #0b67f0;
}
.domain-stats .review {
  color: #f97316;
}
.domain-stats .failed {
  color: #dc2626;
}
.modules {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.module-card {
  border: 1px solid #edf1f6;
  border-radius: 10px;
  padding: 14px;
  cursor: pointer;
  background: #fff;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.module-card:hover {
  border-color: #0b67f0;
  box-shadow: 0 4px 18px rgba(11, 103, 240, 0.12);
}
.module-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.module-head b {
  font-size: 14px;
}
.tagline {
  font-size: 12px;
  color: #64748b;
}
.module-stats {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 12px;
  color: #475569;
  margin-top: 8px;
}
.module-stats .sep {
  color: #cbd5e1;
}
.module-stats .active {
  color: #0b67f0;
}
.module-stats .review {
  color: #f97316;
}
.module-stats .failed {
  color: #dc2626;
}
.module-route {
  margin-top: 6px;
  font-size: 12px;
  color: #334155;
}
.module-route .chain {
  color: #64748b;
}
.brief-block + .brief-block {
  margin-top: 12px;
}
.brief-title {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
  margin-bottom: 6px;
}
.brief-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  padding: 4px 0;
  border-bottom: 1px solid #f1f5f9;
}
.brief-row:last-child {
  border-bottom: 0;
}
.brief-row .proj {
  color: #0b67f0;
  font-weight: 600;
}
.brief-row .title {
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.brief-row .due {
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.empty {
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
  padding: 18px;
}
.layers {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.layers li {
  font-size: 13px;
}
.layers li b {
  margin-right: 6px;
}
.layers li span {
  color: #64748b;
}

@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
