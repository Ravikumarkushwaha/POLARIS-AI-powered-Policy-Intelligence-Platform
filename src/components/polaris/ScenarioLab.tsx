import { FlaskConical, Plus, Save, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  cancelJob,
  createScenario,
  deleteScenario,
  getScenarios,
  isRunActive,
  renameScenario,
  retryJob,
  type Run,
} from "@/lib/polaris-api";
import { EvidenceButton } from "./EvidenceDrawer";
import { JobStatus } from "./JobStatus";
import { BRIEF_SECTIONS } from "@/lib/brief-sections";
const CONTROLS = [
  {
    key: "Funding adequacy",
    pattern: /budget|fund|subsid|cost|credit/i,
    options: ["Adequately funded", "Funding constrained", "Funding uncertain"],
  },
  {
    key: "Implementation duration",
    pattern: /year|month|rollout|implement|phase/i,
    options: ["Shorter rollout", "Longer phased rollout", "Delayed implementation"],
  },
  {
    key: "Adoption level",
    pattern: /adopt|particip|household|business|access/i,
    options: ["Higher participation", "Lower participation", "Uneven participation"],
  },
  {
    key: "Administrative capacity",
    pattern: /govern|admin|deliver|implement|public/i,
    options: ["Strong delivery capacity", "Capacity constrained", "Additional staff training"],
  },
];
export function ScenarioLab({ run }: { run: Run }) {
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [assumptions, setAssumptions] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [renaming, setRenaming] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const guard = useRef(false);
  const request = useRef<{ body: string; id: string } | null>(null);
  const qc = useQueryClient();
  const key = ["scenario-lab", run.run_id];
  const variants = useQuery({
    queryKey: key,
    queryFn: () => getScenarios(run.run_id),
    refetchInterval: (q) =>
      q.state.data?.items.some((item) => isRunActive(item.status)) ? 3500 : false,
    retry: false,
  });
  const jobs = variants.data?.items ?? [];
  const current = jobs.find((job) => job.run_id === selected);
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const act = async (action: () => Promise<unknown>) => {
    if (guard.current) return;
    guard.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scenario request failed");
    } finally {
      guard.current = false;
      setBusy(false);
    }
  };
  const create = () =>
    act(async () => {
      const body = JSON.stringify({ title, notes, assumptions });
      if (request.current?.body !== body) request.current = { body, id: crypto.randomUUID() };
      const job = await createScenario(
        run.run_id,
        title.trim() || "New assumption scenario",
        Object.fromEntries(Object.entries(assumptions).filter(([, v]) => v)),
        notes,
        request.current.id,
      );
      request.current = null;
      setSelected(job.run_id);
      setRenaming(job.title ?? "");
      toast("Scenario queued. Your original analysis stays unchanged.");
    });
  return (
    <section className="space-y-5">
      <div className="flex items-start gap-3">
        <span className="rounded-lg bg-primary/10 p-2 text-primary">
          <FlaskConical className="size-5" />
        </span>
        <div>
          <h2 className="text-xl font-semibold">What if?</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Assumption-based reanalysis · explore alternatives using the saved evidence
          </p>
        </div>
      </div>
      <div className="grid items-start gap-5 lg:grid-cols-[1fr_1.2fr]">
        <form
          className="panel space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <div>
            <h3 className="text-sm font-semibold">Baseline assumptions</h3>
            <p className="mt-2 text-xs leading-6 text-muted-foreground">
              {run.parsed_policy?.known_assumptions?.length
                ? run.parsed_policy.known_assumptions.join(" · ")
                : "No explicit baseline assumptions recorded. Values below describe your hypotheses, not facts about the policy."}
            </p>
            {run.parsed_policy?.timeline_years != null && (
              <p className="mt-2 text-xs text-muted-foreground">
                Extracted policy horizon: {run.parsed_policy.timeline_years} years
              </p>
            )}
          </div>
          <div>
            <label htmlFor="variant-title" className="text-xs font-medium">
              Scenario name
            </label>
            <Input
              id="variant-title"
              value={title}
              maxLength={100}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="For example, phased delivery"
              className="mt-2"
            />
          </div>
          {CONTROLS.filter((control) => control.pattern.test(run.policy_input.policy_text)).map(
            (control) => (
              <div key={control.key}>
                <label htmlFor={control.key} className="text-xs font-medium">
                  {control.key}
                </label>
                <select
                  id={control.key}
                  value={assumptions[control.key] ?? ""}
                  onChange={(e) =>
                    setAssumptions({ ...assumptions, [control.key]: e.target.value })
                  }
                  className="mt-2 h-10 w-full rounded-lg border bg-background px-3 text-xs"
                >
                  <option value="">No changed assumption</option>
                  {control.options.map((option) => (
                    <option key={option}>{option}</option>
                  ))}
                </select>
              </div>
            ),
          )}
          <div>
            <label htmlFor="scenario-notes" className="text-xs font-medium">
              Additional assumptions or geographic scope
            </label>
            <Textarea
              id="scenario-notes"
              value={notes}
              maxLength={2500}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Describe what changes and why. For example, begin with a district pilot before expansion."
              className="mt-2 min-h-24 text-sm"
            />
          </div>
          <p className="text-[10px] leading-5 text-muted-foreground">
            An AI assessment of changed assumptions, not a validated economic simulation. No calls
            are made until you run a scenario.
          </p>
          {error && (
            <p role="alert" className="text-xs text-danger">
              {error}
            </p>
          )}
          <Button
            type="submit"
            disabled={
              busy ||
              !run.parsed_policy ||
              (!notes.trim() && !Object.values(assumptions).some(Boolean))
            }
          >
            <Plus className="size-4" />
            {busy ? "Saving…" : "Run scenario"}
          </Button>
        </form>
        <div className="space-y-3">
          <h3 className="text-sm font-semibold">Saved variants</h3>
          {variants.error && (
            <button
              className="text-xs text-danger underline"
              onClick={() => void variants.refetch()}
            >
              Could not load variants. Retry
            </button>
          )}
          {!jobs.length && (
            <div className="rounded-xl border border-dashed p-8 text-center text-xs leading-6 text-muted-foreground">
              {variants.isLoading
                ? "Loading saved variants…"
                : "No variants yet. Change an assumption and run your first scenario."}
            </div>
          )}
          {jobs.map((job) => (
            <button
              key={job.run_id}
              onClick={() => {
                setSelected(job.run_id);
                setRenaming(job.title ?? "");
              }}
              className={`w-full rounded-xl border p-4 text-left transition ${job.run_id === selected ? "border-primary/50 bg-primary/5" : "bg-card hover:bg-muted/30"}`}
            >
              <h4 className="mb-2 text-sm font-medium">{job.title}</h4>
              <JobStatus job={job} />
            </button>
          ))}
        </div>
      </div>
      {current && (
        <div className="panel space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex max-w-full items-center gap-2">
              <Input
                aria-label="Rename scenario"
                value={renaming}
                maxLength={100}
                onChange={(e) => setRenaming(e.target.value)}
                className="max-w-64"
              />
              <Button
                size="icon"
                variant="outline"
                aria-label="Save scenario name"
                disabled={busy || !renaming.trim()}
                onClick={() => void act(() => renameScenario(current.run_id, renaming))}
              >
                <Save className="size-4" />
              </Button>
            </div>
            <div className="flex gap-2">
              {isRunActive(current.status) ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void act(() => cancelJob(current.run_id))}
                >
                  Cancel scenario
                </Button>
              ) : (
                current.status !== "complete" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void act(() => retryJob(current.run_id))}
                  >
                    Retry
                  </Button>
                )
              )}
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    await deleteScenario(current.run_id);
                    setSelected(null);
                  })
                }
              >
                <Trash2 className="size-3.5" />
                Delete variant
              </Button>
            </div>
          </div>
          <JobStatus job={current} />
          {current.error && (
            <p role="alert" className="text-xs text-danger">
              {current.error}
            </p>
          )}
          <div className="rounded-lg bg-muted/50 p-3 text-xs leading-6">
            <span className="font-semibold">Changed user assumptions: </span>
            {Object.entries(current.assumptions ?? {})
              .map(([k, v]) => `${k}: ${v}`)
              .join(" · ")}
            {current.notes && <p>{current.notes}</p>}
          </div>
          {current.baseline_status && current.baseline_status !== "complete" && (
            <p className="text-xs text-warning">
              The baseline used partial findings when this variant was processed.
            </p>
          )}
          {current.output && (
            <>
              <p className="text-sm leading-7">{current.output.summary}</p>
              <div className="space-y-4">
                {current.output.changes?.map((change, i) => (
                  <article key={i} className="overflow-hidden rounded-xl border">
                    <div className="border-b bg-muted/30 px-4 py-2 text-xs font-semibold capitalize">
                      {change.area}
                    </div>
                    <div className="grid md:grid-cols-2">
                      <div className="p-4">
                        <h4 className="label-eyebrow">Original baseline</h4>
                        <p className="mt-2 text-sm leading-7 text-muted-foreground">
                          {change.baseline}
                        </p>
                      </div>
                      <div className="bg-primary/[0.03] p-4">
                        <h4 className="label-eyebrow">Assumption-based variant</h4>
                        <p className="mt-2 text-sm leading-7">{change.revised}</p>
                        <p className="mt-3 text-xs leading-6 text-muted-foreground">
                          <strong>Why it changes: </strong>
                          {change.cause}
                        </p>
                        <EvidenceButton
                          text={change.revised}
                          trace={change}
                          catalog={current.evidence_catalog}
                        />
                      </div>
                    </div>
                  </article>
                ))}
              </div>
              <details className="rounded-lg border p-4">
                <summary className="cursor-pointer text-xs font-medium">
                  Full six-section variant assessment
                </summary>
                <div className="mt-4 space-y-4">
                  {BRIEF_SECTIONS.map(({ key, label }) => (
                    <section key={key}>
                      <h4 className="text-sm font-semibold">{label}</h4>
                      {current.output?.brief?.[key]?.map((claim, i) => (
                        <div key={i}>
                          <p className="mt-2 text-xs leading-6 text-muted-foreground">
                            {claim.text}
                          </p>
                          <EvidenceButton
                            text={claim.text}
                            trace={claim}
                            catalog={current.evidence_catalog}
                          />
                        </div>
                      ))}
                    </section>
                  ))}
                </div>
              </details>
            </>
          )}
        </div>
      )}
    </section>
  );
}
