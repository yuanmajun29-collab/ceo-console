<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useDashboardStore } from "@/stores/dashboard";
import { useUiStore } from "@/stores/ui";

interface CommandItem {
  id: string;
  title: string;
  hint?: string;
  group: string;
  icon: string;
  keywords?: string;
  run: () => void;
}

const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{
  (e: "update:show", v: boolean): void;
}>();

const router = useRouter();
const store = useDashboardStore();
const ui = useUiStore();

const query = ref("");
const selectedIndex = ref(0);
const inputRef = ref<HTMLInputElement | null>(null);

function close() {
  emit("update:show", false);
}

const items = computed<CommandItem[]>(() => {
  const out: CommandItem[] = [];
  const pages: Array<{ path: string; title: string; hint: string; icon: string }> = [
    { path: "/", title: "CEO 驾驶舱", hint: "首页 · KPI / 决策队列 / 业务板块", icon: "⌂" },
    { path: "/biz/project", title: "项目交付", hint: "业务板块 · 项目研发", icon: "◳" },
    { path: "/biz/customer", title: "客户管理", hint: "业务板块 · 客户分诊", icon: "☎" },
    { path: "/biz/finance", title: "财务问诊", hint: "业务板块 · 现金流 / 票据", icon: "¥" },
    { path: "/biz/marketing", title: "营销推广", hint: "业务板块 · 内容车间", icon: "✎" },
    { path: "/tasks", title: "任务中心", hint: "看板 + 表格", icon: "☷" },
    { path: "/review", title: "评审中心", hint: "待人工审查 + 失败队列", icon: "☑" },
    { path: "/decisions", title: "决策日志", hint: "CEO 决策时间轴", icon: "□" },
    { path: "/tools", title: "AI 工具与 ACP", hint: "工具状态 + ACP 体检", icon: "◉" },
    { path: "/repos", title: "代码仓库", hint: "Git 状态 + 行内操作", icon: "⌘" },
    { path: "/analytics", title: "数据分析", hint: "趋势 / 分布 / 效能", icon: "▣" },
    { path: "/reports", title: "报表中心", hint: "运营汇总 / CSV 导出", icon: "☰" },
    { path: "/health", title: "环境与健康", hint: "launchd / 目录 / 工具检测", icon: "☁" },
    { path: "/settings", title: "设置", hint: "调度 / 默认 / 路由规则", icon: "⚙" },
  ];
  for (const page of pages) {
    out.push({
      id: `page:${page.path}`,
      title: page.title,
      hint: page.hint,
      icon: page.icon,
      group: "页面",
      keywords: page.path + " " + page.title + " " + page.hint,
      run: () => router.push(page.path),
    });
  }

  const actions: Array<Omit<CommandItem, "id" | "group">> = [
    {
      title: "新建任务",
      hint: "Cmd/Ctrl + N",
      icon: "＋",
      keywords: "new create task add 新建 创建",
      run: () => ui.openCreateTask(),
    },
    {
      title: "刷新全部数据",
      hint: "重新拉取项目 / 任务 / 工具状态",
      icon: "↻",
      keywords: "refresh reload 刷新",
      run: () => store.loadAll(),
    },
    {
      title: "导出任务 CSV",
      hint: "/api/tasks/export",
      icon: "📤",
      keywords: "export csv 导出",
      run: () => window.open("/api/tasks/export", "_blank"),
    },
    {
      title: "打开经典控制台",
      hint: "/legacy",
      icon: "↗",
      keywords: "legacy classic 经典",
      run: () => window.open("/legacy", "_blank"),
    },
  ];
  for (const a of actions) {
    out.push({
      id: `action:${a.title}`,
      group: "动作",
      ...a,
    });
  }

  for (const t of store.tasks.slice(0, 80)) {
    out.push({
      id: `task:${t.id}`,
      title: t.title,
      hint: `#${t.id} · ${t.project} · ${t.status} · ${t.assignee_ai}`,
      icon: t.priority === "P0" ? "!" : t.priority === "P1" ? "·" : "·",
      group: "任务",
      keywords: `${t.title} ${t.project} ${t.assignee_ai} ${t.task_type} ${t.status} #${t.id}`,
      run: () => ui.openTask(t.id),
    });
  }

  const projects = new Set(store.tasks.map((t) => t.project));
  for (const p of projects) {
    out.push({
      id: `project:${p}`,
      title: p,
      hint: "项目 · 跳到项目交付页",
      icon: "▦",
      group: "项目",
      keywords: p,
      run: () => router.push(`/biz/project?project=${encodeURIComponent(p)}`),
    });
  }

  return out;
});

const filtered = computed<CommandItem[]>(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return items.value.slice(0, 40);
  const tokens = q.split(/\s+/).filter(Boolean);
  return items.value
    .filter((item) => {
      const haystack = `${item.title} ${item.hint ?? ""} ${item.keywords ?? ""}`.toLowerCase();
      return tokens.every((tok) => haystack.includes(tok));
    })
    .slice(0, 40);
});

const grouped = computed(() => {
  const map = new Map<string, CommandItem[]>();
  for (const it of filtered.value) {
    if (!map.has(it.group)) map.set(it.group, []);
    map.get(it.group)!.push(it);
  }
  return Array.from(map.entries());
});

