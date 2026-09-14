import { BRIEF_SECTIONS } from "@/lib/brief-sections";
import type { Claim, PolicyBrief, Run } from "@/lib/polaris-api";
import { EvidenceButton } from "./EvidenceDrawer";
export function QuickSummary({ run }: { run: Run }) {
  const brief = run.synthesis?.brief;
  const partial: Partial<PolicyBrief> = {
    policy: run.parsed_policy ? [{ text: run.parsed_policy.goals.join(". ") }] : [],
    affected: run.parsed_policy ? [{ text: run.parsed_policy.stakeholders.join(", ") }] : [],
    risks: run.agents.risk.output
      ? [{ text: run.agents.risk.output.justification, ...run.agents.risk.output }]
      : [],
    actions:
      run.recommendations?.recommendations.map((item) => ({
        text: `${item.title}. ${item.description}`,
        ...item,
      })) ?? [],
  };
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {BRIEF_SECTIONS.map(({ key, label }, index) => {
        const claims: Claim[] = brief?.[key] ?? partial[key] ?? [];
        return (
          <section className="rounded-xl border bg-card p-5" key={key}>
            <div className="flex items-center gap-2">
              <span className="font-mono text-[10px] text-primary">0{index + 1}</span>
              <h2 className="text-sm font-semibold">{label}</h2>
            </div>
            {claims.length ? (
              <div className="mt-4 space-y-4">
                {claims.map((claim, i) => (
                  <div key={i}>
                    <p className="text-sm leading-7 text-muted-foreground">{claim.text}</p>
                    <EvidenceButton text={claim.text} trace={claim} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-xs leading-6 text-muted-foreground">
                {run.status === "complete"
                  ? "This saved analysis does not record this summary section. Review the available specialist findings in Analyst detail."
                  : "No completed findings for this section yet."}
              </p>
            )}
          </section>
        );
      })}
    </div>
  );
}
