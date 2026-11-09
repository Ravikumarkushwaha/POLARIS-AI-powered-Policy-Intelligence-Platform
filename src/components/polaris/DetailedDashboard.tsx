import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  CircleDollarSign,
  Download,
  ExternalLink,
  FileText,
  Globe2,
  Info,
  Layers3,
  Leaf,
  ListChecks,
  MapPin,
  Minus,
  Scale,
  Search,
  ShieldAlert,
  Sparkles,
  Users,
} from "lucide-react";
import { useState } from "react";

import { EvidenceButton } from "./EvidenceDrawer";
import { QuickSummary } from "./QuickSummary";
import { useDisplayPreference } from "@/hooks/use-display-preference";
import { StateInsights } from "@/components/polaris/StateInsights";
import { KpiHeader } from "@/components/polaris/KpiHeader";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Run } from "@/lib/polaris-api";
import { asPercent, downloadReport, policyTitle, safeSourceUrl } from "@/lib/report-export";

const AGENT_META = {
  economic: { label: "Economy", icon: CircleDollarSign, tone: "text-sky-500 bg-sky-500/10" },
  environment: { label: "Environment", icon: Leaf, tone: "text-emerald-500 bg-emerald-500/10" },
  social: { label: "Society", icon: Users, tone: "text-violet-500 bg-violet-500/10" },
  legal_budget: { label: "Law & budget", icon: Scale, tone: "text-primary bg-primary/10" },
  risk: { label: "Risk", icon: ShieldAlert, tone: "text-amber-500 bg-amber-500/10" },
} as const;

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-dashed border-border p-7 text-center">
      <Info className="mx-auto h-5 w-5 text-muted-foreground" />
      <h3 className="mt-3 text-sm font-semibold">{title}</h3>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted-foreground">{body}</p>
    </div>
  );
}

function SpecialistFindings({ run }: { run: Run }) {
  return (
    <div className="space-y-3">
      {Object.entries(AGENT_META).map(([name, meta]) => {
        const agent = run.agents?.[name as keyof typeof AGENT_META];
        const output = agent?.output;
        const effects = output && "metric_effects" in output ? output.metric_effects : [];
        const reasoning =
          output && "reasoning" in output
            ? output.reasoning
            : output && "justification" in output
              ? output.justification
              : null;
        const conf = asPercent(
          output?.confidence ??
            (effects.length
              ? effects.reduce((sum, effect) => sum + effect.confidence, 0) / effects.length
              : null),
        );
        const Icon = meta.icon;
        return (
          <details
            key={name}
            className="group rounded-xl border border-border bg-background/35 open:bg-background/60"
          >
            <summary className="flex cursor-pointer list-none items-center gap-3 p-4 [&::-webkit-details-marker]:hidden">
              <span className={`rounded-xl p-2.5 ${meta.tone}`}>
                <Icon className="h-5 w-5" />
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold">{meta.label}</h3>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {agent?.status === "done"
                    ? `${effects.length ? `${effects.length} projected effects · ` : ""}Assessment ready`
                    : agent?.status === "error"
                      ? "Assessment unavailable"
                      : agent?.status === "running"
                        ? "Assessment in progress"
                        : "Awaiting assessment"}
                </p>
              </div>
              {conf != null && (
                <span className="text-xs tabular-nums text-muted-foreground">
                  {conf}%<span className="hidden sm:inline"> confidence</span>
                </span>
              )}
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
            </summary>
            <div className="space-y-4 border-t border-border px-4 pb-5 pt-4">
              <p className="whitespace-pre-wrap text-sm leading-7 text-muted-foreground">
                {reasoning ?? "No findings have been produced by this specialist yet."}
              </p>
              {reasoning && <EvidenceButton text={reasoning} trace={output ?? undefined} />}
              {effects.length > 0 && (
                <div className="grid gap-2 sm:grid-cols-2">
                  {effects.map((effect, index) => {
                    const DirectionIcon =
                      effect.direction === "up"
                        ? ArrowUpRight
                        : effect.direction === "down"
                          ? ArrowDownRight
                          : Minus;
                    return (
                      <div
                        key={`${effect.metric}-${index}`}
                        className="rounded-lg border border-border p-3"
                      >
                        <div className="flex items-center gap-2 text-sm font-medium">
                          <DirectionIcon className="h-4 w-4 shrink-0 text-primary" />
                          {effect.metric}
                        </div>
                        <p className="mt-2 text-xs text-muted-foreground">
                          {effect.direction === "flat"
                            ? "Stable"
                            : effect.direction === "up"
                              ? "Projected increase"
                              : "Projected decrease"}{" "}
                          · {effect.magnitude} effect · {asPercent(effect.confidence)}% confidence
                        </p>
                        <EvidenceButton text={effect.metric} trace={effect} />
                      </div>
                    );
                  })}
                </div>
              )}
              {output && "confidence_rationale" in output && output.confidence_rationale && (
                <p className="text-xs leading-6 text-muted-foreground">
                  Confidence basis: {output.confidence_rationale}
                </p>
              )}
            </div>
          </details>
        );
      })}
    </div>
  );
}

