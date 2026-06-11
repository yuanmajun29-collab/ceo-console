<script setup lang="ts">
import { onMounted, ref } from "vue";

interface Client {
  name: string;
  contact?: string;
  notes?: string;
  projects?: string[];
  finance?: { income_cents: number; expense_cents: number };
}

interface Activity {
  id: number;
  activity_type: string;
  content: string;
  created_at: string;
}

const clients = ref<Client[]>([]);
const loading = ref(true);
const selectedClient = ref<string | null>(null);
const activities = ref<Activity[]>([]);
const newActivity = ref("");
const showActPanel = ref(false);

onMounted(async () => {
  try {
    const resp = await fetch("/api/clients");
    clients.value = await resp.json();
  } catch {}
  loading.value = false;
});

async function openActivities(name: string) {
  selectedClient.value = name;
  showActPanel.value = true;
  try {
    const resp = await fetch(`/api/clients/${name}/activities`);
    activities.value = await resp.json();
  } catch {}
}

async function addActivity() {
  if (!newActivity.value.trim() || !selectedClient.value) return;
  try {
    await fetch(`/api/clients/${selectedClient.value}/activities`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: newActivity.value.trim() }),
    });
    newActivity.value = "";
    const resp = await fetch(`/api/clients/${selectedClient.value}/activities`);
    activities.value = await resp.json();
  } catch {}
}

const typeIcon = (t: string) => t === "meeting" ? "📅" : t === "call" ? "📞" : t === "email" ? "📧" : "📝";
</script>

<template>
  <div class="cp">
    <h3>🤝 客户</h3>
    <div v-if="loading" class="empty">加载中...</div>
    <div v-else-if="clients.length === 0" class="empty">暂无客户</div>
    <div v-else class="grid">
      <div v-for="c in clients" :key="c.name" class="card" @click="openActivities(c.name)">
        <div class="top">
          <span class="name">{{ c.name }}</span>
          <span class="act-link">📋</span>
        </div>
        <div v-if="c.contact" class="con">📞 {{ c.contact }}</div>
        <div v-if="c.projects && c.projects.length" class="pro">📦 {{ c.projects.length }} 个项目</div>
        <div v-if="c.finance" class="fin">
          <span>收入 {{ (c.finance.income_cents/100).toFixed(0) }}元</span>
          <span>支出 {{ (c.finance.expense_cents/100).toFixed(0) }}元</span>
        </div>
        <div v-if="c.notes" class="note">{{ c.notes }}</div>
      </div>
    </div>

    <!-- 沟通记录面板 -->
    <div v-if="showActPanel" class="panel-overlay" @click.self="showActPanel = false">
      <div class="panel">
        <div class="panel-header">
          <h4>📋 {{ selectedClient }} — 沟通记录</h4>
          <button class="close-btn" @click="showActPanel = false">✕</button>
        </div>

        <div class="timeline">
          <div v-for="a in activities" :key="a.id" class="tl-item">
            <span class="tl-icon">{{ typeIcon(a.activity_type) }}</span>
            <div class="tl-body">
              <div class="tl-content">{{ a.content }}</div>
              <div class="tl-time">{{ a.created_at?.slice(0, 16) }}</div>
            </div>
          </div>
          <div v-if="activities.length === 0" class="empty" style="padding:20px">暂无记录</div>
        </div>

        <div class="add-row">
          <input v-model="newActivity" placeholder="记录沟通内容..." class="act-input" @keyup.enter="addActivity" />
          <button class="act-btn" @click="addActivity">发送</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cp { max-width: 1000px; margin: 0 auto; padding: 20px; position: relative; }
.cp h3 { margin: 0 0 16px; font-size: 18px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.card { background: #fff; border: 1px solid #eef2f6; border-radius: 10px; padding: 16px; cursor: pointer; transition: box-shadow .15s; }
.card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
.top { display: flex; justify-content: space-between; align-items: center; }
.name { font-weight: 600; font-size: 15px; }
.act-link { font-size: 14px; color: #94a3b8; }
.con { font-size: 13px; color: #64748b; margin-top: 6px; }
.pro { font-size: 13px; color: #475569; margin-top: 6px; }
.fin { display: flex; gap: 16px; font-size: 13px; color: #475569; margin-top: 10px; padding-top: 10px; border-top: 1px solid #f1f5f9; }
.note { font-size: 12px; color: #94a3b8; margin-top: 6px; }
.empty { text-align: center; color: #94a3b8; padding: 40px; font-size: 14px; }

/* 沟通记录面板 */
.panel-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.3); z-index: 100; display: flex; justify-content: center; align-items: center; }
.panel { background: #fff; border-radius: 12px; width: 500px; max-height: 80vh; display: flex; flex-direction: column; box-shadow: 0 8px 30px rgba(0,0,0,.12); }
.panel-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid #eef2f6; }
.panel-header h4 { margin: 0; font-size: 15px; }
.close-btn { border: none; background: none; font-size: 16px; cursor: pointer; color: #94a3b8; }
.timeline { flex: 1; overflow-y: auto; padding: 16px 20px; }
.tl-item { display: flex; gap: 10px; margin-bottom: 14px; }
.tl-icon { font-size: 16px; margin-top: 2px; }
.tl-body { flex: 1; }
.tl-content { font-size: 13px; color: #334155; line-height: 1.5; }
.tl-time { font-size: 11px; color: #94a3b8; margin-top: 3px; }
.add-row { display: flex; gap: 8px; padding: 12px 20px; border-top: 1px solid #eef2f6; }
.act-input { flex: 1; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 12px; font-size: 13px; outline: none; }
.act-input:focus { border-color: #3b82f6; }
.act-btn { background: #3b82f6; color: #fff; border: none; border-radius: 8px; padding: 8px 16px; font-size: 13px; cursor: pointer; }
.act-btn:hover { background: #2563eb; }
</style>
