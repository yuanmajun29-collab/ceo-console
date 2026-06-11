<script setup lang="ts">
import { onMounted, ref } from "vue";

interface ProjectFinance {
  income_cents: number;
  expense_cents: number;
  net_cents: number;
}

interface Project {
  name: string;
  client_name?: string;
  budget_cents?: number;
  status?: string;
  description?: string;
  _finance?: ProjectFinance;
  _milestones?: { total: number; done: number; progress: string };
}

const projects = ref<Project[]>([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const resp = await fetch("/api/projects");
    const data = await resp.json();
    const list = data.active_projects || data.projects || data || [];
    projects.value = Array.isArray(list) ? list : [];
    for (const p of projects.value) {
      try {
        const [fin, ms] = await Promise.all([
          fetch(`/api/projects/${p.name}/finance`).then(r => r.json()),
          fetch(`/api/projects/${p.name}/milestones/summary`).then(r => r.json()),
        ]);
        p._finance = fin;
        p._milestones = ms;
      } catch {}
    }
  } catch {}
  loading.value = false;
});
</script>

<template>
  <div class="pp">
    <h3>📦 项目</h3>
    <div v-if="loading" class="empty">加载中...</div>
    <div v-else-if="projects.length === 0" class="empty">暂无项目</div>
    <div v-else class="grid">
      <div v-for="p in projects" :key="p.name" class="card">
        <div class="top">
          <span class="name">{{ p.name }}</span>
          <span class="tag" :class="p.status || 'active'">{{ p.status || 'active' }}</span>
        </div>
        <div v-if="p.client_name" class="cl">🤝 {{ p.client_name }}</div>
        <div class="fin">
          <span>预算 {{ ((p.budget_cents || 0)/100).toFixed(0) }}元</span>
          <span v-if="p._finance">收入 {{ (p._finance.income_cents/100).toFixed(0) }}元</span>
          <span v-if="p._finance">支出 {{ (p._finance.expense_cents/100).toFixed(0) }}元</span>
        </div>
        <div v-if="p.description" class="desc">{{ p.description }}</div>
        <div v-if="p._milestones && p._milestones.total > 0" class="ms">
          <span class="ms-bar">
            <span class="ms-fill" :style="{ width: (p._milestones.done / p._milestones.total * 100) + '%' }"></span>
          </span>
          <span class="ms-label">{{ p._milestones.progress }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pp { max-width: 1000px; margin: 0 auto; padding: 20px; }
.pp h3 { margin: 0 0 16px; font-size: 18px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.card { background: #fff; border: 1px solid #eef2f6; border-radius: 10px; padding: 16px; }
.top { display: flex; justify-content: space-between; align-items: center; }
.name { font-weight: 600; font-size: 15px; }
.tag { font-size: 11px; padding: 2px 10px; border-radius: 10px; background: #e8f5e9; color: #2e7d32; font-weight: 500; }
.tag.completed { background: #e3f2fd; color: #1565c0; }
.tag.paused { background: #fff3e0; color: #e65100; }
.cl { font-size: 13px; color: #64748b; margin-top: 6px; }
.fin { display: flex; gap: 16px; font-size: 13px; color: #475569; margin-top: 10px; padding-top: 10px; border-top: 1px solid #f1f5f9; }
.desc { font-size: 12px; color: #94a3b8; margin-top: 6px; }
.ms { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
.ms-bar { flex: 1; height: 6px; background: #eef2f6; border-radius: 3px; overflow: hidden; }
.ms-fill { display: block; height: 100%; background: #3b82f6; border-radius: 3px; transition: width .3s; }
.ms-label { font-size: 11px; color: #64748b; white-space: nowrap; }
.empty { text-align: center; color: #94a3b8; padding: 40px; font-size: 14px; }
</style>
