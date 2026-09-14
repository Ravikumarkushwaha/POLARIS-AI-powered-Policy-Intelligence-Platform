import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, MapPin, Search, Sparkles, BookOpen, Layers3 } from "lucide-react";
import { IndiaMap } from "./IndiaMap";
import { normalizeState } from "@/lib/state-geography";
import { EvidenceButton } from "./EvidenceDrawer";
import { Button } from "@/components/ui/button";
import { askPolaris, getChat, isRunActive, retryJob, type Run } from "@/lib/polaris-api";
import geo from "@/data/india-states.geo.json";

const DOMAINS = [
  ["economic", "Economy & livelihoods"],
  ["social", "People & inclusion"],
  ["environment", "Environment"],
  ["legal_budget", "Delivery & public finance"],
] as const;
function weight(values: Record<string, number> | undefined | null, name: string) {
  const value = Object.entries(values ?? {}).find(
    ([key]) => normalizeState(key) === normalizeState(name),
  )?.[1];
  return value != null && Number.isFinite(value) ? value : null;
}
export function StateInsights({ run }: { run: Run }) {
  const states = geo.features
    .map((f) => f.properties.name)
    .sort(
      (a, b) =>
        (weight(run.state_impact, b) ?? -1) - (weight(run.state_impact, a) ?? -1) ||
        a.localeCompare(b),
    );
  const [selected, setSelected] = useState(states[0] ?? "Uttar Pradesh");
  const [query, setQuery] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const guard = useRef(false);
  const qc = useQueryClient();
  const history = useQuery({
    queryKey: ["chat", run.run_id],
    queryFn: () => getChat(run.run_id),
    retry: false,
    refetchInterval: (q) => (q.state.data?.items.some((j) => isRunActive(j.status)) ? 3500 : false),
  });
  const question = `State dossier: ${selected}. Return a concise five-point state brief from the selected state's saved weights, metrics, risks, and evidence.`;
  const dossier = history.data?.items.find((j) => j.question === question);
  const busy = history.data?.items.some((j) => isRunActive(j.status));
  const generate = async () => {
    if (guard.current || busy) return;
    guard.current = true;
    setSending(true);
    setError(null);
    try {
      if (dossier && (dossier.status === "error" || dossier.status === "cancelled"))
        await retryJob(dossier.run_id);
      else await askPolaris(run.run_id, question, `state-dossier-v2-${normalizeState(selected)}`);
      await qc.invalidateQueries({ queryKey: ["chat", run.run_id] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not queue state analysis");
    } finally {
      guard.current = false;
      setSending(false);
    }
  };
  const score = weight(run.state_impact, selected);
  const aliases = [
    selected,
    ...Object.keys(run.state_impact ?? {}).filter(
      (n) => normalizeState(n) === normalizeState(selected),
    ),
  ];
  const mentions = (run.evidence_catalog ?? []).filter(
    (e) =>
      e.retrieval_status !== "link_only" &&
      aliases.some((n) => `${e.title} ${e.text}`.toLowerCase().includes(n.toLowerCase())),
  );
  return (
    <div className="space-y-5">
      <section className="relative overflow-hidden rounded-2xl border border-primary/20 bg-gradient-to-br from-slate-950 via-slate-900 to-teal-950 p-6 text-white lg:p-8">
        <div className="pointer-events-none absolute -right-10 -top-20 size-72 rounded-full border-[40px] border-teal-400/10" />
        <div className="relative">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-[.2em] text-teal-300">
            <Layers3 className="size-4" /> Regional intelligence
          </div>
          <h2 className="mt-3 text-2xl font-semibold tracking-tight lg:text-3xl">
            One policy. Different local realities.
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
            Explore all 36 states and union territories. Select a region for domain findings, source
            coverage and a focused policy dossier.
          </p>
          <div className="mt-5 flex flex-wrap gap-3 text-xs">
            <span className="rounded-full border border-white/15 bg-white/5 px-3 py-2">
              36 regions
            </span>
            <span className="rounded-full border border-white/15 bg-white/5 px-3 py-2">
              4 analytical lenses
            </span>
            <span className="rounded-full border border-teal-400/20 bg-teal-400/10 px-3 py-2 text-teal-200">
              Browsing uses no AI requests
            </span>
          </div>
        </div>
      </section>
      <div className="grid items-start gap-5 xl:grid-cols-[1.05fr_1fr]">
        <div className="space-y-4">
          <IndiaMap stateImpact={run.state_impact} selected={selected} onSelect={setSelected} />
          <section className="panel">
            <label className="flex items-center gap-2 rounded-xl border bg-background px-3 py-2">
              <Search className="size-4 text-muted-foreground" />
              <input
                className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                aria-label="Find a state"
                placeholder="Find a state or union territory"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <div className="mt-3 grid max-h-60 grid-cols-1 gap-1 overflow-y-auto sm:grid-cols-2">
              {states
                .filter((n) => n.toLowerCase().includes(query.toLowerCase()))
                .map((n) => (
                  <button
                    key={n}
                    onClick={() => setSelected(n)}
                    aria-pressed={n === selected}
                    className={`flex items-center justify-between gap-2 rounded-lg px-3 py-2.5 text-left text-xs ${n === selected ? "bg-primary/10 font-semibold text-primary" : "hover:bg-muted"}`}
                  >
                    <span>{n}</span>
                    <span className="shrink-0 font-mono text-[10px]">
                      {weight(run.state_impact, n)?.toFixed(1) ?? "—"}
                    </span>
                  </button>
                ))}
            </div>
          </section>
        </div>
        <div className="space-y-4" aria-live="polite">
          <section className="panel border-primary/20">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="label-eyebrow flex items-center gap-1">
                  <MapPin className="size-3" /> Selected region
                </div>
                <h3 className="mt-2 text-2xl font-semibold">{selected}</h3>
              </div>
              <span className="rounded-xl bg-primary/10 p-3 font-mono text-xl text-primary">
                {score?.toFixed(1) ?? "—"}
                <span className="block text-center text-[9px] uppercase">Exposure</span>
              </span>
            </div>
            <p className="mt-3 text-xs leading-6 text-muted-foreground">
              Relative model weight, not an observed outcome or a benefit score. No estimate is
              assigned where this run has no regional assessment.
            </p>
            <div className="mt-4 flex items-center gap-2 rounded-xl bg-muted/60 p-3 text-xs">
              <BookOpen className="size-4 shrink-0 text-primary" />
              {mentions.length
                ? `${mentions.length} saved source passages mention this region.`
                : "No saved source passage names this region. Local effects need verification."}
            </div>
          </section>
          <section className="panel">
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-primary" />
              <h3 className="font-semibold">State policy dossier</h3>
            </div>
            {dossier?.output?.answer ? (
              <>
                {dossier.output.partial_findings && (
                  <p className="mt-3 rounded-lg bg-warning/10 p-3 text-xs">
                    This dossier was generated from an incomplete baseline analysis.
                  </p>
                )}
                <div className="mt-4 space-y-3 text-sm leading-7">
                  {dossier.output.answer.split(/\n\s*\n/).map((block, index) => {
                    const lines = block.split("\n");
                    const heading = /^#{1,6}\s/.test(lines[0] ?? "")
                      ? lines.shift()?.replace(/^#{1,6}\s+/, "")
                      : null;
                    return (
                      <div key={index}>
                        {heading && (
                          <h4 className="mt-5 font-semibold text-foreground">{heading}</h4>
                        )}
                        <p className="whitespace-pre-wrap text-muted-foreground">
                          {lines.join("\n")}
                        </p>
                      </div>
                    );
                  })}
                </div>
                <EvidenceButton
                  text={dossier.output.answer}
                  trace={dossier.output}
                  catalog={dossier.evidence_catalog}
                />
              </>
            ) : (
              <>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">
                  Explore rural and urban applicability, affected groups, implementation risks,
                  state actions and monitoring needs. Grounded in this run's saved evidence.
                </p>
                <Button
                  className="mt-4"
                  onClick={() => void generate()}
                  disabled={sending || !!busy || history.isLoading || !!history.error}
                >
                  {sending
                    ? "Queuing..."
                    : dossier && isRunActive(dossier.status)
                      ? "Dossier queued / analyzing"
                      : dossier
                        ? "Retry state dossier"
                        : "Generate state dossier"}
                  <ArrowUpRight className="size-4" />
                </Button>
                <p className="mt-2 text-[10px] leading-5 text-muted-foreground">
                  Uses one compact AI request grounded in this state's saved findings.
                </p>
              </>
            )}
            {(error || dossier?.error || history.error) && (
              <p role="alert" className="mt-3 text-xs text-danger">
                {error ??
                  dossier?.error ??
                  "Could not load saved dossiers. Please reload this view."}
              </p>
            )}
          </section>
          <div className="grid gap-3 sm:grid-cols-2">
            {DOMAINS.map(([key, label]) => {
              const output = run.agents[key].output;
              const share = weight(output?.affected_states_weight, selected);
              return (
                <article className="panel !p-4" key={key}>
                  <div className="text-xs font-semibold">{label}</div>
                  <div className="mt-2 text-lg font-semibold text-primary">
                    {share == null ? "Not assessed" : `${share.toFixed(1)} weight`}
                  </div>
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    {share == null
                      ? "No regional weight recorded"
                      : "Domain model weight; not measured impact"}
                  </p>
                  <details className="mt-3">
                    <summary className="cursor-pointer text-xs text-primary">
                      Read national context
                    </summary>
                    <p className="mt-3 text-xs leading-6 text-muted-foreground">
                      {output?.reasoning ?? "This domain has not completed."}
                    </p>
                    {output?.metric_effects.map((m, i) => (
                      <div key={i} className="mt-2 rounded-lg bg-muted/50 p-2 text-xs">
                        {m.metric} · {m.direction} · {m.magnitude}
                        <EvidenceButton text={m.metric} trace={m} />
                      </div>
                    ))}
                  </details>
                </article>
              );
            })}
          </div>
          {mentions.length > 0 && (
            <section className="panel">
              <h3 className="font-semibold">Regional source mentions</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                A mention alone does not establish a local policy effect.
              </p>
              {mentions.map((e) => (
                <article key={e.evidence_id} className="mt-4 border-t pt-3">
                  <h4 className="text-sm font-medium">{e.title}</h4>
                  <p className="mt-2 line-clamp-3 text-xs leading-6 text-muted-foreground">
                    {e.text}
                  </p>
                  <EvidenceButton text={e.title} trace={{ evidence_ids: [e.evidence_id] }} />
                </article>
              ))}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
