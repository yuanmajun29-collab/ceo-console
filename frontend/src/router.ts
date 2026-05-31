import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import AppShell from "@/layouts/AppShell.vue";

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    component: AppShell,
    children: [
      {
        path: "",
        name: "home",
        component: () => import("@/views/CockpitHome.vue"),
        meta: { title: "CEO 驾驶舱", group: "home" },
      },
      {
        path: "biz/project",
        name: "biz-project",
        component: () => import("@/views/biz/ProjectDelivery.vue"),
        meta: { title: "项目交付", group: "biz", moduleKey: "project" },
      },
      {
        path: "biz/customer",
        name: "biz-customer",
        component: () => import("@/views/biz/CustomerCare.vue"),
        meta: { title: "客户管理", group: "biz", moduleKey: "customer" },
      },
      {
        path: "biz/finance",
        name: "biz-finance",
        component: () => import("@/views/biz/FinanceClinic.vue"),
        meta: { title: "财务问诊", group: "biz", moduleKey: "finance" },
      },
      {
        path: "biz/marketing",
        name: "biz-marketing",
        component: () => import("@/views/biz/MarketingGrowth.vue"),
        meta: { title: "营销推广", group: "biz", moduleKey: "marketing" },
      },
      {
        path: "tasks",
        name: "tasks",
        component: () => import("@/views/ops/TasksCenter.vue"),
        meta: { title: "任务中心", group: "ops" },
      },
      {
        path: "review",
        name: "review",
        component: () => import("@/views/ops/ReviewCenter.vue"),
        meta: { title: "评审中心", group: "ops" },
      },
      {
        path: "decisions",
        name: "decisions",
        component: () => import("@/views/ops/DecisionLog.vue"),
        meta: { title: "决策日志", group: "ops" },
      },
      {
        path: "tools",
        name: "tools",
        component: () => import("@/views/ops/ToolsAndAcp.vue"),
        meta: { title: "AI 工具与 ACP", group: "ops" },
      },
      {
        path: "repos",
        name: "repos",
        component: () => import("@/views/ops/Repositories.vue"),
        meta: { title: "代码仓库", group: "ops" },
      },
      {
        path: "analytics",
        name: "analytics",
        component: () => import("@/views/ops/Analytics.vue"),
        meta: { title: "数据分析", group: "ops" },
      },
      {
        path: "reports",
        name: "reports",
        component: () => import("@/views/ops/Reports.vue"),
        meta: { title: "报表中心", group: "ops" },
      },
      {
        path: "health",
        name: "health",
        component: () => import("@/views/ops/Health.vue"),
        meta: { title: "环境与健康", group: "ops" },
      },
      {
        path: "settings",
        name: "settings",
        component: () => import("@/views/ops/Settings.vue"),
        meta: { title: "设置", group: "system" },
      },
      {
        path: "legacy-bridge",
        name: "legacy-bridge",
        component: () => import("@/views/LegacyBridge.vue"),
        meta: { title: "经典控制台", group: "legacy" },
      },
    ],
  },
];

const router = createRouter({
  history: createWebHistory("/app/"),
  routes,
});

router.afterEach((to) => {
  const title = (to.meta?.title as string | undefined) ?? "CEO 驾驶舱";
  document.title = `${title} · CEO 驾驶舱`;
});

export default router;
