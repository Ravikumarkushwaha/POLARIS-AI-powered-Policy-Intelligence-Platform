import { createContext, useContext, useState, type ReactNode } from "react";
import { BookOpen, ExternalLink } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { EvidenceItem, Run, TraceFields } from "@/lib/polaris-api";
import { safeSourceUrl } from "@/lib/report-export";
type Selection = TraceFields & { text: string; catalog?: EvidenceItem[] };
const EvidenceContext = createContext<(selection: Selection) => void>(() => {});
export function EvidenceProvider({ run, children }: { run: Run; children: ReactNode }) {
  const [selected, setSelected] = useState<Selection | null>(null);
  const catalog = selected?.catalog ?? run.evidence_catalog ?? [];
  const linked = catalog.filter((item) => selected?.evidence_ids?.includes(item.evidence_id));
  const conflicts = catalog.filter((item) =>
    selected?.conflicting_evidence_ids?.includes(item.evidence_id),
  );
  const sourceCard = (item: EvidenceItem) => (
    <article key={item.evidence_id} className="rounded-xl border bg-card p-4">
      <div className="flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
        <span>{item.kind === "document" ? "Policy excerpt" : "External evidence"}</span>
        <span>{item.retrieval_status ?? "Status not recorded"}</span>
      </div>
      <h3 className="mt-2 text-sm font-semibold">{item.title}</h3>
      <p className="mt-2 font-mono text-[10px] text-primary">
        {item.evidence_id}
        {item.page != null ? ` · Page ${item.page}` : ""}
        {item.section ? ` · Passage ${item.section}` : ""}
      </p>
      {item.retrieval_status === "link_only" ? (
        <p className="mt-3 text-xs text-muted-foreground">Page content was not retrieved.</p>
      ) : (
        <blockquote className="mt-3 whitespace-pre-wrap border-l-2 border-primary/30 pl-3 text-xs leading-6 text-muted-foreground">
          {item.text}
        </blockquote>
      )}
      {item.published_at && (
        <p className="mt-3 text-[10px] text-muted-foreground">Published: {item.published_at}</p>
      )}
      {item.retrieved_at && (
        <p className="text-[10px] text-muted-foreground">Retrieved: {item.retrieved_at}</p>
      )}
      {item.url && safeSourceUrl(item.url) && (
        <a
          className="mt-3 inline-flex items-center gap-1 text-xs text-primary hover:underline"
          href={safeSourceUrl(item.url)!}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open original source
          <ExternalLink className="size-3" />
        </a>
      )}
    </article>
  );
  return (
    <EvidenceContext.Provider value={setSelected}>
      {children}
      <Sheet
        open={Boolean(selected)}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>Evidence behind this finding</SheetTitle>
            <SheetDescription>
              A source link establishes traceability, not proof that a conclusion is correct.
            </SheetDescription>
          </SheetHeader>
          <div className="mt-6 space-y-5">
            <div className="rounded-xl bg-primary/5 p-4">
              <div className="label-eyebrow">
                {selected?.kind?.replace(/_/g, " ") ?? "AI-generated finding"}
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-7">{selected?.text}</p>
            </div>
            {linked.length ? (
              linked.map(sourceCard)
            ) : (
              <div className="rounded-xl border border-dashed p-5 text-xs leading-6 text-muted-foreground">
                <p className="font-medium text-foreground">No direct supporting evidence linked.</p>
                <p className="mt-2">
                  {!run.citation_version && !selected?.catalog
                    ? "This older analysis has no claim-to-evidence mappings. Sources are available in the Evidence tab, but are not automatically attributed to this finding."
                    : "This may be an inference or an unsupported claim. Check the assumptions and original policy before relying on it."}
                </p>
              </div>
            )}
            <section>
              <h3 className="text-sm font-semibold">Assumptions & uncertainty</h3>
              {selected?.assumptions?.length ? (
                <ul className="mt-3 list-disc space-y-2 pl-4 text-xs leading-6 text-muted-foreground">
                  {selected.assumptions.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-xs text-muted-foreground">
                  No explicit assumptions recorded for this finding.
                </p>
              )}
              <p className="mt-3 text-xs leading-6 text-muted-foreground">
                {selected?.uncertainty ||
                  "No finding-specific uncertainty recorded. Model conclusions are not measured forecasts."}
              </p>
            </section>
            <section>
              <h3 className="mb-3 text-sm font-semibold">Conflicting evidence</h3>
              {conflicts.length ? (
                conflicts.map(sourceCard)
              ) : (
                <p className="text-xs text-muted-foreground">
                  No conflicting evidence was explicitly linked. This does not mean none exists.
                </p>
              )}
            </section>
          </div>
        </SheetContent>
      </Sheet>
    </EvidenceContext.Provider>
  );
}
export function EvidenceButton({
  text,
  trace,
  catalog,
}: {
  text: string;
  trace?: TraceFields | undefined;
  catalog?: EvidenceItem[] | undefined;
}) {
  const open = useContext(EvidenceContext);
  return (
    <button
      type="button"
      onClick={() => open({ text, ...trace, ...(catalog ? { catalog } : {}) })}
      className="mt-3 inline-flex items-center gap-1.5 rounded text-[11px] font-medium text-primary hover:underline"
    >
      <BookOpen className="size-3" />
      View evidence{trace?.evidence_ids?.length ? ` (${trace.evidence_ids.length})` : ""}
    </button>
  );
}
