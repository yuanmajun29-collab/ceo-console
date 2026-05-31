import { api } from "./client";
import type {
  CompanyOperatingSystem,
  DailyBrief,
  DashboardSummary,
  DecisionLog,
  FinanceOverview,
  FinanceSubscription,
  FinanceTransaction,
  ProjectRow,
  Task,
  ToolsStatus,
} from "./types";

export const endpoints = {
  dashboardSummary: () =>
    api.get<DashboardSummary>("/api/dashboard-summary"),
  dailyBrief: () => api.get<DailyBrief>("/api/daily-brief"),
  companyOperatingSystem: () =>
    api.get<CompanyOperatingSystem>("/api/company-operating-system"),
  tasks: (query?: Record<string, string | undefined>) => {
    const qs = new URLSearchParams();
    if (query) {
      for (const [k, v] of Object.entries(query)) {
        if (v) qs.set(k, v);
      }
    }
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return api.get<Task[]>(`/api/tasks${suffix}`);
  },
  task: (id: number) => api.get<Task>(`/api/tasks/${id}`),
  createTask: (body: Record<string, unknown>) =>
    api.post<Task>("/api/tasks", body),
  patchTask: (id: number, body: Record<string, unknown>) =>
    api.patch<Task>(`/api/tasks/${id}`, body),
  dispatchTask: (id: number) =>
    api.post<{ ok: boolean }>(`/api/tasks/${id}/dispatch`, {}),
  retryTask: (id: number) =>
    api.post<{ ok: boolean }>(`/api/tasks/${id}/retry`, {}),
  routeTask: (id: number) =>
    api.post<{ ok: boolean; tool: string; reason: string }>(
      `/api/tasks/${id}/route`,
      {}
    ),
  reviewTask: (id: number, decision: "approve" | "reject", comment = "") =>
    api.post<Task>(`/api/tasks/${id}/review`, { decision, comment }),
  bulkDispatch: (ids: number[]) =>
    api.post<{
      ok: boolean;
      queued_count: number;
      queued_ids: number[];
      skipped: Array<{ id: number; reason: string }>;
      message: string;
    }>("/api/tasks/bulk-dispatch", { ids }),
  bulkRetry: (ids: number[]) =>
    api.post<{
      ok: boolean;
      queued_count: number;
      queued: Array<{ id: number; tool: string }>;
      skipped: Array<{ id: number; reason: string }>;
      message: string;
    }>("/api/tasks/bulk-retry", { ids }),
  bulkReview: (ids: number[], decision: "approve" | "reject", comment = "") =>
    api.post<{
      ok: boolean;
      applied_count: number;
      applied_ids: number[];
      skipped: Array<{ id: number; reason: string }>;
      decision: string;
      message: string;
    }>("/api/tasks/bulk-review", { ids, decision, comment }),
  toolsStatus: () => api.get<ToolsStatus>("/api/tools/status"),
  decisionLogs: (project?: string, limit = 30) => {
    const qs = new URLSearchParams();
    if (project) qs.set("project", project);
    qs.set("limit", String(limit));
    return api.get<DecisionLog[]>(`/api/decision-logs?${qs.toString()}`);
  },
  createDecisionLog: (body: Record<string, unknown>) =>
    api.post<DecisionLog>("/api/decision-logs", body),
  projects: () =>
    api.get<{
      company_dir: string;
      projects: ProjectRow[];
      archived_projects: string[];
      active_count: number;
      archived_count: number;
      source: string;
      warning: string | null;
    }>("/api/projects"),
  health: () => api.get<Record<string, unknown>>("/api/health"),
  financeOverview: () => api.get<FinanceOverview>("/api/finance/overview"),
  financeTransactions: (filters?: Record<string, string | undefined>) => {
    const qs = new URLSearchParams();
    if (filters) {
      for (const [k, v] of Object.entries(filters)) {
        if (v) qs.set(k, v);
      }
    }
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return api.get<FinanceTransaction[]>(`/api/finance/transactions${suffix}`);
  },
  createFinanceTransaction: (body: Record<string, unknown>) =>
    api.post<FinanceTransaction>("/api/finance/transactions", body),
  deleteFinanceTransaction: (id: number) =>
    api.del<{ ok: boolean }>(`/api/finance/transactions/${id}`),
  importFinanceCsv: (csvText: string) =>
    fetch("/api/finance/transactions/import-csv", {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: csvText,
    }).then(async (r) => {
      const text = await r.text();
      const data = text ? JSON.parse(text) : {};
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      return data as { imported: number; skipped: Array<{ row: number; reason: string }> };
    }),
  financeSubscriptions: (status?: string) => {
    const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
    return api.get<FinanceSubscription[]>(`/api/finance/subscriptions${suffix}`);
  },
  createFinanceSubscription: (body: Record<string, unknown>) =>
    api.post<FinanceSubscription>("/api/finance/subscriptions", body),
  patchFinanceSubscription: (id: number, body: Record<string, unknown>) =>
    api.patch<FinanceSubscription>(`/api/finance/subscriptions/${id}`, body),
  deleteFinanceSubscription: (id: number) =>
    api.del<{ ok: boolean }>(`/api/finance/subscriptions/${id}`),
};
