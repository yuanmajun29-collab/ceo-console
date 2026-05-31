<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { useDashboardStore } from "@/stores/dashboard";

interface NavItem {
  to: string;
  label: string;
  icon: string;
  badgeKey?: "todo" | "review" | "risk";
  group: string;
}

const groups: Array<{ title: string | null; items: NavItem[] }> = [
  {
    title: null,
    items: [{ to: "/", label: "CEO 驾驶舱", icon: "⌂", group: "home" }],
  },
  {
    title: "生产与经营",
    items: [
      { to: "/biz/project", label: "项目交付", icon: "◳", group: "biz" },
    ],
  },
  {
    title: "营销与销售",
    items: [
      { to: "/biz/marketing", label: "营销推广", icon: "✎", group: "biz" },
      { to: "/biz/customer", label: "客户与销售", icon: "☎", group: "biz" },
    ],
  },
  {
    title: "财务运作",
    items: [
      { to: "/biz/finance", label: "财务运作", icon: "¥", group: "biz" },
    ],
  },
  {
    title: "协同与执行",
    items: [
      { to: "/tasks", label: "任务中心", icon: "☷", group: "ops", badgeKey: "todo" },
      { to: "/review", label: "评审中心", icon: "☑", group: "ops", badgeKey: "review" },
      { to: "/decisions", label: "决策日志", icon: "□", group: "ops" },
    ],
  },
  {
    title: "平台运维",
    items: [
      { to: "/tools", label: "AI 工具与 ACP", icon: "◉", group: "ops" },
      { to: "/repos", label: "代码仓库", icon: "⌘", group: "ops" },
      { to: "/analytics", label: "数据分析", icon: "▣", group: "ops" },
      { to: "/reports", label: "报表中心", icon: "☰", group: "ops" },
      { to: "/health", label: "环境与健康", icon: "☁", group: "ops" },
    ],
  },
  {
    title: "系统",
    items: [{ to: "/settings", label: "设置", icon: "⚙", group: "ops" }],
  },
];

const store = useDashboardStore();
const route = useRoute();

const badges = computed(() => {
  const c = store.summary?.counts ?? ({} as Record<string, number>);
  return {
    todo: c["待分配"] ?? 0,
    review: c["待人工审查"] ?? 0,
    risk: store.brief?.warnings.length ?? 0,
  };
});

function isActive(to: string): boolean {
  const path = to.split("?")[0];
  if (path === "/") return route.path === "/";
  return route.path.startsWith(path);
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-mark">CC</div>
      <div>
        <div class="brand-title">CEO 驾驶舱</div>
        <div class="brand-sub">ONE-PERSON COMPANY OS</div>
      </div>
    </div>

    <nav class="nav">
      <template v-for="(group, gi) in groups" :key="gi">
        <div v-if="group.title" class="nav-group">{{ group.title }}</div>
        <RouterLink
          v-for="item in group.items"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :class="{ active: isActive(item.to) }"
        >
          <span class="nav-ico">{{ item.icon }}</span>
          <span class="nav-text">{{ item.label }}</span>
          <span
            v-if="item.badgeKey && badges[item.badgeKey] > 0"
            class="badge"
          >
            {{ badges[item.badgeKey] }}
          </span>
        </RouterLink>
      </template>
    </nav>

    <div class="sidebar-foot">
      <span><span class="dot" />本地服务</span>
      <span>{{ store.lastLoadedAt ?? "-" }}</span>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  background: linear-gradient(180deg, #061a2f, #031221);
  color: #dbeafe;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #0b2a47;
}
.brand {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 6px;
  background: #fff;
  color: #09233f;
  display: grid;
  place-items: center;
  font-weight: 900;
}
.brand-title {
  font-size: 14px;
  font-weight: 800;
  color: #fff;
}
.brand-sub {
  font-size: 9px;
  letter-spacing: 0.08em;
  color: #93c5fd;
}
.nav {
  padding: 12px 8px;
  display: grid;
  gap: 4px;
  overflow-y: auto;
}
.nav-group {
  padding: 14px 12px 4px;
  font-size: 11px;
  letter-spacing: 0.08em;
  color: #64748b;
  text-transform: uppercase;
}
.nav-item {
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 0 12px;
  color: #dbeafe;
  text-decoration: none;
  font-size: 13px;
}
.nav-item:hover {
  background: rgba(11, 99, 229, 0.6);
  color: #fff;
}
.nav-item.active {
  background: #0b63e5;
  color: #fff;
}
.nav-ico {
  width: 16px;
  text-align: center;
  opacity: 0.95;
}
.nav-text {
  flex: 1;
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
</style>
