import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Loader2,
  PauseCircle,
  StopCircle,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRunActive, STATUS_LABELS, type Run } from "@/lib/polaris-api";
const STEPS = [
  "Policy profile",
  "Evidence",
  "Specialists",
  "Risk & verdict",
  "Scenarios",
  "Recommendations",
];
export function RunProgress({
  run,
  onCancel,
  cancelling,
}: {
  run: Run;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const [now, setNow] = useState(Date.now());
  const active = isRunActive(run.status);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  const t = run.telemetry;
  const wait = t?.wait_until ? Math.max(0, Math.ceil((Date.parse(t.wait_until) - now) / 1000)) : 0;
  const done = [
    Boolean(run.parsed_policy),
    Boolean(
      run.stages?.["retrieval"] === "completed" ||
      run.retrieved_context.length ||
      run.web_sources.length,
    ),
    ["economic", "environment", "social", "legal_budget"].every(
      (k) => run.agents[k as keyof Run["agents"]]?.status === "done",
    ),
    Boolean(run.synthesis),
    Boolean(run.scenario_set),
    Boolean(run.recommendations),
  ];
  const stageKeys = [
    ["parser"],
    ["retrieval"],
    ["specialists", "economic", "environment", "social", "legal_budget"],
    ["risk_synthesis", "risk", "synthesis"],
    ["scenario"],
    ["recommendation"],
  ];
  const states = stageKeys.map((keys, i) => {
    if (done[i]) return "completed";
    const saved = keys.map((key) => run.stages?.[key]);
    if (saved.includes("failed")) return "failed";
    if (saved.includes("cancelled") || run.status === "cancelled") return "cancelled";
    if (saved.includes("running")) return "running";
    if (run.status === "error" && i === done.findIndex((value) => !value)) return "failed";
    return "pending";
  });
  const completed = done.filter(Boolean).length;
  const queued = run.runtime?.queue_position;
  const start = run.lifecycle?.started_at ?? run.lifecycle?.queued_at;
  const end = run.lifecycle?.finished_at ?? run.lifecycle?.cancelled_at;
  const elapsed = start
    ? Math.max(0, Math.floor(((end ? Date.parse(end) : now) - Date.parse(start)) / 1000))
    : 0;
  const title =
    wait && t?.wait_reason !== "provider_cooldown"
      ? "Waiting for the shared API budget"
      : wait
        ? "Waiting for the AI provider's rate limit to reset"
        : queued
          ? `Queued · position ${queued}`
          : STATUS_LABELS[run.status];
  return (
    <section
      className="progress-shell mx-5 mt-6 rounded-2xl border border-border/75 p-4 lg:mx-9"
      aria-label="Analysis progress"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            className={`rounded-lg p-2 ${wait ? "bg-warning/10 text-warning" : "bg-primary/10 text-primary"}`}
          >
            {wait ? (
              <PauseCircle className="size-4" />
            ) : active ? (
              <Loader2 className="size-4 animate-spin" />
            ) : run.status === "error" ? (
              <AlertTriangle className="size-4 text-warning" />
            ) : run.status === "cancelled" ? (
              <StopCircle className="size-4 text-muted-foreground" />
            ) : (
              <CheckCircle2 className="size-4" />
            )}
          </span>
          <div>
            <p className="text-xs font-semibold" aria-live="polite">
              {title}
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {wait
                ? `Resumes in about ${wait}s. Your completed work is saved.`
                : active
                  ? "You can leave this page and reopen the run from your policy library."
                  : `${completed} of 6 sections available in this saved analysis.`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
          {Number.isFinite(elapsed) && elapsed > 0 && (
            <span className="flex items-center gap-1">
              <Clock3 className="size-3" />
              {Math.floor(elapsed / 60)}m {elapsed % 60}s
            </span>
          )}
          {active && (
            <Button
              variant="outline"
              size="sm"
              disabled={cancelling}
              onClick={onCancel}
              className="text-xs"
            >
              <StopCircle className="size-3.5" />
              {cancelling ? "Cancelling…" : "Cancel run"}
            </Button>
          )}
        </div>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-6">
        {STEPS.map((step, i) => (
          <div key={step}>
            <div
              className={`h-1.5 rounded-full shadow-inner ${done[i] ? "bg-primary shadow-[0_0_12px_var(--primary)]" : states[i] === "failed" ? "bg-danger" : states[i] === "running" ? "bg-primary/40 animate-pulse" : "bg-muted"}`}
            />
            <p
              className={`mt-2 flex items-center gap-1 text-[9px] sm:text-[10px] ${done[i] ? "text-primary" : "text-muted-foreground"}`}
            >
              {done[i] && <CheckCircle2 className="size-2.5" />}
              {step}
            </p>
            <p className="mt-1 text-[9px] capitalize text-muted-foreground">{states[i]}</p>
          </div>
        ))}
      </div>
      {t && (
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-border pt-3 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1 capitalize">
            <Zap className="size-3 text-primary" />
            {t.analysis_mode} mode
          </span>
          <span>
            {t.api_requests} requests · {t.planned_calls} planned stages
          </span>
          <span>{(t.tokens_used ?? 0).toLocaleString()} reported tokens</span>
          {t.rate_limit_retries > 0 && <span>{t.rate_limit_retries} rate-limit retries</span>}
          {(t.resumed_stages ?? []).length > 0 && (
            <span>{(t.resumed_stages ?? []).length} saved stages reused</span>
          )}
        </div>
      )}
    </section>
  );
}