function EvidenceWorkspace({ run }: { run: Run }) {
  const [query, setQuery] = useState("");
  const needle = query.trim().toLocaleLowerCase();
  const chunks = (run.retrieved_context ?? []).filter((chunk) =>
    `${chunk.chunk_id} ${chunk.text}`.toLocaleLowerCase().includes(needle),
  );
  const sources = (run.web_sources ?? []).filter((source) =>
    `${source.title} ${source.source} ${source.text}`.toLocaleLowerCase().includes(needle),
  );
  return (
    <div className="space-y-6">
      <div className="panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="label-eyebrow">Trace the evidence</div>
            <h2 className="mt-2 text-xl font-semibold">Know what informed the analysis</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Policy passages and external excerpts retrieved for this run. Relevance measures
              keyword overlap; it is not a measure of factual accuracy.
            </p>
          </div>
          <label className="flex w-full items-center gap-2 rounded-xl border border-border bg-background px-3 py-2.5 sm:w-64">
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
            <input
              aria-label="Search evidence"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search evidence…"
              className="w-full min-w-0 bg-transparent text-sm outline-none"
            />
          </label>
        </div>
      </div>
      <section>
        <div className="mb-4 flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-primary" />
          <h2 className="font-semibold">Submitted policy</h2>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {chunks.length} passages
          </span>
        </div>
        {chunks.length ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {chunks.map((chunk, index) => (
              <article key={`${chunk.chunk_id}-${index}`} className="panel">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="rounded-md bg-primary/10 px-2 py-1 font-mono text-xs text-primary">
                    {chunk.chunk_id}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {Math.round(chunk.relevance * 100)}% keyword coverage
                  </span>
                </div>
                <p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-muted-foreground">
                  {chunk.text}
                </p>
                <p className="mt-4 border-t border-border pt-3 text-xs text-muted-foreground">
                  Source: policy text submitted for this run
                </p>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title={query ? "No matching policy passages" : "No policy passages available"}
            body={
              query
                ? "Try another keyword or clear your search."
                : "Retrieved passages will appear here when they are available in the saved analysis."
            }
          />
        )}
      </section>
      <section>
        <div className="mb-4 flex items-center gap-2">
          <Globe2 className="h-4 w-4 text-primary" />
          <h2 className="font-semibold">External references</h2>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {sources.length} sources
          </span>
        </div>
        {sources.length ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {sources.map((source, index) => {
              const href = safeSourceUrl(source.url);
              return (
                <article key={`${source.url}-${index}`} className="panel">
                  <div className="label-eyebrow break-words">{source.source}</div>
                  <h3 className="mt-2 font-semibold leading-6">{source.title}</h3>
                  <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-muted-foreground">
                    {source.text}
                  </p>
                  {href && (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-4 inline-flex items-center gap-2 text-xs font-semibold text-primary hover:underline"
                    >
                      Read original source <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyState
            title={query ? "No matching external references" : "No external references recorded"}
            body={
              query
                ? "Try a broader search term."
                : run.policy_input.web_enabled === false
                  ? "Web enrichment was switched off for this run. The analysis uses the submitted policy and configured baseline context."
                  : "This run did not retrieve external pages. Claims that depend on current external facts need independent verification."
            }
          />
        )}
      </section>
      <div className="flex items-start gap-3 rounded-xl border border-border bg-muted/30 p-4 text-xs leading-6 text-muted-foreground">
        <Info className="mt-1 h-4 w-4 shrink-0" />
        <p>
          Use View evidence on findings to inspect validated source IDs. Older runs may not have
          claim-level citation mappings. Geographic analysis can also use illustrative baseline
          data. Check the original sources and official state statistics before using the findings
          in a decision.
        </p>
      </div>
    </div>
  );
}

function ActionWorkspace({ run }: { run: Run }) {
  const [checked, setChecked] = useState<Record<number, boolean>>({});
  const recommendations = run.recommendations?.recommendations ?? [];
  const reviewed = recommendations.filter((_, index) => checked[index]).length;
  return (
    <div className="space-y-5">
      <div className="panel flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="label-eyebrow">From analysis to implementation</div>
          <h2 className="mt-2 text-xl font-semibold">Recommended next steps</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Review the generated actions and their supporting signals. Checkmarks are a temporary
            review aid for this view.
          </p>
        </div>
        {recommendations.length > 0 && (
          <span className="rounded-full bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary">
            {reviewed}/{recommendations.length} reviewed
          </span>
        )}
      </div>
      {recommendations.length ? (
        recommendations.map((item, index) => (
          <article
            key={`${item.title}-${index}`}
            className={`panel transition-opacity ${checked[index] ? "opacity-70" : ""}`}
          >
            <div className="flex items-start gap-4">
              <input
                type="checkbox"
                aria-label={`Mark recommendation ${index + 1} reviewed`}
                checked={checked[index] ?? false}
                onChange={(event) =>
                  setChecked((current) => ({ ...current, [index]: event.target.checked }))
                }
                className="mt-1 h-4 w-4 shrink-0 accent-primary"
              />
              <div className="min-w-0 flex-1">
                <span className="rounded-md bg-primary/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-primary">
                  {item.priority}
                </span>
                <h3 className="mt-3 text-lg font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-7 text-muted-foreground">{item.description}</p>
                <EvidenceButton text={item.description} trace={item} />
                {item.why && (
                  <div className="mt-4 rounded-xl bg-muted/45 p-4">
                    <div className="label-eyebrow">Why this matters</div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.why}</p>
                  </div>
                )}
                {item.supporting_signals.length > 0 && (
                  <ul className="mt-4 space-y-2">
                    {item.supporting_signals.map((signal, signalIndex) => (
                      <li
                        key={signalIndex}
                        className="flex items-start gap-2 text-xs leading-6 text-muted-foreground"
                      >
                        <ArrowRight className="mt-1 h-3.5 w-3.5 shrink-0 text-primary" />
                        {signal}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </article>
        ))
      ) : (
        <EmptyState
          title="No recommendations available yet"
          body="Only recommendations produced by the analysis will appear here. You can still review the completed specialist findings in Overview."
        />
      )}
    </div>
  );
}

export function DetailedDashboard({ run }: { run: Run }) {
  const [detail, setDetail] = useDisplayPreference();
  const synthesis = run.synthesis;
  const parsed = run.parsed_policy;
  const scenarios = run.scenario_set?.scenarios ?? [];
  const effects = synthesis?.top_3_effects ?? [];
  return (
    <main className="workspace-enter min-w-0 flex-1 px-4 py-6 text-foreground sm:px-7 lg:px-9">
      <div className="mx-auto max-w-[1440px] space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 max-w-3xl">
            <div className="label-eyebrow flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" /> Policy intelligence{" "}
              <span className="text-muted-foreground/50">/</span> {run.run_id.slice(0, 8)}
            </div>
            <h1 className="hero-title mt-3 text-2xl font-semibold leading-tight tracking-[-0.035em] sm:text-3xl">
              {policyTitle(run.policy_input.policy_text)}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="rounded-full border border-border bg-card px-2.5 py-1">
                {parsed?.domain ?? "Classification pending"}
              </span>
              <span className="rounded-full border border-border bg-card px-2.5 py-1">
                {run.status === "complete"
                  ? "Completed analysis"
                  : run.status === "error"
                    ? "Partial analysis"
                    : "Analysis in progress"}
              </span>
              <span>
                {run.retrieved_context?.length ?? 0} policy passages ·{" "}
                {run.web_sources?.length ?? 0} web references
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm">
                  <Download />
                  Export
                  <ChevronDown />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => downloadReport(run, "text")}>
                  Readable report (.txt)
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => downloadReport(run, "json")}>
                  Complete analysis (.json)
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => downloadReport(run, "csv")}>
                  Metrics & actions (.csv)
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        <Tabs defaultValue="overview" className="space-y-6">
          <TabsList className="sticky top-[70px] z-20 h-auto w-full justify-start gap-1 overflow-x-auto rounded-2xl border border-border/70 bg-card/70 p-1.5 shadow-[0_18px_50px_-38px_rgba(0,0,0,.7)] backdrop-blur-xl">
            <TabsTrigger
              value="overview"
              className="gap-2 rounded-xl px-4 py-2.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary"
            >
              <Layers3 className="h-4 w-4" />
              Overview
            </TabsTrigger>
            <TabsTrigger
              value="evidence"
              className="gap-2 rounded-xl px-4 py-2.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary"
            >
              <BookOpen className="h-4 w-4" />
              Evidence
            </TabsTrigger>
            <TabsTrigger
              value="states"
              className="gap-2 rounded-xl px-4 py-2.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary"
            >
              <MapPin className="h-4 w-4" />
              State insights
            </TabsTrigger>
            <TabsTrigger
              value="actions"
              className="gap-2 rounded-xl px-4 py-2.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary"
            >
              <ListChecks className="h-4 w-4" />
              Actions
            </TabsTrigger>
          </TabsList>
          <TabsContent value="overview" className="space-y-6">
            <div
              className="segmented-glass flex w-fit gap-1 rounded-xl p-1"
              aria-label="Reading depth"
            >
              <Button
                size="sm"
                variant={detail ? "ghost" : "secondary"}
                aria-pressed={!detail}
                onClick={() => setDetail(false)}
              >
                Quick summary
              </Button>
              <Button
                size="sm"
                variant={detail ? "secondary" : "ghost"}
                aria-pressed={detail}
                onClick={() => setDetail(true)}
              >
                Analyst detail
              </Button>
            </div>
            {detail ? (
              <>
                <KpiHeader synthesis={synthesis} />
                <div className="grid items-start gap-5 xl:grid-cols-[1.12fr_1fr]">
                  <section className="panel relative overflow-hidden">
                    <div className="absolute -right-8 -top-10 h-40 w-40 rounded-full bg-primary/5 blur-2xl" />
                    <div className="label-eyebrow flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-primary" />
                      Executive assessment
                    </div>
                    {synthesis ? (
                      <>
                        <h2 className="relative mt-4 text-xl font-semibold leading-8">
                          {synthesis.verdict}
                        </h2>
                        <EvidenceButton text={synthesis.verdict} trace={synthesis} />
                        {effects.length > 0 && (
                          <ol className="mt-6 space-y-4">
                            {effects.map((effect, index) => (
                              <li key={index} className="flex gap-3">
                                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 font-mono text-xs text-primary">
                                  0{index + 1}
                                </span>
                                <p className="text-sm leading-6 text-muted-foreground">{effect}</p>
                              </li>
                            ))}
                          </ol>
                        )}
                        {synthesis.impact_score_rationale && (
                          <p className="mt-5 border-t border-border pt-4 text-xs leading-6 text-muted-foreground">
                            <span className="font-semibold text-foreground">
                              Impact rationale:{" "}
                            </span>
                            {synthesis.impact_score_rationale}
                          </p>
                        )}
                        <details className="mt-5 border-t border-border pt-4">
                          <summary className="cursor-pointer text-xs font-medium text-primary">
                            How to interpret these scores
                          </summary>
                          <div className="mt-3 space-y-2 text-xs leading-6 text-muted-foreground">
                            <p>
                              Impact and confidence are estimates from the model. Confidence is not
                              a verified probability of correctness.
                            </p>
                            {synthesis.confidence_basis && (
                              <>
                                <p>{synthesis.confidence_basis.note}</p>
                                <p className="break-words font-mono">
                                  {synthesis.confidence_basis.formula}
                                </p>
                                {Object.entries(synthesis.confidence_basis.components).map(
                                  ([name, value]) => (
                                    <div key={name} className="flex justify-between">
                                      <span className="capitalize">{name.replace(/_/g, " ")}</span>
                                      <span>{asPercent(value)}%</span>
                                    </div>
                                  ),
                                )}
                              </>
                            )}
                          </div>
                        </details>
                      </>
                    ) : (
                      <div className="mt-5">
                        <EmptyState
                          title="Executive assessment is not available yet"
                          body="Specialist findings appear as they arrive. The final synthesis will bring those findings together here."
                        />
                      </div>
                    )}
                  </section>
                  <section className="panel">
                    <div className="mb-5 flex items-center justify-between gap-3">
                      <div>
                        <div className="label-eyebrow">Multiple perspectives</div>
                        <h2 className="mt-2 text-lg font-semibold">Specialist findings</h2>
                      </div>
                      <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                        {
                          Object.values(run.agents ?? {}).filter((agent) => agent.status === "done")
                            .length
                        }
                        /5 ready
                      </span>
                    </div>
                    <SpecialistFindings run={run} />
                  </section>
                </div>
                <section>
                  <div className="mb-4 flex items-center justify-between gap-3">
                    <h2 className="text-lg font-semibold">Possible futures</h2>
                    <span className="text-xs text-muted-foreground">Model-estimated scenarios</span>
                  </div>
                  {scenarios.length ? (
                    <div className="grid gap-4 lg:grid-cols-3">
                      {scenarios.map((scenario, index) => (
                        <article key={`${scenario.label}-${index}`} className="panel metric-glow">
                          <div className="flex items-start justify-between gap-3">
                            <span className="label-eyebrow">{scenario.label}</span>
                            <div className="text-right">
                              <span className="text-2xl font-semibold tabular-nums text-primary">
                                {scenario.probability}%
                              </span>
                              <p className="text-[10px] text-muted-foreground">
                                estimated likelihood
                              </p>
                            </div>
                          </div>
                          <h3 className="mt-4 font-semibold leading-6">{scenario.title}</h3>
                          <p className="mt-3 text-sm leading-6 text-muted-foreground">
                            {scenario.body}
                          </p>
                          <EvidenceButton text={scenario.body} trace={scenario} />
                          <ul className="mt-4 space-y-2">
                            {scenario.points.map((point, pointIndex) => (
                              <li
                                key={pointIndex}
                                className="flex gap-2 text-xs leading-6 text-muted-foreground"
                              >
                                <span className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                                {point}
                              </li>
                            ))}
                          </ul>
                          <p className="mt-4 border-t border-border pt-4 text-xs leading-6 text-muted-foreground">
                            {scenario.probability_rationale
                              ? `Likelihood basis: ${scenario.probability_rationale}`
                              : "No probability rationale recorded. Treat this estimate cautiously."}
                          </p>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <EmptyState
                      title="No scenarios available yet"
                      body="Scenario assessments will appear when they have been generated for this run."
                    />
                  )}
                </section>
                <details className="panel">
                  <summary className="flex cursor-pointer items-center gap-2 text-sm font-semibold">
                    <FileText className="h-4 w-4 text-primary" />
                    Policy scope & original input
                  </summary>
                  <div className="mt-5 space-y-4">
                    {parsed && (
                      <div className="grid gap-4 text-sm sm:grid-cols-2">
                        <div>
                          <div className="label-eyebrow">Goals</div>
                          <p className="mt-2 leading-6 text-muted-foreground">
                            {parsed.goals.join(" · ") || "No goals extracted"}
                          </p>
                        </div>
                        <div>
                          <div className="label-eyebrow">Stakeholders</div>
                          <p className="mt-2 leading-6 text-muted-foreground">
                            {parsed.stakeholders.join(" · ") || "No stakeholders extracted"}
                          </p>
                        </div>
                        <div>
                          <div className="label-eyebrow">Affected sectors</div>
                          <p className="mt-2 leading-6 text-muted-foreground">
                            {parsed.affected_sectors.join(" · ") || "No sectors extracted"}
                          </p>
                        </div>
                        <div>
                          <div className="label-eyebrow">Analysis horizon</div>
                          <p className="mt-2 text-muted-foreground">
                            {parsed.timeline_years != null
                              ? `${parsed.timeline_years} years`
                              : "Not specified"}
                          </p>
                        </div>
                      </div>
                    )}
                    <p className="max-h-80 overflow-y-auto whitespace-pre-wrap rounded-xl bg-background/60 p-4 text-sm leading-7 text-muted-foreground">
                      {run.policy_input.policy_text}
                    </p>
                  </div>
                </details>
              </>
            ) : (
              <QuickSummary run={run} />
            )}
          </TabsContent>
          <TabsContent value="evidence">
            <EvidenceWorkspace run={run} />
          </TabsContent>
          <TabsContent value="states">
            <StateInsights run={run} />
          </TabsContent>
          <TabsContent value="actions">
            <ActionWorkspace key={run.run_id} run={run} />
          </TabsContent>
        </Tabs>
        <p className="flex items-start gap-2 pb-3 text-xs leading-6 text-muted-foreground">
          <Info className="mt-1 h-3.5 w-3.5 shrink-0" />
          AI-generated decision support. Review source evidence, assumptions, and local conditions
          before acting.
        </p>
      </div>
    </main>
  );
}
