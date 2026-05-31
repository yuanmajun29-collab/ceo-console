<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useMessage, useDialog } from "naive-ui";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader.vue";
import SectionCard from "@/components/SectionCard.vue";

interface SettingsPayload {
  settings: {
    dispatch_timeout_seconds: number;
    auto_route_new_tasks: boolean;
    dashboard_refresh_seconds: number;
    default_task_type: string;
    default_assignee_ai: string;
  };
  routing_rules: Record<string, { tool: string; reason: string }>;
  allowed: {
    task_types: string[];
    assignee_ai: string[];
  };
}

const message = useMessage();
const dialog = useDialog();
const data = ref<SettingsPayload | null>(null);
const form = ref({
  dispatch_timeout_seconds: 1800,
  auto_route_new_tasks: true,
  dashboard_refresh_seconds: 15,
  default_task_type: "fullstack",
  default_assignee_ai: "Other",
});
const saving = ref(false);

async function load() {
  data.value = await api.get<SettingsPayload>("/api/settings");
  form.value = { ...data.value.settings };
}

onMounted(load);

async function save() {
  saving.value = true;
  try {
    const res = await api.patch<{ ok: boolean }>("/api/settings", form.value);
    if (res.ok) message.success("设置已保存");
    await load();
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    saving.value = false;
  }
}

function resetDefaults() {
  dialog.warning({
    title: "恢复默认设置？",
    content: "当前的保存值会被清空，恢复到内置默认。",
    positiveText: "恢复",
    negativeText: "取消",
    onPositiveClick: async () => {
      await api.post("/api/settings/reset", {});
      message.success("已恢复默认");
      await load();
    },
  });
}

async function refreshTools() {
  try {
    await api.post("/api/settings/refresh-tools", {});
    message.success("工具状态已重新探测");
  } catch (err) {
    message.error((err as Error).message);
  }
}

const TYPE_LABEL: Record<string, string> = {
  market_research: "市场调研",
  architecture: "架构设计",
  fullstack: "全栈研发",
  code_edit: "代码修改",
  testing: "测试验证",
  docs: "文档交付",
  security_review: "安全审查",
  quality_review: "质量审查",
  delivery: "交付打包",
  customer_triage: "客户分诊",
  contract_review: "合同审查",
  bookkeeping: "财务记账",
  finance_report: "财务问诊",
  marketing_content: "营销内容",
  social_monitor: "社媒监听",
};
</script>

<template>
  <PageHeader
    title="设置"
    subtitle="平台行为 · 默认策略 · 工具刷新"
  >
    <template #extra>
      <n-button size="small" @click="refreshTools">重测工具</n-button>
      <n-button size="small" type="error" ghost @click="resetDefaults">恢复默认</n-button>
      <n-button size="small" type="primary" :loading="saving" @click="save">保存</n-button>
    </template>
  </PageHeader>

  <SectionCard title="调度与刷新">
    <n-form label-placement="left" label-width="160" :model="form">
      <n-form-item label="调度超时（秒）">
        <n-input-number
          v-model:value="form.dispatch_timeout_seconds"
          :min="60"
          :max="7200"
          :step="60"
        />
        <span class="help">超时后自动失败回退到待分配</span>
      </n-form-item>
      <n-form-item label="看板刷新（秒）">
        <n-input-number
          v-model:value="form.dashboard_refresh_seconds"
          :min="5"
          :max="300"
          :step="5"
        />
        <span class="help">前端轮询间隔，建议 15-30 秒</span>
      </n-form-item>
    </n-form>
  </SectionCard>

  <SectionCard title="任务默认行为">
    <n-form label-placement="left" label-width="160" :model="form">
      <n-form-item label="默认任务类型">
        <n-select
          v-model:value="form.default_task_type"
          :options="(data?.allowed.task_types ?? []).map((v) => ({ label: TYPE_LABEL[v] ?? v, value: v }))"
        />
      </n-form-item>
      <n-form-item label="默认 AI 执行端">
        <n-select
          v-model:value="form.default_assignee_ai"
          :options="(data?.allowed.assignee_ai ?? []).map((v) => ({ label: v, value: v }))"
        />
      </n-form-item>
      <n-form-item label="新任务智能路由">
        <n-switch v-model:value="form.auto_route_new_tasks" />
        <span class="help">开启后创建任务自动选择 Token 最优工具</span>
      </n-form-item>
    </n-form>
  </SectionCard>

  <SectionCard title="路由规则" subtitle="任务类型 → 默认工具 + 理由">
    <table class="rules">
      <thead>
        <tr>
          <th>任务类型</th>
          <th>默认工具</th>
          <th>路由理由</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(rule, key) in data?.routing_rules ?? {}" :key="key">
          <td><b>{{ TYPE_LABEL[key] ?? key }}</b></td>
          <td><n-tag size="small" :bordered="false">{{ rule.tool }}</n-tag></td>
          <td class="reason">{{ rule.reason }}</td>
        </tr>
      </tbody>
    </table>
  </SectionCard>
</template>

<style scoped>
.help {
  margin-left: 12px;
  font-size: 12px;
  color: #64748b;
}
.rules {
  width: 100%;
  font-size: 12px;
  border-collapse: collapse;
}
.rules th {
  text-align: left;
  padding: 6px 8px;
  font-weight: 600;
  color: #475569;
  background: #f8fafc;
}
.rules td {
  padding: 8px;
  border-bottom: 1px solid #f1f5f9;
}
.rules .reason {
  color: #475569;
  line-height: 1.5;
}
</style>
