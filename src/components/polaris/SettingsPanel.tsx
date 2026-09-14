import { Database, Globe2, Server, ShieldCheck } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import type { RuntimeStatus } from "@/lib/polaris-api";
export function SettingsPanel({
  webEnabled,
  onWebEnabledChange,
  onClose,
  runtime,
  online,
}: {
  webEnabled: boolean;
  onWebEnabledChange: (value: boolean) => void;
  onClose: () => void;
  runtime: RuntimeStatus | undefined;
  online: boolean | null;
}) {
  const quota = runtime?.quota;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Preferences & system</DialogTitle>
          <DialogDescription>
            Control evidence collection and inspect your analysis budget.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-5 pt-3">
          <div className="flex items-start justify-between gap-4 rounded-xl border p-4">
            <div>
              <label htmlFor="settings-web" className="flex items-center gap-2 text-sm font-medium">
                <Globe2 className="size-4 text-primary" />
                Web research
              </label>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                Include external sources with new analyses. Turn this off to use only your policy
                document.
              </p>
            </div>
            <Switch id="settings-web" checked={webEnabled} onCheckedChange={onWebEnabledChange} />
          </div>
          <div className="rounded-xl border p-4">
            <h3 className="flex items-center gap-2 text-sm font-medium">
              <Server className="size-4 text-primary" />
              Analysis server
            </h3>
            <p className="mt-2 text-xs text-muted-foreground">
              {online === null
                ? "Checking connection…"
                : !online
                  ? "Offline. Start the backend to analyze policies or load saved runs."
                  : runtime?.configured
                    ? "Connected · Groq API key configured"
                    : "Connected · configure GROQ_API_KEY in backend/.env"}
            </p>
            {runtime && (
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="text-lg font-semibold">{runtime.queue.queued_runs}</div>
                  <div className="text-[10px] text-muted-foreground">Queued analyses</div>
                </div>
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="text-lg font-semibold">
                    {runtime.queue.active_run_id ? "1" : "0"}
                  </div>
                  <div className="text-[10px] text-muted-foreground">Running analysis</div>
                </div>
              </div>
            )}
          </div>
          {quota && (
            <div className="rounded-xl border p-4">
              <h3 className="flex items-center gap-2 text-sm font-medium">
                <ShieldCheck className="size-4 text-primary" />
                Configured quota protection
              </h3>
              <dl className="mt-3 space-y-2 text-xs">
                {[
                  ["Token limit / minute", quota["tokens_per_minute"]],
                  ["Safe tokens / window", quota["safe_tokens_per_window"]],
                  ["Maximum request tokens", quota["max_request_tokens"]],
                  ["Window length (seconds)", quota["window_seconds"]],
                  ["Shared requests / minute", quota["requests_per_minute"]],
                  ["Provider requests / minute", quota["provider_requests_per_minute"]],
                  ["Currently reserved tokens", quota["reserved_tokens"]],
                ].map(([label, value]) => (
                  <div key={String(label)} className="flex justify-between gap-3">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="font-mono">{value == null ? "—" : String(value)}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-3 text-[10px] leading-5 text-muted-foreground">
                Local reservations are estimates, not your provider account balance. Provider
                cooldowns are also respected.
              </p>
            </div>
          )}
          <div className="rounded-xl border p-4">
            <h3 className="flex items-center gap-2 text-sm font-medium">
              <Database className="size-4 text-primary" />
              Result reuse
            </h3>
            <p className="mt-2 text-xs leading-6 text-muted-foreground">
              Identical completed analyses are reused for{" "}
              {Math.round((runtime?.cache.web_ttl_seconds ?? 3600) / 3600)} hour with web research,
              or {Math.round((runtime?.cache.document_ttl_seconds ?? 86400) / 3600)} hours with
              document evidence only. Use the refresh option in a new analysis when you need a fresh
              assessment.
            </p>
            <p className="mt-2 text-[10px] text-muted-foreground">
              Draft text and theme are saved in this browser. Analysis history is stored in your
              backend workspace.
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
