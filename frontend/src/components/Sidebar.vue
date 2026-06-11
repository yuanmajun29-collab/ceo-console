<script setup lang="ts">
import { computed, h, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import type { MenuOption } from "naive-ui";
import { useDashboardStore } from "@/stores/dashboard";

interface NavItem {
  key: string;
  to: string;
  label: string;
  icon: string;
  badgeKey?: "todo" | "review" | "risk";
}

const topItems: NavItem[] = [
  { key: "/", to: "/", label: "首页", icon: "🏠" },
  { key: "/commander", to: "/commander", label: "指挥", icon: "▶" },
]

const bizItems: NavItem[] = [
  { key: "/biz", to: "/biz", label: "总览", icon: "📊" },
  { key: "/biz/project", to: "/biz/project", label: "项目", icon: "📦" },
  { key: "/biz/customer", to: "/biz/customer", label: "客户", icon: "🤝" },
  { key: "/biz/finance", to: "/biz/finance", label: "财务", icon: "💰" },
  { key: "/biz/marketing", to: "/biz/marketing", label: "营销", icon: "📣" },
]

const dailyItems: NavItem[] = [
  { key: "/tasks", to: "/tasks", label: "任务", icon: "☷", badgeKey: "todo" },
  { key: "/review", to: "/review", label: "审查", icon: "☑", badgeKey: "review" },
  { key: "/tools/hub", to: "/tools/hub", label: "知识", icon: "📚" },
  { key: "/tools", to: "/tools", label: "状态", icon: "◉" },
  { key: "/health", to: "/health", label: "健康", icon: "☁" },
]

const supportItems: NavItem[] = [
  { key: "/help", to: "/help", label: "说明", icon: "?" },
  { key: "/repos", to: "/repos", label: "代码", icon: "⌘" },
  { key: "/analytics", to: "/analytics", label: "数据", icon: "▣" },
  { key: "/reports", to: "/reports", label: "报表", icon: "☰" },
  { key: "/decisions", to: "/decisions", label: "决策", icon: "□" },
  { key: "/settings", to: "/settings", label: "设置", icon: "⚙" },
]

const store = useDashboardStore();
const route = useRoute();
const collapsed = ref(false);
const expandedKeys = ref<string[]>(["ops"]);

const badges = computed(() => {
  const c = store.summary?.counts ?? ({} as Record<string, number>);
  return {
    todo: c["待分配"] ?? 0,
    review: c["待人工审查"] ?? 0,
    risk: store.brief?.warnings.length ?? 0,
  };
});

function isActive(to: string): boolean {
  if (to === "/") return route.path === "/";
  if (to === "/tools") return route.path === "/tools";
  if (to === "/biz") return route.path === "/biz" || route.path === "/app/biz";
  return route.path.startsWith(to);
}

function renderLabel(item: NavItem) {
  return () =>
    h(
      RouterLink,
      { to: item.to, class: "menu-link" },
      {
        default: () => [
          h("span", { class: "menu-label" }, item.label),
          item.badgeKey && badges.value[item.badgeKey] > 0
            ? h("span", { class: "badge" }, String(badges.value[item.badgeKey]))
            : null,
        ],
      }
    );
}

function renderIcon(item: NavItem) {
  return () => h("span", { class: "nav-ico", "aria-hidden": "true" }, item.icon);
}

function itemToOption(item: NavItem): MenuOption {
  return {
    key: item.key,
    label: renderLabel(item),
    icon: renderIcon(item),
  };
}

const menuOptions = computed<MenuOption[]>(() => [
  ...topItems.map(itemToOption),
  {
    key: "biz",
    label: "经营",
    icon: () => h("span", { class: "nav-ico", "aria-hidden": "true" }, "📊"),
    children: bizItems.map(itemToOption),
  },
  ...dailyItems.map(itemToOption),
  {
    key: "support",
    label: "支持",
    icon: () => h("span", { class: "nav-ico", "aria-hidden": "true" }, "🔧"),
    children: supportItems.map(itemToOption),
  },
]);

const selectedKey = computed(() => {
  const all = [...topItems, ...dailyItems, ...bizItems, ...supportItems].filter((item) => isActive(item.to));
  return all.sort((a, b) => b.to.length - a.to.length)[0]?.key ?? "/";
});

watch(
  () => route.path,
  () => {
    if (!expandedKeys.value.includes("biz") && bizItems.some((item) => isActive(item.to))) {
      expandedKeys.value = ["biz"];
    }
    if (!expandedKeys.value.includes("support") && supportItems.some((item) => isActive(item.to))) {
      if (!expandedKeys.value.includes("biz")) expandedKeys.value = ["support"];
      else if (!expandedKeys.value.includes("support")) expandedKeys.value.push("support");
    }
  },
  { immediate: true }
);

</script>

<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="brand">
      <div class="brand-mark">C</div>
      <div v-if="!collapsed" class="brand-copy">
        <div class="brand-title">CEO</div>
      </div>
      <button class="collapse-btn" type="button" @click="collapsed = !collapsed">
        {{ collapsed ? "›" : "‹" }}
      </button>
    </div>

    <n-menu
      v-model:expanded-keys="expandedKeys"
      :collapsed="collapsed"
      :collapsed-width="64"
      :collapsed-icon-size="18"
      :options="menuOptions"
      :value="selectedKey"
      :indent="18"
      class="menu"
    />

    <div v-if="!collapsed" class="sidebar-foot">
      <span><span class="dot" />本地</span>
      <span>{{ store.lastLoadedAt ?? "-" }}</span>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: sticky;
  top: 0;
  width: 188px;
  height: 100vh;
  background: linear-gradient(180deg, #061a2f, #031221);
  color: #dbeafe;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #0b2a47;
  transition: width 0.15s ease;
}
.sidebar.collapsed {
  width: 64px;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.brand-mark {
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: 6px;
  background: #fff;
  color: #09233f;
  display: grid;
  place-items: center;
  font-weight: 900;
}
.brand-copy {
  min-width: 0;
  flex: 1;
}
.brand-title {
  font-size: 14px;
  font-weight: 800;
  color: #fff;
}
.collapse-btn {
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.08);
  color: #dbeafe;
  cursor: pointer;
}
.menu {
  flex: 1;
  overflow-y: auto;
  padding: 8px 6px;
}
.sidebar-foot {
  margin-top: auto;
  padding: 12px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #c7d2fe;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #16a34a;
  display: inline-block;
  margin-right: 6px;
}
:deep(.n-menu) {
  --n-item-text-color: #dbeafe !important;
  --n-item-text-color-hover: #fff !important;
  --n-item-text-color-active: #fff !important;
  --n-item-icon-color: #dbeafe !important;
  --n-item-icon-color-hover: #fff !important;
  --n-item-icon-color-active: #fff !important;
  --n-item-color-hover: rgba(11, 99, 229, 0.6) !important;
  --n-item-color-active: #0b63e5 !important;
  --n-item-color-active-hover: #0b63e5 !important;
  --n-item-color-active-collapsed: #0b63e5 !important;
  --n-arrow-color: #dbeafe !important;
}
:deep(.menu-link) {
  color: inherit;
  text-decoration: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  gap: 8px;
  width: 100%;
}
.menu-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nav-ico {
  width: 18px;
  font-size: 16px;
  text-align: center;
}
.badge {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: #ef233c;
  color: #fff;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 700;
}
</style>
