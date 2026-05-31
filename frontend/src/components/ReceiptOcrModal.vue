<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { api } from "@/api/client";
import { endpoints } from "@/api/endpoints";

interface OcrExtracted {
  occurred_on: string;
  amount: string;
  direction: "in" | "out";
  vendor: string;
  category: string;
  currency: string;
  note: string;
  confidence: number;
}

interface OcrResult {
  receipt_filename: string;
  receipt_url: string;
  mime_type: string;
  size_bytes: number;
  extracted: OcrExtracted;
  raw_text: string;
  model: string;
}

const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{
  (e: "update:show", v: boolean): void;
  (e: "created", id: number): void;
}>();

const message = useMessage();

const ocrConfigured = ref<boolean | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const file = ref<File | null>(null);
const previewUrl = ref<string | null>(null);
const result = ref<OcrResult | null>(null);
const loading = ref(false);
const submitting = ref(false);
const dragOver = ref(false);

const form = ref<OcrExtracted>({
  occurred_on: "",
  amount: "",
  direction: "out",
  vendor: "",
  category: "",
  currency: "CNY",
  note: "",
  confidence: 0,
});

watch(
  () => props.show,
  (v) => {
    if (v) {
      void refreshStatus();
      reset();
    } else if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value);
      previewUrl.value = null;
    }
  }
);

onMounted(refreshStatus);

async function refreshStatus() {
  try {
    const s = await api.get<{ configured: boolean }>("/api/finance/ocr/status");
    ocrConfigured.value = s.configured;
  } catch {
    ocrConfigured.value = false;
  }
}

function reset() {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value);
  }
  file.value = null;
  previewUrl.value = null;
  result.value = null;
  form.value = {
    occurred_on: "",
    amount: "",
    direction: "out",
    vendor: "",
    category: "",
    currency: "CNY",
    note: "",
    confidence: 0,
  };
}

function pick() {
  fileInput.value?.click();
}

function onFileChosen(e: Event) {
  const target = e.target as HTMLInputElement;
  const f = target.files?.[0];
  if (f) setFile(f);
}

function onDrop(e: DragEvent) {
  e.preventDefault();
  dragOver.value = false;
  const f = e.dataTransfer?.files?.[0];
  if (f) setFile(f);
}

function setFile(f: File) {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  file.value = f;
  result.value = null;
  previewUrl.value = f.type.startsWith("image/") ? URL.createObjectURL(f) : null;
}

async function recognize() {
  if (!file.value) return;
  if (!ocrConfigured.value) {
    message.error("Gemini API key 未配置，请先设置 CEO_CONSOLE_GEMINI_API_KEY");
    return;
  }
  loading.value = true;
  try {
    const fd = new FormData();
    fd.append("file", file.value);
    const resp = await fetch("/api/finance/ocr", { method: "POST", body: fd });
    const text = await resp.text();
    const body = text ? JSON.parse(text) : {};
    if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
    result.value = body as OcrResult;
    form.value = { ...result.value.extracted };
    message.success("识别完成，请核对后入账");
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    loading.value = false;
  }
}

async function commit() {
  if (!result.value) return;
  if (!form.value.occurred_on || !form.value.amount) {
    message.error("日期和金额必填");
    return;
  }
  submitting.value = true;
  try {
    const tx = await endpoints.createFinanceTransaction({
      ...form.value,
      source: "ocr",
    });
    message.success(`已入账 #${tx.id}`);
    emit("created", tx.id);
    emit("update:show", false);
  } catch (err) {
    message.error((err as Error).message);
  } finally {
    submitting.value = false;
  }
}

const confidencePct = computed(() =>
  Math.round((form.value.confidence ?? 0) * 100)
);
const confidenceTone = computed<"success" | "warning" | "error">(() => {
  if (confidencePct.value >= 75) return "success";
  if (confidencePct.value >= 45) return "warning";
  return "error";
});
</script>

