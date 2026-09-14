import { Skeleton } from "@/components/ui/skeleton";
import type { Run } from "@/lib/polaris-api";

export function VerdictCard({
  synthesis,
  retrievedContext,
}: {
  synthesis: Run["synthesis"];
  retrievedContext: Run["retrieved_context"];
}) {
  return (
    <div className="panel">
      <div className="label-eyebrow">Synthesis</div>
      {synthesis ? (
        <>
          <h2 className="mt-2 text-xl font-semibold leading-snug">{synthesis.verdict}</h2>
          <ul className="mt-4 space-y-2">
            {synthesis.top_3_effects.map((effect, i) => (
              <li key={i} className="flex gap-3 text-sm text-muted-foreground">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                <span>{effect}</span>
              </li>
            ))}
          </ul>
          {retrievedContext.length > 0 && (
            <details className="mt-5 border-t border-border pt-4">
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Retrieved policy evidence ({retrievedContext.length} passages)
              </summary>
              <div className="mt-3 space-y-3">
                {retrievedContext.map((chunk) => (
                  <div key={chunk.chunk_id} className="rounded-lg bg-muted/50 p-3 text-xs">
                    <div className="mb-1 font-semibold text-primary">{chunk.chunk_id}</div>
                    <p className="leading-relaxed text-muted-foreground">{chunk.text}</p>
                  </div>
                ))}
              </div>
            </details>
          )}
        </>
      ) : (
        <div className="mt-3 space-y-3">
          <Skeleton className="h-6 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}
    </div>
  );
}