watch(filtered, () => {
  selectedIndex.value = 0;
});
watch(
  () => props.show,
  (v) => {
    if (v) {
      query.value = "";
      selectedIndex.value = 0;
      nextTick(() => inputRef.value?.focus());
    }
  }
);

function runIndex(i: number) {
  const item = filtered.value[i];
  if (!item) return;
  close();
  item.run();
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    selectedIndex.value = Math.min(selectedIndex.value + 1, filtered.value.length - 1);
    scrollSelectedIntoView();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    selectedIndex.value = Math.max(selectedIndex.value - 1, 0);
    scrollSelectedIntoView();
  } else if (e.key === "Enter") {
    e.preventDefault();
    runIndex(selectedIndex.value);
  } else if (e.key === "Escape") {
    e.preventDefault();
    close();
  }
}

function scrollSelectedIntoView() {
  nextTick(() => {
    const el = document.querySelector(".cp-item.active") as HTMLElement | null;
    if (el) el.scrollIntoView({ block: "nearest" });
  });
}

function flatIndex(group: string, idxInGroup: number): number {
  let count = 0;
  for (const [g, list] of grouped.value) {
    if (g === group) return count + idxInGroup;
    count += list.length;
  }
  return -1;
}
</script>

<template>
  <n-modal
    :show="show"
    :mask-closable="true"
    :show-mask="true"
    transform-origin="center"
    :on-update:show="(v: boolean) => emit('update:show', v)"
    :style="{ width: '640px', maxWidth: 'calc(100vw - 32px)', padding: 0 }"
  >
    <div class="cp" @keydown="onKeydown">
      <div class="cp-search">
        <span class="cp-icon">⌕</span>
        <input
          ref="inputRef"
          v-model="query"
          class="cp-input"
          placeholder="搜索页面、任务、项目，或执行动作…"
          autocomplete="off"
        />
        <kbd class="cp-kbd">esc</kbd>
      </div>
      <div class="cp-list">
        <div v-if="filtered.length === 0" class="cp-empty">
          没有匹配项
        </div>
        <template v-for="[group, list] in grouped" :key="group">
          <div class="cp-group">{{ group }}</div>
          <div
            v-for="(item, idx) in list"
            :key="item.id"
            class="cp-item"
            :class="{ active: flatIndex(group, idx) === selectedIndex }"
            @mouseenter="selectedIndex = flatIndex(group, idx)"
            @click="runIndex(flatIndex(group, idx))"
          >
            <span class="cp-item-icon">{{ item.icon }}</span>
            <div class="cp-item-body">
              <div class="cp-item-title">{{ item.title }}</div>
              <div v-if="item.hint" class="cp-item-hint">{{ item.hint }}</div>
            </div>
            <kbd v-if="flatIndex(group, idx) === selectedIndex" class="cp-kbd cp-kbd-enter">↵</kbd>
          </div>
        </template>
      </div>
      <div class="cp-foot">
        <span><kbd class="cp-kbd">↑</kbd><kbd class="cp-kbd">↓</kbd> 选择</span>
        <span><kbd class="cp-kbd">↵</kbd> 执行</span>
        <span><kbd class="cp-kbd">esc</kbd> 关闭</span>
        <span class="cp-foot-hint">{{ filtered.length }} 项</span>
      </div>
    </div>
  </n-modal>
</template>

<style scoped>
.cp {
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: 70vh;
}
.cp-search {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid #e5e7eb;
}
.cp-icon {
  font-size: 18px;
  color: #94a3b8;
}
.cp-input {
  flex: 1;
  border: 0;
  outline: 0;
  background: transparent;
  font-size: 15px;
  color: #0f172a;
}
.cp-list {
  overflow-y: auto;
  flex: 1;
  padding: 8px 0;
}
.cp-empty {
  padding: 32px;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
}
.cp-group {
  padding: 10px 16px 4px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #94a3b8;
  font-weight: 700;
}
.cp-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  cursor: pointer;
}
.cp-item.active {
  background: #eff6ff;
}
.cp-item-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: #f1f5f9;
  display: grid;
  place-items: center;
  font-size: 14px;
  color: #475569;
  flex-shrink: 0;
}
.cp-item.active .cp-item-icon {
  background: #dbeafe;
  color: #1d4ed8;
}
.cp-item-body {
  flex: 1;
  min-width: 0;
}
.cp-item-title {
  font-size: 14px;
  font-weight: 500;
  color: #0f172a;
}
.cp-item-hint {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 1px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cp-foot {
  border-top: 1px solid #f1f5f9;
  padding: 8px 16px;
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: #94a3b8;
}
.cp-foot-hint {
  margin-left: auto;
}
.cp-kbd {
  display: inline-grid;
  place-items: center;
  min-width: 22px;
  padding: 0 6px;
  height: 18px;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  background: #f8fafc;
  font-size: 10px;
  color: #475569;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.cp-kbd-enter {
  color: #1d4ed8;
  border-color: #bfdbfe;
  background: #eff6ff;
}
</style>