<template>
  <n-modal
    :show="show"
    preset="card"
    title="AI 票据识别"
    style="max-width: 720px"
    :on-update:show="(v: boolean) => emit('update:show', v)"
  >
    <div v-if="ocrConfigured === false" class="banner error">
      <b>Gemini API 未配置。</b>
      请在 launchd 环境或当前 shell 设置
      <code>CEO_CONSOLE_GEMINI_API_KEY</code>
      （或 <code>GEMINI_API_KEY</code> / <code>GOOGLE_API_KEY</code>），然后重启服务。
    </div>

    <div v-if="!result" class="upload-zone-wrap">
      <div
        class="upload-zone"
        :class="{ active: dragOver }"
        @click="pick"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop="onDrop"
      >
        <input
          ref="fileInput"
          type="file"
          accept="image/*,application/pdf"
          hidden
          @change="onFileChosen"
        />
        <template v-if="!file">
          <div class="upload-icon">⤴</div>
          <div class="upload-text">
            <b>点击或拖拽上传票据</b>
            <span>支持 JPG / PNG / WEBP / HEIC / PDF</span>
          </div>
        </template>
        <template v-else>
          <img v-if="previewUrl" :src="previewUrl" class="preview" />
          <div v-else class="upload-text">
            <b>{{ file.name }}</b>
            <span>{{ (file.size / 1024).toFixed(0) }} KB · {{ file.type }}</span>
          </div>
        </template>
      </div>
      <div class="upload-actions">
        <n-button v-if="file" @click="reset">重选</n-button>
        <n-button
          type="primary"
          :loading="loading"
          :disabled="!file || ocrConfigured === false"
          @click="recognize"
        >
          AI 识别
        </n-button>
      </div>
    </div>

    <div v-else class="review">
      <div class="review-left">
        <img
          v-if="previewUrl"
          :src="previewUrl"
          class="review-preview"
          alt="receipt"
        />
        <div v-else class="review-preview fallback">
          {{ result.mime_type }} · {{ (result.size_bytes / 1024).toFixed(0) }} KB
        </div>
        <div class="confidence">
          <n-tag :type="confidenceTone" size="small" :bordered="false">
            置信度 {{ confidencePct }}%
          </n-tag>
          <span class="muted">模型 {{ result.model }}</span>
        </div>
      </div>
      <div class="review-right">
        <n-form label-placement="top" size="small">
          <div class="grid-2">
            <n-form-item label="日期" required>
              <n-input v-model:value="form.occurred_on" placeholder="YYYY-MM-DD" />
            </n-form-item>
            <n-form-item label="方向" required>
              <n-radio-group v-model:value="form.direction">
                <n-radio-button value="out">支出</n-radio-button>
                <n-radio-button value="in">收入</n-radio-button>
              </n-radio-group>
            </n-form-item>
            <n-form-item label="金额（元）" required>
              <n-input v-model:value="form.amount" />
            </n-form-item>
            <n-form-item label="货币">
              <n-input v-model:value="form.currency" />
            </n-form-item>
            <n-form-item label="对方/商家">
              <n-input v-model:value="form.vendor" />
            </n-form-item>
            <n-form-item label="类目">
              <n-input v-model:value="form.category" />
            </n-form-item>
          </div>
          <n-form-item label="备注">
            <n-input
              v-model:value="form.note"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
            />
          </n-form-item>
        </n-form>
      </div>
    </div>

    <template #footer>
      <div class="footer-bar">
        <n-button @click="emit('update:show', false)">取消</n-button>
        <div style="flex:1" />
        <n-button v-if="result" @click="reset">重新上传</n-button>
        <n-button
          v-if="result"
          type="primary"
          :loading="submitting"
          @click="commit"
        >
          确认入账
        </n-button>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.banner.error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin-bottom: 14px;
  line-height: 1.5;
}
.banner code {
  background: #fff;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
}
.upload-zone-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.upload-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 24px;
  background: #f8fafc;
  text-align: center;
  cursor: pointer;
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
  transition: background 0.15s, border-color 0.15s;
}
.upload-zone:hover,
.upload-zone.active {
  border-color: #0b67f0;
  background: #eff6ff;
}
.upload-icon {
  font-size: 36px;
  color: #94a3b8;
}
.upload-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #475569;
}
.upload-text b {
  font-size: 14px;
  color: #0f172a;
}
.upload-text span {
  font-size: 11px;
  color: #94a3b8;
}
.preview {
  max-width: 100%;
  max-height: 240px;
  border-radius: 6px;
}
.upload-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.review {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 16px;
}
.review-preview {
  width: 100%;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}
.review-preview.fallback {
  height: 160px;
  display: grid;
  place-items: center;
  background: #f1f5f9;
  color: #64748b;
  font-size: 12px;
  text-align: center;
}
.confidence {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.muted {
  color: #94a3b8;
  font-size: 11px;
}
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.footer-bar {
  display: flex;
  gap: 8px;
  width: 100%;
}
@media (max-width: 720px) {
  .review {
    grid-template-columns: 1fr;
  }
  .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
