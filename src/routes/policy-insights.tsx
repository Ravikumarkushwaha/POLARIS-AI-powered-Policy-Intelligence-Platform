import { createFileRoute, Link } from "@tanstack/react-router";
import { AlertTriangle, ArrowRight, BookOpenText, BriefcaseBusiness, Building2, CheckCircle2, Gauge, Globe2, Landmark, ShieldCheck, Sparkles, TrendingUp, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { getRun, getRunHistory, type Run, type RunHistoryItem } from "@/lib/polaris-api";
import { asPercent } from "@/lib/report-export";

export function resolvePolicyInsightsRunId(
  selectedRunId: string | null | undefined,
  historyItems: RunHistoryItem[] | undefined,
) {
  if (selectedRunId) return selectedRunId;
  return historyItems?.find((item) => item.status === "complete")?.run_id ?? null;
}

function getPreferredRunId(historyItems: RunHistoryItem[] | undefined) {
  if (typeof window === "undefined") return null;
  const fromUrl = new URLSearchParams(window.location.search).get("run");
  const fromStorage = sessionStorage.getItem("polaris-selected-run");
  return resolvePolicyInsightsRunId(fromUrl ?? fromStorage, historyItems);
}

function safeNumber(value: number | null | undefined, fallback = "Not assessed") {
  return value == null || Number.isNaN(value) ? fallback : value;
}

function formatScore(value: number | null | undefined) {
  return value == null || Number.isNaN(value) ? "Not assessed" : `${Math.round(value)} / 100`;
}

function formatPercent(value: number | null | undefined) {
  return value == null || Number.isNaN(value) ? "Not assessed" : `${Math.round(value)}%`;
}

function formatDirection(value: string | null | undefined) {
  if (!value) return "Not assessed";
  const lower = value.toLowerCase();
  if (lower.includes("up") || lower === "positive") return "Positive";
  if (lower.includes("down") || lower === "negative") return "Negative";
  if (lower.includes("mixed") || lower === "neutral") return "Mixed / neutral";
  return value;
}

function buildPerspectiveList(run: Run) {
  const perspectives = [
    {
      id: "economy",
      label: "Economy & Livelihoods",
      impact: run.agents.economic.output?.metric_effects?.reduce((sum, effect) => sum + (effect.direction === "up" ? 1 : effect.direction === "down" ? -1 : 0), 0) ?? null,
      risk: run.agents.economic.output?.confidence ?? null,
      confidence: run.agents.economic.output?.confidence ?? null,
      direction: run.synthesis?.top_3_effects?.[0] ?? null,
      keyFindings: run.agents.economic.output?.reasoning ?? "No specialist insight recorded.",
      concerns: run.agents.economic.output?.metric_effects?.map((effect) => `${effect.metric}: ${effect.direction} (${effect.magnitude})`).join("; ") || "No material concerns recorded.",
    },
    {
      id: "people",
      label: "People & Inclusion",
      impact: run.agents.social.output?.confidence ?? null,
      risk: run.agents.social.output?.confidence ?? null,
      confidence: run.agents.social.output?.confidence ?? null,
      direction: run.agents.social.output?.reasoning ?? null,
      keyFindings: run.agents.social.output?.reasoning ?? "No specialist insight recorded.",
      concerns: run.agents.social.output?.metric_effects?.map((effect) => `${effect.metric}: ${effect.direction} (${effect.magnitude})`).join("; ") || "No material concerns recorded.",
    },
    {
      id: "environment",
      label: "Environment",
      impact: run.agents.environment.output?.confidence ?? null,
      risk: run.agents.environment.output?.confidence ?? null,
      confidence: run.agents.environment.output?.confidence ?? null,
      direction: run.agents.environment.output?.reasoning ?? null,
      keyFindings: run.agents.environment.output?.reasoning ?? "No specialist insight recorded.",
      concerns: run.agents.environment.output?.metric_effects?.map((effect) => `${effect.metric}: ${effect.direction} (${effect.magnitude})`).join("; ") || "No material concerns recorded.",
    },
    {
      id: "delivery",
      label: "Delivery & Public Finance",
      impact: run.agents.legal_budget.output?.confidence ?? null,
      risk: run.agents.legal_budget.output?.confidence ?? null,
      confidence: run.agents.legal_budget.output?.confidence ?? null,
      direction: run.agents.legal_budget.output?.reasoning ?? null,
      keyFindings: run.agents.legal_budget.output?.reasoning ?? "No specialist insight recorded.",
      concerns: run.agents.legal_budget.output?.metric_effects?.map((effect) => `${effect.metric}: ${effect.direction} (${effect.magnitude})`).join("; ") || "No material concerns recorded.",
    },
    {
      id: "legal",
      label: "Legal & Regulatory",
      impact: run.agents.legal_budget.output?.confidence ?? null,
      risk: run.agents.legal_budget.output?.confidence ?? null,
      confidence: run.agents.legal_budget.output?.confidence ?? null,
      direction: run.agents.legal_budget.output?.reasoning ?? null,
      keyFindings: run.agents.legal_budget.output?.reasoning ?? "No specialist insight recorded.",
      concerns: run.agents.legal_budget.output?.metric_effects?.map((effect) => `${effect.metric}: ${effect.direction} (${effect.magnitude})`).join("; ") || "No material concerns recorded.",
    },
    {
      id: "tech",
      label: "Technology & Infrastructure",
      impact: run.agents.environment.output?.confidence ?? null,
      risk: run.agents.environment.output?.confidence ?? null,
      confidence: run.agents.environment.output?.confidence ?? null,
      direction: run.agents.environment.output?.reasoning ?? null,
      keyFindings: run.agents.environment.output?.reasoning ?? "No specialist insight recorded.",
      concerns: run.agents.environment.output?.metric_effects?.map((effect) => `${effect.metric}: ${effect.direction} (${effect.magnitude})`).join("; ") || "No material concerns recorded.",
    },
    {
      id: "risk",
      label: "Risk & Governance",
      impact: run.agents.risk.output?.confidence ?? null,
      risk: run.agents.risk.output?.confidence ?? null,
      confidence: run.agents.risk.output?.confidence ?? null,
      direction: run.agents.risk.output?.risk_level ?? null,
      keyFindings: run.agents.risk.output?.justification ?? "No specialist insight recorded.",
      concerns: run.agents.risk.output?.risk_level ? `Risk level: ${run.agents.risk.output.risk_level}` : "No material concerns recorded.",
    },
  ];

  return perspectives;
}

export const Route = createFileRoute("/policy-insights")({
  component: PolicyInsightsPage,
});

function PolicyInsightsPage() {
  const history = useQuery({ queryKey: ["insights-history"], queryFn: () => getRunHistory(50), retry: false });
  const activeRunId = getPreferredRunId(history.data?.items);
  const selectedRun = useQuery({
    queryKey: ["insights-run", activeRunId],
    queryFn: () => getRun(activeRunId!),
    enabled: Boolean(activeRunId),
    retry: false,
  });

  const run = selectedRun.data;
  const perspectives = useMemo(() => (run ? buildPerspectiveList(run) : []), [run]);

  if (history.isLoading || selectedRun.isLoading) {
    return (
      <main className="workspace-enter mx-auto w-full max-w-7xl px-5 py-9 lg:px-9">
        <div className="panel p-8 text-sm text-muted-foreground">Loading latest policy insight…</div>
      </main>
    );
  }

  if (!run) {
    return (
      <main className="workspace-enter mx-auto w-full max-w-7xl px-5 py-9 lg:px-9">
        <div className="panel p-10 text-center">
          <Sparkles className="mx-auto size-8 text-primary" />
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">No policy insights available</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Complete a policy analysis first to unlock the quantified insight dashboard.
          </p>
          <Link to="/" className="mt-6 inline-flex items-center gap-2 text-sm text-primary">
            Return to the workspace <ArrowRight className="size-4" />
          </Link>
        </div>
      </main>
    );
  }

  const overallImpact = run.synthesis?.overall_impact_score ?? null;
  const riskScore = run.synthesis?.risk_level === "Low" ? 25 : run.synthesis?.risk_level === "Medium" ? 55 : run.synthesis?.risk_level === "High" ? 80 : null;
  const confidence = asPercent(run.synthesis?.confidence) ?? null;

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 text-slate-800 lg:px-6">
      <article className="overflow-hidden rounded-none border border-slate-200 bg-white shadow-[0_0_0_1px_rgba(15,23,42,0.02)]">
        <header className="border-b border-slate-200 bg-slate-50 px-6 py-7 md:px-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500">
                Policy insights
              </div>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900 md:text-4xl">
                {run.policy_input.source_name ?? "Latest policy assessment"}
              </h1>
            </div>
            <Link to="/" className="md:inline-flex">
              <Button variant="outline" size="sm" className="rounded-none border-slate-300 bg-white text-slate-700 shadow-none">
                Back to workspace
              </Button>
            </Link>
          </div>
        </header>

        <section className="grid gap-0 border-b border-slate-200 md:grid-cols-3">
          <SummaryMetric label="Overall impact" value={formatScore(overallImpact)} tone="neutral" />
          <SummaryMetric label="Risk" value={riskScore == null ? "Not assessed" : `${riskScore} / 100`} tone="neutral" />
          <SummaryMetric label="Confidence" value={formatPercent(confidence)} tone="neutral" />
        </section>

        <section className="px-6 py-7 md:px-8">
          <h2 className="text-xl font-semibold text-slate-900">Executive summary</h2>
          <p className="mt-3 max-w-3xl text-[15px] leading-7 text-slate-700">
            {run.synthesis?.verdict ?? "No executive summary is available for this policy yet."}
          </p>
        </section>

        <section className="border-t border-slate-200 px-6 py-7 md:px-8">
          <h2 className="text-xl font-semibold text-slate-900">Assessment by dimension</h2>
          <div className="mt-5 space-y-5">
            {perspectives.map((perspective) => (
              <div key={perspective.id} className="border-b border-slate-200 pb-5 last:border-b-0 last:pb-0">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-lg font-medium text-slate-900">{perspective.label}</h3>
                  <span className="text-xs uppercase tracking-[0.14em] text-slate-500">
                    {perspective.direction ? formatDirection(String(perspective.direction)) : "Not assessed"}
                  </span>
                </div>

                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <MetricRow label="Impact" value={safeNumber((perspective.impact ?? null)) === "Not assessed" ? "Not assessed" : `${safeNumber((perspective.impact ?? null))} / 100`} />
                  <MetricRow label="Risk" value={safeNumber((perspective.risk ?? null)) === "Not assessed" ? "Not assessed" : `${safeNumber((perspective.risk ?? null))} / 100`} />
                  <MetricRow label="Confidence" value={safeNumber((perspective.confidence ?? null)) === "Not assessed" ? "Not assessed" : `${safeNumber((perspective.confidence ?? null))}%`} />
                </div>

                <p className="mt-3 text-[15px] leading-7 text-slate-700">{perspective.keyFindings}</p>
                <p className="mt-2 text-[15px] leading-7 text-slate-600">
                  <span className="font-medium text-slate-800">Concerns:</span> {perspective.concerns}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="border-t border-slate-200 px-6 py-7 md:px-8">
          <h2 className="text-xl font-semibold text-slate-900">Specialist findings</h2>
          <div className="mt-5 space-y-4">
            {Object.entries(run.agents).map(([name, agent]) => (
              <div key={name} className="border-l-2 border-slate-300 pl-4">
                <div className="text-sm font-medium uppercase tracking-[0.12em] text-slate-500">
                  {name.replace(/_/g, " ")}
                </div>
                <p className="mt-2 text-[15px] leading-7 text-slate-700">
                  {agent.output && "reasoning" in agent.output && agent.output.reasoning
                    ? agent.output.reasoning
                    : "Not assessed"}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="border-t border-slate-200 px-6 py-7 md:px-8">
          <h2 className="text-xl font-semibold text-slate-900">Future scenarios</h2>
          <div className="mt-5 space-y-5">
            {(run.scenario_set?.scenarios ?? []).slice(0, 3).map((scenario, index) => (
              <div key={`${scenario.label}-${index}`} className="border-b border-slate-200 pb-5 last:border-b-0 last:pb-0">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-lg font-medium text-slate-900">{scenario.title}</h3>
                  <span className="text-xs uppercase tracking-[0.12em] text-slate-500">{scenario.probability}%</span>
                </div>
                <p className="mt-2 text-[15px] leading-7 text-slate-700">{scenario.body}</p>
                <p className="mt-2 text-[15px] leading-7 text-slate-600">
                  {scenario.probability_rationale ?? "No scenario rationale recorded."}
                </p>
              </div>
            ))}
            {(!run.scenario_set || run.scenario_set.scenarios.length === 0) && (
              <p className="text-[15px] text-slate-600">No scenario data is available for this policy yet.</p>
            )}
          </div>
        </section>

        <section className="border-t border-slate-200 px-6 py-7 md:px-8">
          <div className="grid gap-6 lg:grid-cols-2">
            <div>
              <h2 className="text-xl font-semibold text-slate-900">State / India-level insights</h2>
              {run.state_impact && Object.keys(run.state_impact).length > 0 ? (
                <div className="mt-4 space-y-2">
                  {Object.entries(run.state_impact).map(([state, score]) => (
                    <div key={state} className="flex items-center justify-between border-b border-slate-200 py-2 text-[15px] text-slate-700">
                      <span>{state}</span>
                      <span>{score} / 100</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-[15px] text-slate-600">Not assessed</p>
              )}
            </div>

            <div>
              <h2 className="text-xl font-semibold text-slate-900">Recommended actions</h2>
              <div className="mt-4 space-y-4">
                {(run.recommendations?.recommendations ?? []).map((item, index) => (
                  <div key={`${item.title}-${index}`} className="border-l-2 border-slate-300 pl-4">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-base font-medium text-slate-900">{item.title}</h3>
                      <span className="text-[10px] uppercase tracking-[0.12em] text-slate-500">{item.priority}</span>
                    </div>
                    <p className="mt-2 text-[15px] leading-7 text-slate-700">{item.description}</p>
                    <p className="mt-2 text-[15px] leading-7 text-slate-600">
                      <span className="font-medium text-slate-800">Why:</span> {item.why ?? "Not assessed"}
                    </p>
                  </div>
                ))}
                {(!run.recommendations || run.recommendations.recommendations.length === 0) && (
                  <p className="text-[15px] text-slate-600">Not assessed</p>
                )}
              </div>
            </div>
          </div>
        </section>
      </article>
    </main>
  );
}

function SummaryMetric({ label, value, tone }: { label: string; value: string; tone: "neutral" | "teal" | "amber" | "cyan" | "violet" }) {
  const colors = {
    neutral: "bg-slate-50 text-slate-800 border-slate-200",
    teal: "bg-teal-50 text-teal-800 border-teal-200",
    amber: "bg-amber-50 text-amber-800 border-amber-200",
    cyan: "bg-cyan-50 text-cyan-800 border-cyan-200",
    violet: "bg-violet-50 text-violet-800 border-violet-200",
  };

  return (
    <div className={`border-r border-slate-200 p-4 last:border-r-0 ${colors[tone]}`}>
      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">{value}</div>
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-none border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-slate-800">{value}</div>
    </div>
  );
}
