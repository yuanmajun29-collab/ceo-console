export type TaskStatus = "待分配" | "AI执行中" | "待人工审查" | "已完成";
export type Priority = "P0" | "P1" | "P2";
export type ExecutionState =
  | "idle"
  | "running"
  | "succeeded"
  | "failed"
  | "unsupported";

export interface Task {
  id: number;
  title: string;
  project: string;
  assignee_ai: string;
  status: TaskStatus;
  priority: Priority;
  due_at: string | null;
  estimated_finish_at: string | null;
  acceptance_criteria: string | null;
  notes: string | null;
  execution_state: ExecutionState;
  execution_tool: string | null;
  execution_command: string | null;
  execution_output: string | null;
  execution_error: string | null;
  execution_progress: string | null;
  execution_started_at: string | null;
  execution_finished_at: string | null;
  review_result: string | null;
  review_comment: string | null;
  reviewed_at: string | null;
  task_type: string;
  ai_instruction: string | null;
  locked_scope: string | null;
  expected_output: string | null;
  verification_command: string | null;
  routing_reason: string | null;
  delivery_evidence: string | null;
  created_at: string;
  updated_at: string;
}

export interface DashboardSummary {
  date: string;
  active_projects: number;
  counts: Record<TaskStatus, number>;
  overdue_count: number;
  due_soon_count: number;
  running_dispatch_count: number;
  failed_dispatch_count: number;
}

export interface DailyBrief {
  date: string;
  warnings: string[];
  overdue_tasks: Task[];
  due_soon_tasks: Task[];
  failed_dispatch_tasks: Array<{
    id: number;
    title: string;
    project: string;
    error: string | null;
  }>;
}

export interface BusinessTaskRef {
  id: number;
  title: string;
  project: string;
  task_type: string;
  status: string;
  raw_status: string;
  execution_state: ExecutionState;
  assignee_ai: string;
  priority: Priority;
  due_at: string | null;
  updated_at: string;
  execution_error: string | null;
}

export interface BusinessRoute {
  primary_tool: string;
  recommended_tool: string;
  reason: string;
  execution_chain: string[];
  fallback_applied: boolean;
  skipped_tools: Array<{ tool: string; reason: string }>;
}

export type DomainKey = "operations" | "sales" | "finance";

export interface BusinessDomain {
  key: DomainKey;
  name: string;
  tagline: string;
  module_keys: string[];
  stats: { total: number; active: number; review: number; failed: number };
}

export interface BusinessModule {
  key: "project" | "customer" | "finance" | "marketing";
  domain: DomainKey;
  name: string;
  tagline: string;
  task_types: string[];
  toolchain: string[];
  ceo_actions: string[];
  default_task_type: string;
  task_template: {
    title: string;
    priority: Priority;
    instruction: string;
    expected_output: string;
  };
  stats: { total: number; active: number; review: number; failed: number };
  route: BusinessRoute;
  latest_task: BusinessTaskRef | null;
}

export interface DecisionQueueItem {
  level: Priority;
  task: BusinessTaskRef;
  reason: string;
  action: string;
}

export interface CompanyOperatingSystem {
  generated_at: string;
  principle: string;
  layers: Array<{ name: string; role: string }>;
  interaction_modes: Array<{ name: string; description: string }>;
  counts: Record<TaskStatus, number>;
  domains: BusinessDomain[];
  modules: BusinessModule[];
  decision_queue: DecisionQueueItem[];
}

export interface ProjectRow {
  name: string;
  path: string;
  has_ai_rule: boolean;
  has_cursorrules: boolean;
  has_coordinator: boolean;
  has_execution_checklist: boolean;
  governance_score: number;
  phase: string;
  adr_count: number;
  checklist_total: number;
  checklist_done: number;
  checklist_completion: number;
}

export interface ToolStatusEntry {
  available: boolean;
  runnable: boolean;
  command: string | null;
  candidates: string[];
  reason: string | null;
  quota: {
    available: boolean;
    label: string;
    remaining: number | null;
    limit: number | null;
    unit: string;
    percent: number | null;
    recharge_url?: string | null;
  };
  acp_target: string | null;
  acp_enabled: boolean;
  acp_configured: boolean;
  dynamic_acp: boolean;
  source: string;
}

export type ToolsStatus = Record<string, ToolStatusEntry>;

export type FinanceDirection = "in" | "out";
export type FinanceCycle = "monthly" | "quarterly" | "yearly" | "once";
export type SubscriptionStatus = "active" | "paused" | "cancelled";

export interface FinanceTransaction {
  id: number;
  occurred_on: string;
  amount_cents: number;
  amount: number;
  amount_label: string;
  currency: string;
  direction: FinanceDirection;
  category: string | null;
  vendor: string | null;
  note: string | null;
  project: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface FinanceSubscription {
  id: number;
  name: string;
  vendor: string | null;
  amount_cents: number;
  amount: number;
  amount_label: string;
  currency: string;
  cycle: FinanceCycle;
  monthly_equivalent_cents: number;
  monthly_equivalent_label: string;
  next_renewal_on: string | null;
  status: SubscriptionStatus;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface FinanceOverview {
  currency: string;
  has_data: boolean;
  current_month_key: string;
  current_month_income_cents: number;
  current_month_expense_cents: number;
  current_month_net_cents: number;
  prev_month_income_cents: number;
  prev_month_expense_cents: number;
  cumulative_income_cents: number;
  cumulative_expense_cents: number;
  cash_balance_cents: number;
  subscription_monthly_cents: number;
  avg_monthly_expense_cents: number;
  runway_months: number | null;
  transaction_count: number;
  subscription_count: number;
  labels: {
    current_month_income: string;
    current_month_expense: string;
    current_month_net: string;
    cash_balance: string;
    subscription_monthly: string;
    avg_monthly_expense: string;
    runway: string;
  };
}

export interface DecisionLog {
  id: number;
  project: string;
  decision: string;
  context: string | null;
  reason: string | null;
  impact: string | null;
  created_at: string;
}
