<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader.vue";
import SectionCard from "@/components/SectionCard.vue";
import EmptyState from "@/components/EmptyState.vue";

interface RepoEntry {
  name: string;
  project: string;
  relative_path: string;
  path: string;
  is_git: boolean;
  branch: string | null;
  dirty: boolean;
  changed_count: number;
  remote: string | null;
  last_commit: string | null;
  last_commit_at: string | null;
  status: string;
  error: string | null;
}

interface RepoResponse {
  company_dir: string;
  source: string;
  repositories: RepoEntry[];
  counts: { total: number; git: number; dirty: number; not_git: number };
}

const message = useMessage();
const data = ref<RepoResponse | null>(null);
const loading = ref(false);
const filter = ref<"all" | "dirty" | "clean" | "not_git">("all");
const search = ref("");
const commitMsg = ref("");
const showCommit = ref(false);
const commitTarget = ref<RepoEntry | null>(null);
const acting = ref<string | null>(null);

async function load() {
  loading.value = true;
  try {
    data.value = await api.get<RepoResponse>("/api/repositories");
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    loading.value = false;
  }
}

async function doAction(repo: RepoEntry, action: string, payload: Record<string, unknown> = {}) {
  acting.value = `${repo.path}-${action}`;
  try {
    const result = await api.post<{
      ok: boolean;
      output: string;
      action: string;
    }>(`/api/repositories/action`, { path: repo.path, action, ...payload });
    if (result.ok) {
      message.success(`${action}：${(result.output || "完成").slice(0, 60)}`);
    } else {
      message.warning(`${action}：${(result.output || "失败").slice(0, 80)}`);
    }
    await load();
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    acting.value = null;
  }
}

function openCommit(repo: RepoEntry) {
  commitTarget.value = repo;
  commitMsg.value = "";
  showCommit.value = true;
}
async function submitCommit() {
  if (!commitTarget.value || !commitMsg.value.trim()) {
    message.error("请输入 commit 信息");
    return;
  }
  showCommit.value = false;
  await doAction(commitTarget.value, "commit", { message: commitMsg.value.trim() });
}

const filtered = computed(() => {
  const list = data.value?.repositories ?? [];
  return list.filter((r) => {
    if (filter.value === "dirty" && !r.dirty) return false;
    if (filter.value === "clean" && (r.dirty || !r.is_git)) return false;
    if (filter.value === "not_git" && r.is_git) return false;
    if (search.value) {
      const q = search.value.toLowerCase();
      if (!r.name.toLowerCase().includes(q) && !r.project.toLowerCase().includes(q)) return false;
    }
    return true;
  });
});

onMounted(load);
</script>

<template>
  <PageHeader
    title="代码仓库"
    :subtitle="`共 ${data?.counts.total ?? 0} · Git ${data?.counts.git ?? 0} · 有变更 ${data?.counts.dirty ?? 0}`"
  >
    <template #extra>
      <n-input
        v-model:value="search"
        size="small"
        clearable
        placeholder="搜索"
        style="width: 200px"
      />
      <n-radio-group v-model:value="filter" size="small">
        <n-radio-button value="all">全部</n-radio-button>
        <n-radio-button value="dirty">有变更</n-radio-button>
        <n-radio-button value="clean">干净</n-radio-button>
        <n-radio-button value="not_git">未初始化</n-radio-button>
      </n-radio-group>
      <n-button size="small" type="primary" :loading="loading" @click="load">刷新</n-button>
    </template>
  </PageHeader>

  <EmptyState
    v-if="!loading && filtered.length === 0"
    icon="⌘"
    title="未找到匹配的仓库"
  />
  <div v-else class="grid">
    <SectionCard
      v-for="repo in filtered"
      :key="repo.path"
      :title="repo.name"
      :subtitle="repo.relative_path || repo.project"
    >
      <template #extra>
        <n-tag
          size="small"
          :type="repo.dirty ? 'warning' : repo.is_git ? 'success' : 'default'"
          :bordered="false"
        >
          {{ repo.status }}
        </n-tag>
      </template>
      <div class="meta">
        <div class="meta-line">
          <span>分支</span>
          <b>{{ repo.branch ?? "-" }}</b>
        </div>
        <div class="meta-line">
          <span>变更文件</span>
          <b :class="{ alert: repo.dirty }">{{ repo.changed_count }}</b>
        </div>
        <div class="meta-line">
          <span>远端</span>
          <code>{{ repo.remote ?? "-" }}</code>
        </div>
        <div class="meta-line">
          <span>最近提交</span>
          <code>{{ repo.last_commit ?? "-" }}</code>
        </div>
        <div v-if="repo.last_commit_at" class="meta-line">
          <span>提交时间</span>
          <code>{{ repo.last_commit_at }}</code>
        </div>
        <div v-if="repo.error" class="error">{{ repo.error }}</div>
      </div>

      <div class="actions">
        <n-button
          v-if="!repo.is_git"
          size="tiny"
          type="primary"
          :loading="acting === `${repo.path}-init`"
          @click="doAction(repo, 'init')"
        >
          初始化
        </n-button>
        <template v-else>
          <n-button size="tiny" :loading="acting === `${repo.path}-status`" @click="doAction(repo, 'status')">status</n-button>
          <n-button size="tiny" :loading="acting === `${repo.path}-diff`" @click="doAction(repo, 'diff')">diff</n-button>
          <n-button size="tiny" :loading="acting === `${repo.path}-log`" @click="doAction(repo, 'log')">log</n-button>
          <n-button size="tiny" :loading="acting === `${repo.path}-pull`" @click="doAction(repo, 'pull')">pull</n-button>
          <n-button size="tiny" :loading="acting === `${repo.path}-stage_all`" @click="doAction(repo, 'stage_all')">stage -A</n-button>
          <n-button size="tiny" type="primary" ghost @click="openCommit(repo)">commit…</n-button>
          <n-button size="tiny" :loading="acting === `${repo.path}-push`" @click="doAction(repo, 'push')">push</n-button>
        </template>
      </div>
    </SectionCard>
  </div>

  <n-modal v-model:show="showCommit" preset="card" title="git commit -m" style="max-width: 460px">
    <p class="commit-target">{{ commitTarget?.name }} <code>{{ commitTarget?.path }}</code></p>
    <n-input
      v-model:value="commitMsg"
      type="textarea"
      placeholder="提交说明"
      :autosize="{ minRows: 3, maxRows: 6 }"
    />
    <template #footer>
      <div style="display:flex; justify-content:flex-end; gap:8px">
        <n-button @click="showCommit = false">取消</n-button>
        <n-button type="primary" @click="submitCommit">提交</n-button>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 14px;
}
.meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}
.meta-line {
  display: grid;
  grid-template-columns: 80px minmax(0, 1fr);
  gap: 8px;
  font-size: 12px;
}
.meta-line span {
  color: #94a3b8;
}
.meta-line b {
  color: #0f172a;
}
.meta-line b.alert {
  color: #f97316;
}
.meta-line code {
  background: #f8fafc;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.error {
  padding: 6px 8px;
  background: #fef2f2;
  color: #b91c1c;
  border-radius: 4px;
  font-size: 11px;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  border-top: 1px solid #f1f5f9;
  padding-top: 10px;
}
.commit-target {
  margin: 0 0 8px;
  font-size: 12px;
  color: #475569;
}
.commit-target code {
  font-size: 11px;
  color: #94a3b8;
}
</style>
