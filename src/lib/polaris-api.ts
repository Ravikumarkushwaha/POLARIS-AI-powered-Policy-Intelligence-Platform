export type RunStatus =
  | "pending"
  | "parsing"
  | "retrieving_context"
  | "analyzing"
  | "synthesizing"
  | "complete"
  | "cancelled"
  | "error";

export type AnalysisMode = "balanced" | "deep";

export type AgentStatus = "pending" | "running" | "done" | "error" | "cancelled";

export type MetricEffect = TraceFields & {
  metric: string;
  direction: "up" | "down" | "flat";
  magnitude: "small" | "moderate" | "large";
  confidence: number;
};

export type DomainAgentOutput = TraceFields & {
  metric_effects: MetricEffect[];
  confidence?: number;
  confidence_basis?: {
    method: string;
    metric_confidences: number[];
    formula: string;
  };
  reasoning: string;
  affected_states_weight: Record<string, number>;
};

export type RiskAgentOutput = TraceFields & {
  risk_level: "Low" | "Medium" | "High";
  justification: string;
  confidence: number;
  confidence_rationale?: string;
  confidence_basis?: { method: string; note: string };
};

export type ScenarioCard = TraceFields & {
  label: string;
  probability: number;
  probability_raw?: number;
  probability_rationale?: string;
  title: string;
  body: string;
  points: string[];
};

export type ScenarioSet = {
  scenarios: ScenarioCard[];
};

export type RecommendationItem = TraceFields & {
  priority: string;
  title: string;
  description: string;
  why: string;
  supporting_signals: string[];
};

export type RecommendationSet = {
  recommendations: RecommendationItem[];
};

export type Run = {
  run_id: string;
  status: RunStatus;
  policy_input: {
    policy_text: string;
    domain_hint: string | null;
    web_enabled?: boolean;
    analysis_mode?: AnalysisMode;
    source_name?: string;
  };
  lifecycle?: {
    queued_at?: string;
    started_at?: string;
    finished_at?: string;
    cancelled_at?: string;
  };
  runtime?: { queue_position: number | null; active: boolean };
  telemetry?: {
    analysis_mode: AnalysisMode;
    planned_calls: number;
    api_requests: number;
    tokens_used: number;
    rate_limit_retries: number;
    wait_until: string | null;
    wait_reason: string | null;
    current_stage: string;
    stage_timings: Record<string, number>;
    resumed_stages: string[];
  };
  parsed_policy: {
    domain: string;
    goals: string[];
    stakeholders: string[];
    affected_sectors: string[];
    timeline_years: number | null;
    known_assumptions?: string[];
  } | null;
  retrieved_context: { chunk_id: string; text: string; relevance: number }[];
  web_sources: {
    title: string;
    url: string;
    source: string;
    text: string;
    retrieval_status?: string;
    published_at?: string;
    retrieved_at?: string;
  }[];
  agents: {
    economic: { status: AgentStatus; output: DomainAgentOutput | null };
    environment: { status: AgentStatus; output: DomainAgentOutput | null };
    social: { status: AgentStatus; output: DomainAgentOutput | null };
    legal_budget: { status: AgentStatus; output: DomainAgentOutput | null };
    risk: { status: AgentStatus; output: RiskAgentOutput | null };
  };
  stages?: Record<string, string>;
  evidence_catalog?: EvidenceItem[];
  citation_version?: number;
  synthesis:
    | (TraceFields & {
        brief?: PolicyBrief | null;
        overall_impact_score: number;
        impact_score_rationale?: string;
        impact_score_basis?: { method: string; rationale: string; note: string };
        verdict: string;
        top_3_effects: string[];
        risk_level: "Low" | "Medium" | "High";
        confidence: number;
        confidence_basis?: {
          method: string;
          components: Record<string, number>;
          formula: string;
          note: string;
        };
      })
    | null;
  scenario_set: ScenarioSet | null;
  recommendations: RecommendationSet | null;
  state_impact: Record<string, number> | null;
  error: string | null;
};

export type RunHistoryItem = {
  analysis_mode?: AnalysisMode;
  run_id: string;
  title: string;
  status: RunStatus;
  domain: string | null;
  created_at: string;
  updated_at: string;
  confidence: number | null;
  impact_score: number | null;
  risk_level: "Low" | "Medium" | "High" | null;
  agents_complete: number;
  web_sources: number;
  error: string | null;
};

export type RunHistoryResponse = {
  items: RunHistoryItem[];
  total: number;
  limit: number;
  offset: number;
};

export const API_BASE_URL: string =
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "http://localhost:8001";

/** Thrown when the backend can't be reached at all (down, CORS, timeout). */
export class NetworkUnreachableError extends Error {
  constructor(message = "Can't reach the analysis server") {
    super(message);
    this.name = "NetworkUnreachableError";
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: init?.signal ?? controller.signal,
      headers:
        init?.body instanceof FormData
          ? new Headers(init?.headers)
          : new Headers({
              "content-type": "application/json",
              ...Object.fromEntries(new Headers(init?.headers)),
            }),
    });
  } catch {
    throw new NetworkUnreachableError();
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: { msg?: string }) => item.msg ?? "Invalid input").join(". ")
          : `Request failed (${response.status})`;
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

export type CreateRunResult = {
  run_id: string;
  reused: boolean;
  reuse_reason: "active" | "cached" | null;
  queue_position: number | null;
};

