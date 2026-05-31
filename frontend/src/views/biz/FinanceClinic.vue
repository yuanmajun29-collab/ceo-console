<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { useDashboardStore } from "@/stores/dashboard";
import { endpoints } from "@/api/endpoints";
import type {
  FinanceOverview,
  FinanceSubscription,
  FinanceTransaction,
} from "@/api/types";
import BusinessModulePage from "./BusinessModulePage.vue";
import SectionCard from "@/components/SectionCard.vue";
import KpiCard from "@/components/KpiCard.vue";
import EmptyState from "@/components/EmptyState.vue";
import ReceiptOcrModal from "@/components/ReceiptOcrModal.vue";

const store = useDashboardStore();
const message = useMessage();

const overview = ref<FinanceOverview | null>(null);
const transactions = ref<FinanceTransaction[]>([]);
const subscriptions = ref<FinanceSubscription[]>([]);
const loading = ref(false);

const showAddTx = ref(false);
const showAddSub = ref(false);
const showImport = ref(false);
const showOcr = ref(false);
const csvText = ref("");

const txForm = ref({
  occurred_on: new Date().toISOString().slice(0, 10),
  amount: "",
  direction: "out" as "in" | "out",
  category: "",
  vendor: "",
  note: "",
  project: "",
});

const subForm = ref({
  name: "",
  vendor: "",
  amount: "",
  cycle: "monthly" as "monthly" | "quarterly" | "yearly" | "once",
  next_renewal_on: "",
  status: "active" as "active" | "paused" | "cancelled",
  note: "",
});

const txFilterMonth = ref<string>("");
const txFilterDirection = ref<string | null>(null);

async function loadAll() {
  loading.value = true;
  try {
    const filters: Record<string, string> = {};
    if (txFilterMonth.value) filters.month = txFilterMonth.value;
    if (txFilterDirection.value) filters.direction = txFilterDirection.value;
    const [o, txs, subs] = await Promise.all([
      endpoints.financeOverview(),
      endpoints.financeTransactions(filters),
      endpoints.financeSubscriptions(),
    ]);
    overview.value = o;
    transactions.value = txs;
    subscriptions.value = subs;
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    loading.value = false;
  }
}

onMounted(loadAll);

