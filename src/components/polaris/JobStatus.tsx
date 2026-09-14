import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { STATUS_LABELS, isRunActive, type WorkspaceJob } from "@/lib/polaris-api";
export function JobStatus({ job }: { job: WorkspaceJob }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!isRunActive(job.status)) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job.status]);
  const wait = job.telemetry?.wait_until
    ? Math.max(0, Math.ceil((Date.parse(job.telemetry.wait_until) - now) / 1000))
    : 0;
  return (
    <p className="flex items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
      {isRunActive(job.status) && <Loader2 className="size-3 animate-spin" />}
      {wait
        ? `Waiting for the provider rate limit to reset · about ${wait}s`
        : job.runtime?.queue_position
          ? `Queued · position ${job.runtime.queue_position}`
          : STATUS_LABELS[job.status]}
    </p>
  );
}