export function createRun(input: {
  policy_text: string;
  domain_hint: string | null;
  web_enabled?: boolean;
  analysis_mode?: AnalysisMode;
  force_refresh?: boolean;
}) {
  return request<CreateRunResult>("/api/runs", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function uploadPolicy(
  file: File,
  domainHint: string | null,
  webEnabled = true,
  analysisMode: AnalysisMode = "balanced",
  forceRefresh = false,
) {
  const form = new FormData();
  form.append("file", file);
  if (domainHint) form.append("domain_hint", domainHint);
  form.append("web_enabled", String(webEnabled));
  form.append("analysis_mode", analysisMode);
  form.append("force_refresh", String(forceRefresh));
  return request<CreateRunResult & { source_name: string; extracted_characters: number }>(
    "/api/runs/upload",
    { method: "POST", body: form },
  );
}

export function getRun(runId: string) {
  return request<Run>(`/api/runs/${encodeURIComponent(runId)}`);
}

export function resumeRun(runId: string) {
  return request<Run>(`/api/runs/${encodeURIComponent(runId)}/resume`, { method: "POST" });
}

export function cancelRun(runId: string) {
  return request<Run>(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
}

export function deleteRun(runId: string) {
  return request<{ deleted: boolean }>(`/api/runs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
}

export type RuntimeStatus = {
  configured: boolean;
  provider?: string;
  queue: { active_run_id: string | null; queued_runs: number; concurrency: number };
  quota: Record<string, string | number | boolean | null>;
  cache: { web_ttl_seconds: number; document_ttl_seconds: number };
  modes: Record<AnalysisMode, { planned_calls: number }>;
};

export function getRuntime() {
  return request<RuntimeStatus>("/api/runtime");
}
export function isRunActive(status: RunStatus) {
  return !["complete", "error", "cancelled"].includes(status);
}

export function getRunHistory(limit = 100, offset = 0) {
  return request<RunHistoryResponse>(`/api/runs?limit=${limit}&offset=${offset}`);
}

export const STATUS_LABELS: Record<RunStatus, string> = {
  pending: "Queued…",
  parsing: "Parsing policy…",
  retrieving_context: "Retrieving policy evidence…",
  analyzing: "Analyzing…",
  synthesizing: "Synthesizing…",
  complete: "Complete",
  cancelled: "Cancelled",
  error: "Error",
};

export type TraceFields = {
  evidence_ids?: string[];
  conflicting_evidence_ids?: string[];
  kind?: "document_fact" | "external_evidence" | "ai_inference" | "user_assumption";
  assumptions?: string[];
  uncertainty?: string;
};
export type Claim = TraceFields & { text: string };
export type PolicyBrief = Record<
  "policy" | "benefits" | "risks" | "affected" | "uncertainty" | "actions",
  Claim[]
>;
export type EvidenceItem = {
  evidence_id: string;
  kind: "document" | "external";
  title: string;
  text: string;
  section?: string;
  page?: number;
  url?: string;
  retrieval_status?: string;
  published_at?: string;
  retrieved_at?: string;
};
export type WorkspaceJob = {
  run_id: string;
  parent_run_id: string;
  _job_kind: "chat" | "scenario";
  status: RunStatus;
  question?: string;
  title?: string;
  assumptions?: Record<string, string>;
  notes?: string;
  error: string | null;
  baseline_status?: RunStatus;
  baseline_brief?: PolicyBrief | null;
  baseline_verdict?: string | null;
  evidence_catalog?: EvidenceItem[];
  telemetry?: {
    wait_until?: string | null;
    wait_reason?: string | null;
    api_requests?: number;
    tokens_used?: number;
  };
  runtime?: { queue_position: number | null; active: boolean };
  output:
    | (TraceFields & {
        answer?: string;
        partial_findings?: boolean;
        summary?: string;
        brief?: PolicyBrief;
        changes?: (TraceFields & {
          area: string;
          baseline: string;
          revised: string;
          cause: string;
        })[];
      })
    | null;
};
export function getChat(runId: string) {
  return request<{ items: WorkspaceJob[] }>(`/api/runs/${encodeURIComponent(runId)}/chat`);
}
export function askPolaris(runId: string, question: string, requestId: string) {
  return request<WorkspaceJob>(`/api/runs/${encodeURIComponent(runId)}/chat`, {
    method: "POST",
    body: JSON.stringify({ question, request_id: requestId }),
  });
}
export function getScenarios(runId: string) {
  return request<{ items: WorkspaceJob[] }>(`/api/runs/${encodeURIComponent(runId)}/scenarios`);
}
export function createScenario(
  runId: string,
  title: string,
  assumptions: Record<string, string>,
  notes: string,
  requestId: string,
) {
  return request<WorkspaceJob>(`/api/runs/${encodeURIComponent(runId)}/scenarios`, {
    method: "POST",
    body: JSON.stringify({ title, assumptions, notes, request_id: requestId }),
  });
}
export function cancelJob(jobId: string) {
  return request<WorkspaceJob>(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}
export function retryJob(jobId: string) {
  return request<WorkspaceJob>(`/api/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
}
export function renameScenario(jobId: string, title: string) {
  return request<WorkspaceJob>(`/api/scenarios/${encodeURIComponent(jobId)}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}
export function deleteScenario(jobId: string) {
  return request<{ deleted: boolean }>(`/api/scenarios/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  });
}
