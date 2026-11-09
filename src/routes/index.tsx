import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, Loader2, WifiOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { DetailedDashboard } from "@/components/polaris/DetailedDashboard";
import { PolicyForm } from "@/components/polaris/PolicyForm";
import { RunHistory } from "@/components/polaris/RunHistory";
import { SettingsPanel } from "@/components/polaris/SettingsPanel";
import { Sidebar, type WorkspaceView } from "@/components/polaris/Sidebar";
import { TopBar } from "@/components/polaris/TopBar";
import { RunProgress } from "@/components/polaris/RunProgress";
import { ComparisonWorkspace } from "@/components/polaris/ComparisonWorkspace";
import { EvidenceProvider } from "@/components/polaris/EvidenceDrawer";
import { AskPolaris } from "@/components/polaris/AskPolaris";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import {
  ApiError,
  NetworkUnreachableError,
  cancelRun,
  resumeRun,
  createRun,
  getRun,
  getRuntime,
  isRunActive,
  uploadPolicy,
  type AnalysisMode,
  type Run,
} from "@/lib/polaris-api";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "POLARIS — Policy intelligence studio" },
      {
        name: "description",
        content:
          "Explore Indian public policy through evidence, specialist perspectives, and assumption-based scenarios.",
      },
    ],
  }),
  component: Dashboard,
});
function remember(key: string, value: string | null) {
  try {
    if (value) sessionStorage.setItem(key, value);
    else sessionStorage.removeItem(key);
  } catch {
    /* Persistence is optional. */
  }
}
function Dashboard() {
  const navigate = useNavigate();
  const [runId, setRunId] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [webEnabled, setWebEnabled] = useState(true);
  const [view, setView] = useState<WorkspaceView>("analysis");
  const [initialDraft, setInitialDraft] = useState("");
  const [reuse, setReuse] = useState<string | null>(null);
  const guard = useRef(false);
  const pendingPolicy = useRef("");
  const notified = useRef<string | null>(null);
  const qc = useQueryClient();
  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("run");
    try {
      setRunId(fromUrl ?? sessionStorage.getItem("polaris-selected-run"));
      setActiveRunId(sessionStorage.getItem("polaris-active-run"));
      const setting = localStorage.getItem("polaris-web");
      if (setting !== null) setWebEnabled(setting === "true");
    } catch {
      setRunId(fromUrl);
    }
  }, []);
  const selectRun = useCallback((id: string | null) => {
    setRunId(id);
    remember("polaris-selected-run", id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("run", id);
    else url.searchParams.delete("run");
    window.history.replaceState(window.history.state, "", url);
  }, []);
  const runtime = useQuery({
    queryKey: ["runtime"],
    queryFn: getRuntime,
    refetchInterval: 15000,
    retry: false,
  });
  const online = runtime.isSuccess ? true : runtime.isError ? false : null;
  const selected = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId!),
    enabled: Boolean(runId),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
    refetchInterval: (q) =>
      (q.state.error instanceof ApiError && q.state.error.status === 404) ||
      (q.state.data && !isRunActive(q.state.data.status))
        ? false
        : typeof document !== "undefined" && document.visibilityState === "hidden"
          ? 15000
          : 4000,
  });
  const active = useQuery({
    queryKey: ["run", activeRunId],
    queryFn: () => getRun(activeRunId!),
    enabled: Boolean(activeRunId),
    retry: false,
    refetchInterval: (q) =>
      (q.state.error instanceof ApiError && q.state.error.status === 404) ||
      (q.state.data && !isRunActive(q.state.data.status))
        ? false
        : 5000,
  });
  const run = selected.data;
  useEffect(() => {
    if (!active.data || isRunActive(active.data.status) || notified.current === active.data.run_id)
      return;
    notified.current = active.data.run_id;
    const r = active.data;
    if (r.status === "complete")
      toast.success("Your policy analysis is ready.", {
        action: {
          label: "Open",
          onClick: () => {
            selectRun(r.run_id);
            setView("analysis");
          },
        },
      });
    else if (r.status === "error")
      toast.error("Analysis stopped. Completed findings have been saved.", {
        action: {
          label: "Review",
          onClick: () => {
            selectRun(r.run_id);
            setView("analysis");
          },
        },
      });
  }, [active.data, selectRun]);
  const changeWeb = (value: boolean) => {
    setWebEnabled(value);
    try {
      localStorage.setItem("polaris-web", String(value));
    } catch {
      /* Optional preference persistence. */
    }
  };
  const openRun = (id: string) => {
    pendingPolicy.current = "";
    setFormError(null);
    setReuse(null);
    selectRun(id);
    setView("analysis");
  };
  const reset = () => {
    selectRun(null);
    setView("analysis");
    setFormError(null);
    setReuse(null);
    setInitialDraft("");
  };
  const submit = async (
    text: string,
    domain: string | null,
    file: File | null,
    mode: AnalysisMode,
    force: boolean,
  ) => {
    if (guard.current) return;
    guard.current = true;
    setSubmitting(true);
    setFormError(null);
    try {
      const result = file
        ? await uploadPolicy(file, domain, webEnabled, mode, force)
        : await createRun({
            policy_text: text,
            domain_hint: domain,
            web_enabled: webEnabled,
            analysis_mode: mode,
            force_refresh: force,
          });
      pendingPolicy.current = file?.name ?? text;
      selectRun(result.run_id);
      setView("analysis");
      setReuse(
        result.reuse_reason === "cached"
          ? "Loaded a recent identical analysis. No new AI requests were needed."
          : result.reuse_reason === "active"
            ? "This policy is already being analyzed. You are viewing the existing run."
            : null,
      );
      if (result.reuse_reason !== "cached") {
        setActiveRunId(result.run_id);
        remember("polaris-active-run", result.run_id);
        notified.current = null;
      }
      void qc.invalidateQueries({ queryKey: ["runtime"] });
    } catch (e) {
      setFormError(
        e instanceof NetworkUnreachableError
          ? "The analysis server is offline. Start the backend and try again."
          : e instanceof Error
            ? e.message
            : "Could not start analysis",
      );
    } finally {
      guard.current = false;
      setSubmitting(false);
    }
  };
  const resume = async () => {
    if (!runId || cancelling) return;
    setCancelling(true);
    try {
      const next = await resumeRun(runId);
      qc.setQueryData(["run", runId], next);
      void qc.invalidateQueries({ queryKey: ["runtime"] });
      toast("Resuming from saved stages.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not resume");
    } finally {
      setCancelling(false);
    }
  };
  const cancel = async () => {
    if (!runId || cancelling) return;
    setCancelling(true);
    try {
      const next = await cancelRun(runId);
      qc.setQueryData(["run", runId], next);
      void qc.invalidateQueries({ queryKey: ["runtime"] });
      toast("Run cancelled. Completed findings remain available.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Cancellation failed");
    } finally {
      setCancelling(false);
    }
  };
  const fallback: Run = {
    run_id: runId ?? "",
    status: "pending",
    policy_input: {
      policy_text: pendingPolicy.current,
      domain_hint: null,
      web_enabled: webEnabled,
    },
    parsed_policy: null,
    retrieved_context: [],
    web_sources: [],
    agents: {
      economic: { status: "pending", output: null },
      environment: { status: "pending", output: null },
      social: { status: "pending", output: null },
      legal_budget: { status: "pending", output: null },
      risk: { status: "pending", output: null },
    },
    synthesis: null,
    state_impact: null,
    scenario_set: null,
    recommendations: null,
    error: null,
  };
  const display = run ?? fallback;
  const showIndicator =
    active.data &&
    isRunActive(active.data.status) &&
    (view !== "analysis" || runId !== activeRunId);
  return (
    <div className="app-shell flex h-dvh overflow-hidden bg-background">
      <a
        href="#workspace-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-card focus:p-3"
      >
        Skip to workspace
      </a>
      <Sidebar
        activeAction={
          view === "history"
            ? "history"
            : view === "compare"
              ? "compare"
              : view === "insights"
                ? "insights"
                : runId
                  ? "dashboard"
                  : "new"
        }
        onDashboard={() => setView("analysis")}
        onNewAnalysis={reset}
        onHistory={() => setView("history")}
        onCompare={() => setView("compare")}
        onPolicyInsights={() => {
          setView("insights");
          void navigate({ to: "/policy-insights" });
        }}
        onSettings={() => setSettingsOpen(true)}
        online={online}
        configured={runtime.data?.configured ?? false}
      />
      <div
        id="workspace-content"
        className="workspace-scroll min-h-0 min-w-0 flex-1 overflow-y-auto"
      >
        <TopBar
          view={view}
          hasRun={Boolean(runId)}
          onNewAnalysis={reset}
          onHistory={() => setView("history")}
          onCompare={() => setView("compare")}
          onPolicyInsights={() => {
            setView("insights");
            void navigate({ to: "/policy-insights" });
          }}
          onSettings={() => setSettingsOpen(true)}
        />
        {showIndicator && (
          <button
            onClick={() => openRun(activeRunId!)}
            className="flex w-full items-center justify-between gap-3 border-b border-primary/20 bg-primary/5 px-6 py-3 text-xs text-primary"
          >
            <span className="flex items-center gap-2">
              <Loader2 className="size-3 animate-spin" />
              Analysis continues in the background
            </span>
            <span className="flex items-center gap-2">
              Reopen run
              <ArrowRight className="size-3" />
            </span>
          </button>
        )}
        {view === "history" ? (
          <RunHistory onOpenRun={openRun} onNewAnalysis={reset} />
        ) : view === "compare" ? (
          <ComparisonWorkspace onOpenRun={openRun} onNewRun={reset} />
        ) : !runId ? (
          <PolicyForm
            onSubmit={submit}
            submitting={submitting}
            errorMessage={formError}
            webEnabled={webEnabled}
            onWebEnabledChange={changeWeb}
            initialDraft={initialDraft}
          />
        ) : selected.error instanceof ApiError && selected.error.status === 404 ? (
          <div className="panel m-8">
            <h1 className="font-semibold">This run was not found</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              It may belong to another backend workspace.
            </p>
            <Button className="mt-4" onClick={reset}>
              New analysis
            </Button>
          </div>
        ) : (
          <EvidenceProvider key={runId} run={display}>
            {selected.error && (
              <div
                role="alert"
                className="mx-5 mt-4 flex items-center gap-2 rounded-xl border border-danger/30 bg-danger/5 p-3 text-xs text-danger lg:mx-9"
              >
                <WifiOff className="size-4" />
                Connection interrupted. Saved findings below may be out of date.
                <button onClick={() => void selected.refetch()} className="ml-auto underline">
                  Retry
                </button>
              </div>
            )}
            {reuse && (
              <div className="mx-5 mt-4 flex gap-2 rounded-xl border border-primary/20 bg-primary/5 p-3 text-xs text-primary lg:mx-9">
                <CheckCircle2 className="size-4" />
                {reuse}
              </div>
            )}
            <RunProgress run={display} onCancel={() => void cancel()} cancelling={cancelling} />
            <div className="mx-5 mt-3 flex flex-wrap items-center justify-between gap-3 lg:mx-9">
              <button
                onClick={() => {
                  if (run && isRunActive(run.status)) {
                    setActiveRunId(run.run_id);
                    remember("polaris-active-run", run.run_id);
                  }
                  setView("history");
                }}
                className="text-xs text-primary hover:underline"
              >
                Continue browsing →
              </button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setInitialDraft(display.policy_input.policy_text);
                  selectRun(null);
                  setFormError(null);
                }}
                className="text-xs"
              >
                Edit as a new analysis
              </Button>
            </div>
            {(run?.status === "error" || run?.status === "cancelled") && (
              <div className="mx-5 mt-4 rounded-xl border border-warning/30 bg-warning/5 p-4 lg:mx-9">
                <h2 className="flex items-center gap-2 text-sm font-semibold">
                  <AlertTriangle className="size-4 text-warning" />
                  {run.status === "cancelled" ? "Analysis cancelled" : "Analysis stopped"}
                </h2>
                <p className="mt-2 text-xs leading-6 text-muted-foreground">
                  {run.error ?? "No further analysis calls will be made for this run."} Completed
                  findings below remain available.
                </p>
                <Button className="mt-3" onClick={() => void resume()} disabled={cancelling}>
                  {cancelling ? "Queuing..." : "Resume analysis"}
                </Button>
              </div>
            )}
            <DetailedDashboard run={display} />
            <AskPolaris key={runId} run={display} />
          </EvidenceProvider>
        )}
      </div>
      <Toaster />
      {settingsOpen && (
        <SettingsPanel
          webEnabled={webEnabled}
          onWebEnabledChange={changeWeb}
          onClose={() => setSettingsOpen(false)}
          runtime={runtime.data}
          online={online}
        />
      )}
    </div>
  );
}
