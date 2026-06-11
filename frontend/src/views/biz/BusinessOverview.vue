<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

const router = useRouter();

interface BizModule {
  key: string;
  label: string;
  icon: string;
  path: string;
  desc: string;
}

const modules = ref<BizModule[]>([
  { key: "project", label: "项目", icon: "📦", path: "/biz/project", desc: "交付周期与治理评分" },
  { key: "customer", label: "客户", icon: "🤝", path: "/biz/customer", desc: "客户关系与沟通记录" },
  { key: "finance", label: "财务", icon: "💰", path: "/biz/finance", desc: "收支流水与订阅管理" },
  { key: "marketing", label: "营销", icon: "📣", path: "/biz/marketing", desc: "内容与推广计划" },
]);

function go(path: string) {
  router.push(path);
}
</script>

<template>
  <div class="overview">
    <div class="grid">
      <div v-for="m in modules" :key="m.key" class="card" @click="go(m.path)">
        <div class="icon">{{ m.icon }}</div>
        <div class="info">
          <div class="title">{{ m.label }}</div>
          <div class="desc">{{ m.desc }}</div>
        </div>
        <div class="arrow">›</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; padding: 16px; }
.card { display: flex; align-items: center; gap: 12px; padding: 16px; background: #fff; border-radius: 10px; cursor: pointer; transition: box-shadow .15s; border: 1px solid #eef2f6; }
.card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
.icon { font-size: 24px; }
.info { flex: 1; }
.title { font-weight: 600; font-size: 15px; }
.desc { font-size: 12px; color: #94a3b8; margin-top: 2px; }
.arrow { font-size: 20px; color: #94a3b8; }
</style>
