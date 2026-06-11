<script setup lang="ts">
import { ref } from "vue";

const sections = ref([
  {
    title: "🏠 首页（信息流）",
    items: [
      "打开浏览器 http://127.0.0.1:5050 即见",
      "今日焦点：顶部 3 条 AI 推荐今天最重要的事",
      "每条信息流点 ▶ 直接执行，键盘 e 快速执行选中项",
      "j/k 上下导航，Enter 展开详情，i 忽略本条",
    ],
  },
  {
    title: "▶ 指挥（AI Commander）",
    items: [
      "说一句话，系统自动判断用哪个工具执行",
      '示例："检查 ccec 项目状态" → 自动路由 Claude Code',
      '示例："看看本月花了多少钱" → 自动查询财务',
      '示例："以安全工程师审查 Dockerfile" → 路由 OpenClaw',
    ],
  },
  {
    title: "📋 运营",
    items: [
      "☷ 任务 — 查看和管理所有任务",
      "☑ 审查 — 审查 AI 执行完成的任务",
      "📚 知识中心 — 5 标签页：状态/记忆/技能/人格/路由表",
      "◉ 状态 — 9 个 AI 工具的运行状态",
      "☁ 健康 — 工具 Key 是否过期 + 续费提醒",
    ],
  },
  {
    title: "📦 业务",
    items: [
      "📊 总览 — 4 个业务模块的入口聚合页",
      "📦 项目 / 🤝 客户 / 💰 财务 / 📣 营销",
    ],
  },
  {
    title: "🔧 支持",
    items: [
      "⌘ 代码 / ▣ 数据 / ☰ 报表 / □ 决策 / ⚙ 设置",
    ],
  },
  {
    title: "⌨ 快捷键",
    items: [
      "⌘K — 命令面板（搜索页面/工具/任务）",
      "j/k — 信息流上下导航",
      "Enter — 展开/折叠信息流条目",
      "e — 执行选中操作",
      "i — 忽略选中条目",
    ],
  },
]);

const toggle = (idx: number) => {
  const sec = sections.value[idx];
  (sec as any)._open = !(sec as any)._open;
};
</script>

<template>
  <div class="help-page">
    <h3 style="margin: 0 0 16px; font-size: 18px;">使用说明</h3>
    <div
      v-for="(sec, idx) in sections"
      :key="idx"
      class="section"
      @click="toggle(idx)"
    >
      <div class="sec-header">
        <span>{{ sec.title }}</span>
        <span class="arrow">{{ (sec as any)._open ? "▾" : "▸" }}</span>
      </div>
      <ul v-if="(sec as any)._open" class="sec-body">
        <li v-for="(item, i) in sec.items" :key="i">{{ item }}</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.help-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 24px 16px;
}
.section {
  margin-bottom: 8px;
  border: 1px solid #eef2f6;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
}
.sec-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  font-weight: 600;
  font-size: 14px;
  background: #f8fafc;
}
.arrow {
  color: #94a3b8;
  font-size: 12px;
}
.sec-body {
  margin: 0;
  padding: 8px 16px 12px 32px;
  list-style: disc;
  font-size: 13px;
  color: #475569;
  line-height: 1.8;
}
</style>
