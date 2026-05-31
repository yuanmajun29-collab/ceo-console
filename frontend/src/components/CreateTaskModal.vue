<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useMessage } from "naive-ui";
import { endpoints } from "@/api/endpoints";
import { useDashboardStore } from "@/stores/dashboard";

const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{
  (e: "update:show", v: boolean): void;
  (e: "created", id: number): void;
}>();

const store = useDashboardStore();
const message = useMessage();
const saving = ref(false);

const form = ref({
  title: "",
  project: "",
  task_type: "fullstack",
  priority: "P1" as "P0" | "P1" | "P2",
  assignee_ai: "Other",
  auto_route: true,
  due_at: "",
  ai_instruction: "",
  acceptance_criteria: "",
  locked_scope: "",
  expected_output: "",
  auto_dispatch: false,
});

const projects = computed(() => {
  const s = new Set(store.tasks.map((t) => t.project));
  return Array.from(s).sort();
});

watch(
  () => props.show,
  (v) => {
    if (v) {
      form.value = {
        title: "",
        project: projects.value[0] ?? "",
        task_type: "fullstack",
        priority: "P1",
        assignee_ai: "Other",
        auto_route: true,
        due_at: "",
        ai_instruction: "",
        acceptance_criteria: "",
        locked_scope: "",
        expected_output: "",
        auto_dispatch: false,
      };
    }
  }
);

const TASK_TYPES = [
  { value: "fullstack", label: "全栈研发" },
  { value: "market_research", label: "市场调研" },
  { value: "architecture", label: "架构设计" },
  { value: "code_edit", label: "代码修改" },
  { value: "testing", label: "测试验证" },
  { value: "docs", label: "文档交付" },
  { value: "security_review", label: "安全审查" },
  { value: "quality_review", label: "质量审查" },
  { value: "delivery", label: "交付打包" },
  { value: "customer_triage", label: "客户分诊" },
  { value: "contract_review", label: "合同审查" },
  { value: "bookkeeping", label: "财务记账" },
  { value: "finance_report", label: "财务问诊" },
  { value: "marketing_content", label: "营销内容" },
  { value: "social_monitor", label: "社媒监听" },
];

const AI_OPTIONS = [
  { value: "Other", label: "Other（智能路由）" },
  { value: "Antigravity", label: "Antigravity" },
  { value: "Claude Code", label: "Claude Code" },
  { value: "Codex", label: "Codex" },
  { value: "Gemini", label: "Gemini" },
  { value: "DeepSeek V4-Pro", label: "DeepSeek V4-Pro" },
  { value: "Cursor", label: "Cursor" },
];

async function submit() {
  if (!form.value.title.trim()) {
    message.error("任务名称必填");
    return;
  }
  if (!form.value.project.trim()) {
    message.error("项目必填");
    return;
  }
  saving.value = true;
  try {
    const payload: Record<string, unknown> = {
      title: form.value.title.trim(),
      project: form.value.project.trim(),
      task_type: form.value.task_type,
      priority: form.value.priority,
      assignee_ai: form.value.assignee_ai,
      auto_route: form.value.auto_route,
      ai_instruction: form.value.ai_instruction,
      acceptance_criteria: form.value.acceptance_criteria,
      locked_scope: form.value.locked_scope,
      expected_output: form.value.expected_output,
    };
    if (form.value.due_at) payload.due_at = form.value.due_at;
    const task = await endpoints.createTask(payload);
    message.success(`任务 #${task.id} 已创建`);
    if (form.value.auto_dispatch) {
      try {
        await endpoints.dispatchTask(task.id);
        message.info("已自动发起调度");
      } catch (err) {
        message.warning(`创建成功，但调度失败：${(err as Error).message}`);
      }
    }
    emit("created", task.id);
    emit("update:show", false);
    await store.loadAll();
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <n-modal
    :show="show"
    preset="card"
    title="新建任务"
    style="max-width: 640px"
    :on-update:show="(v: boolean) => emit('update:show', v)"
  >
    <n-form label-placement="top" size="small">
      <div class="grid">
        <n-form-item label="任务名称" required>
          <n-input v-model:value="form.title" placeholder="一句话描述要做什么" />
        </n-form-item>
        <n-form-item label="所属项目" required>
          <n-select
            v-model:value="form.project"
            :options="projects.map((p) => ({ label: p, value: p }))"
            placeholder="选择或输入新项目名"
            filterable
            tag
          />
        </n-form-item>
        <n-form-item label="任务类型">
          <n-select v-model:value="form.task_type" :options="TASK_TYPES" />
        </n-form-item>
        <n-form-item label="优先级">
          <n-radio-group v-model:value="form.priority">
            <n-radio-button value="P0">P0</n-radio-button>
            <n-radio-button value="P1">P1</n-radio-button>
            <n-radio-button value="P2">P2</n-radio-button>
          </n-radio-group>
        </n-form-item>
        <n-form-item label="指派给">
          <n-select v-model:value="form.assignee_ai" :options="AI_OPTIONS" />
        </n-form-item>
        <n-form-item label="截止时间">
          <n-input
            v-model:value="form.due_at"
            placeholder="2026-05-30 18:00:00（可选）"
          />
        </n-form-item>
      </div>
      <n-form-item label="给 AI 的指令">
        <n-input
          v-model:value="form.ai_instruction"
          type="textarea"
          placeholder="明确告诉 AI 要做什么、不做什么"
          :autosize="{ minRows: 2, maxRows: 5 }"
        />
      </n-form-item>
      <n-form-item label="验收标准">
        <n-input
          v-model:value="form.acceptance_criteria"
          type="textarea"
          placeholder="完成的判定条件，方便人工审查"
          :autosize="{ minRows: 2, maxRows: 4 }"
        />
      </n-form-item>
      <div class="grid">
        <n-form-item label="锁定范围">
          <n-input v-model:value="form.locked_scope" placeholder="例如：src/gate/，避免改动无关文件" />
        </n-form-item>
        <n-form-item label="预期产物">
          <n-input v-model:value="form.expected_output" placeholder="文件、报告、PR 链接等" />
        </n-form-item>
      </div>
      <div class="flags">
        <n-checkbox v-model:checked="form.auto_route">
          智能路由（按 Token 优先策略选工具）
        </n-checkbox>
        <n-checkbox v-model:checked="form.auto_dispatch">
          创建后立即调度
        </n-checkbox>
      </div>
    </n-form>

    <template #footer>
      <div class="footer">
        <n-button @click="emit('update:show', false)">取消</n-button>
        <n-button type="primary" :loading="saving" @click="submit">创建任务</n-button>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.flags {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  padding-top: 4px;
}
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
@media (max-width: 720px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
