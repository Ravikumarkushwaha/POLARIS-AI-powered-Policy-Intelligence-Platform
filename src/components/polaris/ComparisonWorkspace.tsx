import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, GitCompareArrows } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getRun, getRunHistory } from "@/lib/polaris-api";
import { asPercent } from "@/lib/report-export";
import { BRIEF_SECTIONS } from "@/lib/brief-sections";
export function ComparisonWorkspace({
  onOpenRun,
  onNewRun,
}: {
  onOpenRun: (id: string) => void;
  onNewRun: () => void;
}) {
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const history = useQuery({
    queryKey: ["comparison-history"],
    queryFn: () => getRunHistory(500),
    retry: false,
  });
  const items = history.data?.items.filter((item) => item.status === "complete") ?? [];
  const a = useQuery({
    queryKey: ["run", left],
    queryFn: () => getRun(left),
    enabled: Boolean(left),
    retry: false,
  });
  const b = useQuery({
    queryKey: ["run", right],
    queryFn: () => getRun(right),
    enabled: Boolean(right),
    retry: false,
  });
  return (
    <main className="workspace-enter mx-auto w-full max-w-7xl space-y-6 px-5 py-9 lg:px-9">
      <div>
        <div className="label-eyebrow flex items-center gap-2">
          <GitCompareArrows className="size-4 text-primary" />
          Compare perspectives
        </div>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">Policies, side by side.</h1>
        <p className="mt-3 text-sm text-muted-foreground">
          Compare saved assessments and their trade-offs. This view makes no AI requests.
        </p>
      </div>
      {history.error && (
        <p className="text-sm text-danger">
          Cannot load saved analyses.{" "}
          <button onClick={() => void history.refetch()} className="underline">
            Retry
          </button>
        </p>
      )}
      {items.length < 2 && !history.isLoading ? (
        <div className="panel py-12 text-center">
          <GitCompareArrows className="mx-auto size-8 text-primary" />
          <h2 className="mt-4 font-semibold">Two perspectives make a comparison.</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Complete at least two policy analyses to compare their findings.
          </p>
          <Button className="mt-5" onClick={onNewRun}>
            New analysis
            <ArrowRight className="size-4" />
          </Button>
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {[
              { label: "Policy A", value: left, set: setLeft, other: right },
              { label: "Policy B", value: right, set: setRight, other: left },
            ].map((control) => (
              <label className="panel block space-y-3 text-xs font-medium" key={control.label}>
                {control.label}
                <select
                  aria-label={control.label}
                  value={control.value}
                  onChange={(e) => control.set(e.target.value)}
                  className="block w-full min-w-0 rounded-lg border bg-background p-3 text-sm"
                >
                  <option value="">Choose a completed analysis</option>
                  {items
                    .filter((item) => item.run_id !== control.other)
                    .map((item) => (
                      <option key={item.run_id} value={item.run_id}>
                        {item.title}
                      </option>
                    ))}
                </select>
              </label>
            ))}
          </div>
          {(a.isLoading || b.isLoading) && (
            <p className="text-sm text-muted-foreground">Loading saved findings…</p>
          )}
          {(a.error || b.error) && (
            <p className="text-sm text-danger">
              Unable to load one of these analyses. Select it again or refresh the page.
            </p>
          )}
          {a.data && b.data && (
            <>
              <div className="grid gap-4 md:grid-cols-2">
                {[a.data, b.data].map((run) => (
                  <section key={run.run_id} className="panel">
                    <h2 className="line-clamp-3 text-base font-semibold">
                      {run.policy_input.source_name ?? run.policy_input.policy_text.slice(0, 160)}
                    </h2>
                    <p className="mt-3 text-sm leading-7 text-muted-foreground">
                      {run.synthesis?.verdict}
                    </p>
                    <dl className="mt-4 grid grid-cols-3 gap-3 border-t pt-4 text-xs">
                      <div>
                        <dt className="text-muted-foreground">Impact index</dt>
                        <dd className="mt-1 text-xl">
                          {run.synthesis?.overall_impact_score ?? "—"}
                          <span className="text-xs"> /100</span>
                        </dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">Risk</dt>
                        <dd className="mt-1 text-lg">{run.synthesis?.risk_level ?? "—"}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">Confidence</dt>
                        <dd className="mt-1 text-lg">
                          {asPercent(run.synthesis?.confidence) ?? "—"}%
                        </dd>
                      </div>
                    </dl>
                    <Button
                      className="mt-5"
                      variant="outline"
                      size="sm"
                      onClick={() => onOpenRun(run.run_id)}
                    >
                      Open full assessment
                      <ArrowRight className="size-3" />
                    </Button>
                  </section>
                ))}
              </div>
              {BRIEF_SECTIONS.map(({ key, label }) => (
                <section key={key} className="overflow-hidden rounded-xl border bg-card">
                  <h2 className="border-b bg-muted/30 px-5 py-3 text-sm font-semibold">{label}</h2>
                  <div className="grid md:grid-cols-2">
                    {[a.data, b.data].map((run) => (
                      <div
                        key={run.run_id}
                        className="space-y-3 p-5 text-sm leading-7 text-muted-foreground"
                      >
                        {run.synthesis?.brief?.[key]?.length ? (
                          run.synthesis.brief[key].map((claim, i) => <p key={i}>{claim.text}</p>)
                        ) : (
                          <p>
                            No structured section recorded in this older run. Open the full
                            assessment for available findings.
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              ))}
              <p className="text-xs leading-6 text-muted-foreground">
                These model-assessed indices are not measured outcomes. Different policies, evidence
                dates, and analysis modes limit direct comparisons; a larger impact score does not
                mean a better policy.
              </p>
            </>
          )}
        </>
      )}
    </main>
  );
}