async function submitTx() {
  try {
    await endpoints.createFinanceTransaction({ ...txForm.value });
    message.success("已入账");
    showAddTx.value = false;
    txForm.value = {
      occurred_on: new Date().toISOString().slice(0, 10),
      amount: "",
      direction: "out",
      category: "",
      vendor: "",
      note: "",
      project: "",
    };
    await loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}

async function submitSub() {
  try {
    await endpoints.createFinanceSubscription({ ...subForm.value });
    message.success("订阅已添加");
    showAddSub.value = false;
    subForm.value = {
      name: "",
      vendor: "",
      amount: "",
      cycle: "monthly",
      next_renewal_on: "",
      status: "active",
      note: "",
    };
    await loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}

async function submitImport() {
  try {
    const result = await endpoints.importFinanceCsv(csvText.value);
    if (result.skipped.length === 0) {
      message.success(`导入 ${result.imported} 条`);
    } else {
      message.warning(
        `导入 ${result.imported} 条；跳过 ${result.skipped.length} 条（首条原因：${result.skipped[0].reason}）`
      );
    }
    showImport.value = false;
    csvText.value = "";
    await loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}

async function removeTx(id: number) {
  try {
    await endpoints.deleteFinanceTransaction(id);
    await loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}

async function toggleSub(sub: FinanceSubscription) {
  try {
    await endpoints.patchFinanceSubscription(sub.id, {
      status: sub.status === "active" ? "paused" : "active",
    });
    await loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}

async function removeSub(id: number) {
  try {
    await endpoints.deleteFinanceSubscription(id);
    await loadAll();
  } catch (err) {
    message.error((err as Error).message);
  }
}

const kpiExtras = computed(() => {
  const tasks = store.tasksOfModule("finance");
  const bookkeeping = tasks.filter((t) => t.task_type === "bookkeeping").length;
  const report = tasks.filter((t) => t.task_type === "finance_report").length;
  return [
    { label: "票据/记账任务", value: bookkeeping, tone: "blue" as const, hint: "DeepSeek 批量" },
    { label: "现金流问诊任务", value: report, tone: "green" as const, hint: "Claude 推理" },
  ];
});

const cycleLabel: Record<string, string> = {
  monthly: "月付",
  quarterly: "季付",
  yearly: "年付",
  once: "一次性",
};
const statusLabel: Record<string, string> = {
  active: "进行中",
  paused: "已暂停",
  cancelled: "已取消",
};
</script>

<template>
  <BusinessModulePage module-key="finance" :kpi-extras="kpiExtras">
    <template #pre-content>
      <SectionCard
        title="公司财务全景"
        :subtitle="
          overview
            ? `本月 ${overview.current_month_key} · 共 ${overview.transaction_count} 条交易 · ${overview.subscription_count} 项活跃订阅`
            : '加载中…'
        "
      >
        <template #extra>
          <n-button size="small" type="primary" ghost @click="showOcr = true">
            🤖 AI 票据识别
          </n-button>
          <n-button size="small" @click="showImport = true">CSV 导入</n-button>
          <n-button size="small" type="primary" :loading="loading" @click="loadAll">
            刷新
          </n-button>
        </template>
        <div v-if="overview" class="kpi-grid">
          <KpiCard
            label="现金跑道"
            :value="overview.labels.runway"
            tone="green"
            :hint="`月均支出 ${overview.labels.avg_monthly_expense}`"
          />
          <KpiCard
            label="账户余额（累计净额）"
            :value="overview.labels.cash_balance"
            tone="blue"
            hint="累计收入 - 累计支出"
          />
          <KpiCard
            label="本月收入"
            :value="overview.labels.current_month_income"
            tone="green"
            :hint="`上月 ${overview.prev_month_income_cents / 100}`"
          />
          <KpiCard
            label="本月支出"
            :value="overview.labels.current_month_expense"
            tone="red"
            :hint="`上月 ${overview.prev_month_expense_cents / 100}`"
          />
          <KpiCard
            label="本月净额"
            :value="overview.labels.current_month_net"
            :tone="overview.current_month_net_cents >= 0 ? 'green' : 'red'"
          />
          <KpiCard
            label="订阅月支出"
            :value="overview.labels.subscription_monthly"
            tone="orange"
            :hint="`${overview.subscription_count} 项活跃订阅`"
          />
        </div>
        <EmptyState
          v-if="overview && !overview.has_data"
          icon="¥"
          title="还没有财务数据"
          description="录入第一笔交易或添加一项订阅，KPI 会自动出来"
        >
          <n-space>
            <n-button type="primary" @click="showAddTx = true">＋ 录入交易</n-button>
            <n-button @click="showOcr = true">🤖 AI 识别票据</n-button>
            <n-button @click="showAddSub = true">＋ 添加订阅</n-button>
            <n-button @click="showImport = true">CSV 导入</n-button>
          </n-space>
        </EmptyState>
      </SectionCard>

      <SectionCard
        title="交易流水"
        :subtitle="`共 ${transactions.length} 条 · 显示按月与方向筛选后结果`"
      >
        <template #extra>
          <n-input
            v-model:value="txFilterMonth"
            size="small"
            placeholder="2026-05"
            style="width: 120px"
            @blur="loadAll"
          />
          <n-select
            v-model:value="txFilterDirection"
            size="small"
            placeholder="方向"
            clearable
            style="width: 110px"
            :options="[
              { label: '收入', value: 'in' },
              { label: '支出', value: 'out' },
            ]"
            @update:value="loadAll"
          />
          <n-button size="small" type="primary" @click="showAddTx = true">
            ＋ 录入交易
          </n-button>
        </template>
        <EmptyState v-if="transactions.length === 0" icon="—" title="无交易记录" />
        <table v-else class="tx-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>方向</th>
              <th class="num">金额</th>
              <th>类目</th>
              <th>对方</th>
              <th>备注</th>
              <th>项目</th>
              <th>来源</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="tx in transactions" :key="tx.id">
              <td class="mono">{{ tx.occurred_on }}</td>
              <td>
                <n-tag
                  :type="tx.direction === 'in' ? 'success' : 'error'"
                  size="small"
                  :bordered="false"
                >
                  {{ tx.direction === "in" ? "收入" : "支出" }}
                </n-tag>
              </td>
              <td
                class="num"
                :class="tx.direction === 'in' ? 'good' : 'bad'"
              >
                {{ tx.direction === "in" ? "+" : "−" }}{{ tx.amount_label }}
              </td>
              <td>{{ tx.category ?? "—" }}</td>
              <td>{{ tx.vendor ?? "—" }}</td>
              <td class="note">{{ tx.note ?? "" }}</td>
              <td>{{ tx.project ?? "—" }}</td>
              <td class="muted">{{ tx.source }}</td>
              <td>
                <n-button size="tiny" tertiary type="error" @click="removeTx(tx.id)">
                  删除
                </n-button>
              </td>
            </tr>
          </tbody>
        </table>
      </SectionCard>

      <SectionCard
        title="订阅清单"
        :subtitle="`共 ${subscriptions.length} 项 · 月化总计 ${overview?.labels.subscription_monthly ?? '—'}`"
      >
        <template #extra>
          <n-button size="small" type="primary" @click="showAddSub = true">
            ＋ 添加订阅
          </n-button>
        </template>
        <EmptyState v-if="subscriptions.length === 0" icon="—" title="还没有订阅" />
        <div v-else class="sub-grid">
          <div
            v-for="sub in subscriptions"
            :key="sub.id"
            class="sub-card"
            :class="{ paused: sub.status !== 'active' }"
          >
            <div class="sub-head">
              <b>{{ sub.name }}</b>
              <n-tag
                size="tiny"
                :bordered="false"
                :type="sub.status === 'active' ? 'success' : 'default'"
              >
                {{ statusLabel[sub.status] }}
              </n-tag>
            </div>
            <div class="sub-meta">
              <span v-if="sub.vendor">{{ sub.vendor }}</span>
              <span v-if="sub.vendor" class="sep">·</span>
              <span>{{ cycleLabel[sub.cycle] }}</span>
            </div>
            <div class="sub-amount">
              {{ sub.amount_label }}
              <span class="monthly">≈ 月化 {{ sub.monthly_equivalent_label }}</span>
            </div>
            <div v-if="sub.next_renewal_on" class="sub-next">
              下次续费 {{ sub.next_renewal_on }}
            </div>
            <div class="sub-actions">
              <n-button size="tiny" @click="toggleSub(sub)">
                {{ sub.status === "active" ? "暂停" : "恢复" }}
              </n-button>
              <n-button size="tiny" tertiary type="error" @click="removeSub(sub.id)">
                删除
              </n-button>
            </div>
          </div>
        </div>
      </SectionCard>
    </template>
  </BusinessModulePage>

  <n-modal v-model:show="showAddTx" preset="card" title="录入交易" style="max-width:520px">
    <n-form label-placement="top" size="small">
      <div class="grid-2">
        <n-form-item label="日期" required>
          <n-input v-model:value="txForm.occurred_on" placeholder="YYYY-MM-DD" />
        </n-form-item>
        <n-form-item label="方向" required>
          <n-radio-group v-model:value="txForm.direction">
            <n-radio-button value="in">收入</n-radio-button>
            <n-radio-button value="out">支出</n-radio-button>
          </n-radio-group>
        </n-form-item>
        <n-form-item label="金额（元）" required>
          <n-input v-model:value="txForm.amount" placeholder="例如 1280.50" />
        </n-form-item>
        <n-form-item label="类目">
          <n-input v-model:value="txForm.category" placeholder="服务收入 / 订阅 / 差旅…" />
        </n-form-item>
        <n-form-item label="对方">
          <n-input v-model:value="txForm.vendor" placeholder="客户 / 供应商" />
        </n-form-item>
        <n-form-item label="项目">
          <n-input v-model:value="txForm.project" placeholder="可选 · 关联到具体项目" />
        </n-form-item>
      </div>
      <n-form-item label="备注">
        <n-input
          v-model:value="txForm.note"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 4 }"
        />
      </n-form-item>
    </n-form>
    <template #footer>
      <n-space justify="end">
        <n-button @click="showAddTx = false">取消</n-button>
        <n-button type="primary" @click="submitTx">入账</n-button>
      </n-space>
    </template>
  </n-modal>

  <n-modal v-model:show="showAddSub" preset="card" title="添加订阅" style="max-width:520px">
    <n-form label-placement="top" size="small">
      <div class="grid-2">
        <n-form-item label="订阅名称" required>
          <n-input v-model:value="subForm.name" placeholder="例如 GitHub Copilot" />
        </n-form-item>
        <n-form-item label="供应商">
          <n-input v-model:value="subForm.vendor" placeholder="GitHub" />
        </n-form-item>
        <n-form-item label="金额（元）" required>
          <n-input v-model:value="subForm.amount" placeholder="600" />
        </n-form-item>
        <n-form-item label="周期">
          <n-select
            v-model:value="subForm.cycle"
            :options="[
              { label: '月付', value: 'monthly' },
              { label: '季付', value: 'quarterly' },
              { label: '年付', value: 'yearly' },
              { label: '一次性', value: 'once' },
            ]"
          />
        </n-form-item>
        <n-form-item label="下次续费">
          <n-input v-model:value="subForm.next_renewal_on" placeholder="YYYY-MM-DD（可选）" />
        </n-form-item>
        <n-form-item label="状态">
          <n-select
            v-model:value="subForm.status"
            :options="[
              { label: '进行中', value: 'active' },
              { label: '已暂停', value: 'paused' },
              { label: '已取消', value: 'cancelled' },
            ]"
          />
        </n-form-item>
      </div>
      <n-form-item label="备注">
        <n-input
          v-model:value="subForm.note"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 4 }"
        />
      </n-form-item>
    </n-form>
    <template #footer>
      <n-space justify="end">
        <n-button @click="showAddSub = false">取消</n-button>
        <n-button type="primary" @click="submitSub">保存</n-button>
      </n-space>
    </template>
  </n-modal>

  <ReceiptOcrModal
    :show="showOcr"
    @update:show="(v: boolean) => (showOcr = v)"
    @created="() => loadAll()"
  />

  <n-modal v-model:show="showImport" preset="card" title="CSV 导入交易" style="max-width:640px">
    <p class="hint">
      列要求：<code>date,amount,direction,category,vendor,note,project,currency</code>。
      前 3 列必填；direction 用 <code>in</code> 或 <code>out</code>。
    </p>
    <n-input
      v-model:value="csvText"
      type="textarea"
      placeholder="date,amount,direction,category,vendor,note
