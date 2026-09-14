import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock3,
  FileSearch,
  Globe2,
  History,
  RefreshCw,
  Search,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NetworkUnreachableError, getRunHistory, type RunHistoryItem } from "@/lib/polaris-api";

const ACTIVE_STATUSES = new Set([
  "pending",
  "parsing",
  "retrieving_context",
  "analyzing",
  "synthesizing",
]);

function formatDate(value: string) {
  const isoValue = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(isoValue);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function StatusBadge({ status }: { status: RunHistoryItem["status"] }) {
  if (status === "complete") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-600">
        <CheckCircle2 className="h-3.5 w-3.5" /> Complete
      </span>
    );
  }
  if (status === "cancelled")
    return (
      <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">
        Cancelled
      </span>
    );
  if (status === "error") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-1 text-xs font-medium text-red-600">
        <XCircle className="h-3.5 w-3.5" /> Failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-500/10 px-2.5 py-1 text-xs font-medium capitalize text-blue-600">
      <Clock3 className="h-3.5 w-3.5 animate-pulse" /> {status.replace("_", " ")}
    </span>
  );
}

export function RunHistory({
  onOpenRun,
  onNewAnalysis,
}: {
  onOpenRun: (runId: string) => void;
  onNewAnalysis: () => void;
}) {
  const [items, setItems] = useState<RunHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const pages = useRef(1);
  const loadingGuard = useRef(false);

  const load = useCallback(async (quiet = false) => {
    if (loadingGuard.current) return;
    loadingGuard.current = true;
    if (quiet) setRefreshing(true);
    else setLoading(true);
    try {
      const responses = await Promise.all(
        Array.from({ length: pages.current }, (_, page) => getRunHistory(100, page * 100)),
      );
      setItems(responses.flatMap((response) => response.items));
      setTotal(responses[0]?.total ?? 0);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof NetworkUnreachableError
          ? "Can't reach the POLARIS backend. Make sure it is running."
          : "Run history could not be loaded.",
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
      loadingGuard.current = false;
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!items.some((item) => ACTIVE_STATUSES.has(item.status))) return;
    const timer = window.setInterval(() => void load(true), 10_000);
    return () => window.clearInterval(timer);
  }, [items, load]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    return items.filter(
      (item) =>
        item.title.toLowerCase().includes(needle) ||
        (item.domain ?? "").toLowerCase().includes(needle) ||
        item.run_id.toLowerCase().includes(needle),
    );
  }, [items, query]);

  const complete = items.filter((item) => item.status === "complete").length;
  const failed = items.filter((item) => item.status === "error").length;
  const active = items.filter((item) => ACTIVE_STATUSES.has(item.status)).length;

  return (
    <main className="mx-auto w-full max-w-7xl px-5 py-8 lg:px-10 lg:py-10">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
            <History className="h-4 w-4 text-primary" /> Workspace archive
          </div>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">Policy library</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Review every policy analysis stored in this local POLARIS workspace.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => void load(true)} disabled={refreshing}>
            <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} /> Refresh
          </Button>
          <Button onClick={onNewAnalysis}>New analysis</Button>
        </div>
      </div>

      <section className="mt-7 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ["All runs", total, History],
          ["Complete", complete, CheckCircle2],
          ["In progress", active, Clock3],
          ["Failed", failed, AlertTriangle],
        ].map(([label, value, Icon]) => {
          const MetricIcon = Icon as typeof History;
          return (
            <div key={String(label)} className="panel flex items-center gap-3 p-4">
              <div className="rounded-xl bg-muted p-2.5 text-primary">
                <MetricIcon className="h-5 w-5" />
              </div>
              <div>
                <div className="text-2xl font-bold">{String(value)}</div>
                <div className="text-xs text-muted-foreground">{String(label)}</div>
              </div>
            </div>
          );
        })}
      </section>

      <section className="panel mt-5 overflow-hidden p-0">
        <div className="flex flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-semibold">Previous analyses</h2>
            <p className="text-xs text-muted-foreground">
              Newest runs appear first. Counts below describe loaded analyses.
            </p>
          </div>
          <div className="relative w-full sm:w-80">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="Search policy library"
              placeholder="Search policy, domain, or run ID"
              className="pl-9"
            />
          </div>
        </div>

        {loading ? (
          <div className="flex min-h-64 items-center justify-center text-sm text-muted-foreground">
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> Loading run history…
          </div>
        ) : error ? (
          <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
            <AlertTriangle className="h-7 w-7 text-danger" />
            <p className="mt-3 text-sm text-muted-foreground">{error}</p>
            <Button variant="outline" className="mt-4" onClick={() => void load()}>
              Try again
            </Button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
            <FileSearch className="h-8 w-8 text-muted-foreground" />
            <h3 className="mt-3 font-semibold">
              {items.length ? "No matching runs" : "No analyses yet"}
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {items.length
                ? "Try another search."
                : "Submit your first policy to build the workspace history."}
            </p>
          </div>
        ) : (
          <div className="divide-y">
            {filtered.map((item) => (
              <article
                key={item.run_id}
                className="grid gap-4 px-5 py-5 transition-colors hover:bg-muted/35 lg:grid-cols-[minmax(0,1fr)_140px_160px_auto] lg:items-center"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={item.status} />
                    {item.domain && (
                      <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                        {item.domain}
                      </span>
                    )}
                  </div>
                  <h3 className="mt-2 truncate font-semibold" title={item.title}>
                    {item.title}
                  </h3>
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span>{formatDate(item.created_at)}</span>
                    <span className="font-mono">{item.run_id.slice(0, 8)}</span>
                  </div>
                  {item.status === "error" && item.error && (
                    <p className="mt-2 line-clamp-2 text-xs text-danger">{item.error}</p>
                  )}
                </div>

                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Bot className="h-4 w-4" />
                  <span>
                    <strong className="text-foreground">{item.agents_complete}/5</strong> agents
                  </span>
                </div>

                <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted-foreground lg:block lg:space-y-2">
                  <div className="flex items-center gap-2">
                    <Globe2 className="h-4 w-4" /> {item.web_sources} web sources
                  </div>
                  <div>
                    Confidence:{" "}
                    <strong className="text-foreground">
                      {item.confidence == null ? "—" : `${Math.round(item.confidence * 100)}%`}
                    </strong>
                  </div>
                </div>

                <Button variant="outline" onClick={() => onOpenRun(item.run_id)}>
                  Open analysis
                </Button>
              </article>
            ))}
          </div>
        )}
      </section>
      {items.length < total && (
        <Button
          className="mt-5"
          variant="outline"
          disabled={refreshing}
          onClick={() => {
            pages.current += 1;
            void load(true);
          }}
        >
          Load more analyses ({items.length} of {total})
        </Button>
      )}
    </main>
  );
}