2026-05-01,3000,in,服务收入,客户A,首期款
2026-05-03,150.50,out,差旅,滴滴,机场"
      :autosize="{ minRows: 8, maxRows: 16 }"
    />
    <template #footer>
      <n-space justify="end">
        <n-button @click="showImport = false">取消</n-button>
        <n-button type="primary" @click="submitImport">导入</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<style scoped>
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}
.tx-table {
  width: 100%;
  font-size: 12px;
  border-collapse: collapse;
}
.tx-table th {
  text-align: left;
  padding: 6px 8px;
  font-weight: 600;
  color: #475569;
  background: #f8fafc;
  position: sticky;
  top: 0;
}
.tx-table th.num,
.tx-table td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.tx-table td {
  padding: 8px;
  border-bottom: 1px solid #f1f5f9;
}
.tx-table .mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #475569;
}
.tx-table .good {
  color: #16a34a;
  font-weight: 700;
}
.tx-table .bad {
  color: #dc2626;
  font-weight: 700;
}
.tx-table .note {
  color: #475569;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tx-table .muted {
  color: #94a3b8;
  font-size: 11px;
}
.sub-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}
.sub-card {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sub-card.paused {
  background: #fafbfc;
  opacity: 0.65;
}
.sub-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sub-head b {
  font-size: 14px;
}
.sub-meta {
  font-size: 11px;
  color: #64748b;
  display: flex;
  gap: 4px;
}
.sub-meta .sep {
  color: #cbd5e1;
}
.sub-amount {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.sub-amount .monthly {
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
}
.sub-next {
  font-size: 11px;
  color: #92400e;
  background: #fffbeb;
  padding: 2px 6px;
  border-radius: 4px;
  align-self: flex-start;
}
.sub-actions {
  display: flex;
  gap: 6px;
  border-top: 1px solid #f1f5f9;
  padding-top: 6px;
}
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: #475569;
}
.hint code {
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
}
</style>
