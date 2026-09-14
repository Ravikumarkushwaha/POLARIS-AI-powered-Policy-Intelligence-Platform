import {
  ArrowRight,
  Check,
  ChevronRight,
  FileText,
  Globe2,
  Layers3,
  Leaf,
  Loader2,
  Scale,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  Users,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { AnalysisMode } from "@/lib/polaris-api";
import { POLICY_TEMPLATES } from "@/lib/policy-templates";

const DRAFT_KEY = "polaris-policy-draft-v1";
const DOMAINS = [
  { value: "unsure", label: "Auto-detect domain" },
  { value: "economic", label: "Economy & finance" },
  { value: "environmental", label: "Environment & energy" },
  { value: "social", label: "Social & education" },
  { value: "legal", label: "Governance & law" },
];

export function PolicyForm({
  onSubmit,
  submitting,
  errorMessage,
  webEnabled,
  onWebEnabledChange,
  initialDraft,
}: {
  onSubmit: (
    policyText: string,
    domainHint: string | null,
    file: File | null,
    mode: AnalysisMode,
    forceRefresh: boolean,
  ) => void;
  submitting: boolean;
  errorMessage: string | null;
  webEnabled: boolean;
  onWebEnabledChange: (value: boolean) => void;
  initialDraft?: string;
}) {
  const [text, setText] = useState("");
  const [domain, setDomain] = useState("unsure");
  const [mode, setMode] = useState<AnalysisMode>("balanced");
  const [file, setFile] = useState<File | null>(null);
  const [inputMode, setInputMode] = useState<"text" | "file">("text");
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [ready, setReady] = useState(false);
  const [forceRefresh, setForceRefresh] = useState(false);
  const [draftSaved, setDraftSaved] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const policyInput = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    try {
      const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null");
      if (draft) {
        if (typeof draft.text === "string") setText(draft.text);
        if (DOMAINS.some((d) => d.value === draft.domain)) setDomain(draft.domain);
        if (draft.mode === "deep") setMode("deep");
      }
    } catch {
      /* Invalid or unavailable storage is safe to ignore. */
    }
    if (initialDraft) setText(initialDraft);
    setReady(true);
  }, [initialDraft]);
  useEffect(() => {
    if (!ready) return;
    setDraftSaved(false);
    const timer = setTimeout(() => {
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({ text, domain, mode }));
        setDraftSaved(Boolean(text));
      } catch {
        /* Draft remains available in this page. */
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [text, domain, mode, ready]);
  const selectFile = (next: File | undefined) => {
    setFileError(null);
    if (!next) return;
    if (!/\.(pdf|docx|txt|md|csv|json)$/i.test(next.name)) {
      setFileError("Choose a PDF, DOCX, TXT, Markdown, CSV, or JSON file.");
      return;
    }
    if (next.size > 10 * 1024 * 1024) {
      setFileError("This file exceeds the 10 MB limit. Choose a smaller document.");
      return;
    }
    if (!next.size) {
      setFileError("This file is empty. Choose a document containing text.");
      return;
    }
    setFile(next);
  };
  const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
  const valid =
    inputMode === "file" ? Boolean(file) : Boolean(text.trim()) && text.length <= 200_000;
  return (
    <main
      id="main-content"
      className="workspace-enter mx-auto w-full max-w-[1330px] px-5 pb-10 pt-8 lg:px-9 lg:pt-10"
    >
      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">
        <span className="h-px w-5 bg-primary" /> Turn policy into perspective
      </div>
      <div className="mt-3 flex items-end justify-between gap-5">
        <div>
          <h1 className="hero-title text-[clamp(1.85rem,3.2vw,2.65rem)] font-semibold leading-[1.05] tracking-[-0.052em]">
            Big decisions. <span className="hero-title-accent">Better informed.</span>
          </h1>
          <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
            Understand how public policy could shape the economy, communities, and environment.
          </p>
        </div>
        <div className="hidden items-center gap-2 rounded-full border border-primary/15 bg-primary/5 px-3 py-1.5 text-[10px] text-primary xl:flex">
          <ShieldCheck className="size-3.5" /> Evidence-led analysis
        </div>
      </div>
      <div className="mt-8 grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_290px]">
        <form
          className="elevated-form overflow-hidden rounded-3xl border border-border"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid && !submitting)
              onSubmit(
                inputMode === "text" ? text.trim() : "",
                domain === "unsure" ? null : domain,
                inputMode === "file" ? file : null,
                mode,
                forceRefresh,
              );
          }}
        >
          <div className="flex items-center justify-between border-b border-border px-6 py-5">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-lg bg-primary/8 text-primary">
                <FileText className="size-[18px]" />
              </div>
              <div>
                <h2 className="text-sm font-semibold">Start a policy analysis</h2>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  One policy. Multiple perspectives.
                </p>
              </div>
            </div>
            <span className="hidden text-[10px] text-muted-foreground sm:block">01 / DEFINE</span>
          </div>
          <div className="space-y-5 p-5 sm:p-6">
            <div
              className="segmented-glass flex w-fit gap-1 rounded-xl p-1"
              role="tablist"
              aria-label="Policy input method"
            >
              {(["text", "file"] as const).map((kind) => (
                <button
                  type="button"
                  role="tab"
                  aria-selected={inputMode === kind}
                  aria-controls={`policy-${kind}-panel`}
                  id={`policy-${kind}-tab`}
                  key={kind}
                  onClick={() => setInputMode(kind)}
                  className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-medium transition ${inputMode === kind ? "bg-card/85 text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                >
                  {kind === "text" ? (
                    <FileText className="size-3.5" />
                  ) : (
                    <UploadCloud className="size-3.5" />
                  )}
                  {kind === "text" ? "Write or paste" : "Upload document"}
                </button>
              ))}
            </div>
            {inputMode === "text" ? (
              <div id="policy-text-panel" role="tabpanel" aria-labelledby="policy-text-tab">
                <label htmlFor="policy" className="text-xs font-medium">
                  What policy would you like to explore?
                </label>
                <Textarea
                  ref={policyInput}
                  id="policy"
                  value={text}
                  maxLength={200_000}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={
                    "Describe a policy, paste a proposal, or start with an example below.\n\nFor a useful analysis, include the objectives, target groups, timeline, budget, and location where available."
                  }
                  className="mt-3 min-h-[220px] resize-y rounded-xl border-border bg-background/40 p-4 text-[13px] leading-7 placeholder:text-muted-foreground/65 focus-visible:ring-primary/30"
                />
                <div className="mt-2 flex justify-between gap-2 text-[10px] text-muted-foreground">
                  <span className="flex items-center gap-1">
                    {draftSaved && (
                      <>
                        <Check className="size-3 text-primary" /> Draft saved on this device
                      </>
                    )}
                  </span>
                  <span>
                    {wordCount.toLocaleString()} words · {text.length.toLocaleString()} / 200,000
                    characters
                  </span>
                </div>
              </div>
            ) : (
              <div
                id="policy-file-panel"
                role="tabpanel"
                aria-labelledby="policy-file-tab"
                className={`flex min-h-[257px] flex-col items-center justify-center rounded-xl border border-dashed p-6 text-center transition ${dragging ? "border-primary bg-primary/10" : "border-border bg-background/40"}`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragging(false);
                  selectFile(e.dataTransfer.files[0]);
                }}
              >
                <UploadCloud className="size-8 text-primary" />
                <h3 className="mt-3 max-w-full break-all text-sm font-medium">
                  {file ? file.name : "Drop your policy document here"}
                </h3>
                <p className="mt-2 text-xs text-muted-foreground">
                  {file
                    ? `${(file.size / 1024).toFixed(0)} KB · Ready for text extraction`
                    : "PDF, DOCX, TXT, MD, CSV, or JSON · up to 10 MB"}
                </p>
                <p className="mt-1 text-[10px] text-muted-foreground">
                  Scanned PDFs need selectable text or OCR first.
                </p>
                <input
                  ref={fileInput}
                  type="file"
                  accept=".pdf,.docx,.txt,.md,.csv,.json"
                  className="sr-only"
                  aria-label="Choose policy document"
                  onChange={(e) => {
                    selectFile(e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
                <div className="mt-4 flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => fileInput.current?.click()}
                  >
                    {file ? "Change file" : "Browse files"}
                  </Button>
                  {file && (
                    <Button type="button" variant="ghost" size="sm" onClick={() => setFile(null)}>
                      <X className="size-3" />
                      Remove
                    </Button>
                  )}
                </div>
                {fileError && (
                  <p role="alert" className="mt-3 text-xs text-danger">
                    {fileError}
                  </p>
                )}
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="domain" className="text-xs font-medium">
                  Policy domain
                </label>
                <select
                  id="domain"
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  className="mt-2 h-10 w-full rounded-lg border border-border bg-background/40 px-3 text-xs"
                >
                  {DOMAINS.map((d) => (
                    <option key={d.value} value={d.value}>
                      {d.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className="text-xs font-medium">Evidence sources</div>
                <div className="mt-2 flex h-10 items-center justify-between rounded-lg border border-border px-3">
                  <label
                    htmlFor="web-evidence"
                    className="flex items-center gap-2 text-xs text-muted-foreground"
                  >
                    <Globe2 className="size-3.5" /> Include web research
                  </label>
                  <Switch
                    id="web-evidence"
                    checked={webEnabled}
                    onCheckedChange={onWebEnabledChange}
                  />
                </div>
              </div>
            </div>
            <fieldset>
              <legend className="mb-2 text-xs font-medium">Analysis depth</legend>
              <div className="grid gap-3 sm:grid-cols-2">
                {(
                  [
                    {
                      value: "balanced",
                      title: "Balanced",
                      icon: Zap,
                      note: "4 planned AI calls · grounded futures and actions",
                    },
                    {
                      value: "deep",
                      title: "Deep analysis",
                      icon: Layers3,
                      note: "8 planned AI calls · separate specialist assessments",
                    },
                  ] as const
                ).map(({ value, title, icon: Icon, note }) => (
                  <label
                    key={value}
                    className={`option-tile relative flex cursor-pointer gap-3 rounded-xl border p-3.5 ${mode === value ? "border-primary/50 bg-primary/7 shadow-[0_16px_30px_-28px_var(--primary)]" : "border-border"}`}
                  >
                    <input
                      type="radio"
                      name="analysis-mode"
                      value={value}
                      checked={mode === value}
                      onChange={() => setMode(value)}
                      className="sr-only peer"
                    />
                    <Icon
                      className={`mt-0.5 size-4 shrink-0 ${mode === value ? "text-primary" : "text-muted-foreground"}`}
                    />
                    <div>
                      <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
                        {title}
                        {value === "balanced" && (
                          <span className="text-[9px] text-primary">RECOMMENDED</span>
                        )}
                      </div>
                      <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
                        {note}
                      </p>
                    </div>
                    <span
                      className={`absolute right-2 top-2 size-1.5 rounded-full ${mode === value ? "bg-primary" : "bg-transparent"}`}
                    />
                    <span className="pointer-events-none absolute inset-0 rounded-xl peer-focus-visible:ring-2 peer-focus-visible:ring-primary" />
                  </label>
                ))}
              </div>
              <p className="mt-2 text-[10px] text-muted-foreground">
                Both include risk, scenarios, recommendations, and state estimates. Repairs can
                require extra calls.
              </p>
            </fieldset>
            <label className="flex cursor-pointer items-start gap-2 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                className="mt-0.5 accent-teal-600"
                checked={forceRefresh}
                onChange={(e) => setForceRefresh(e.target.checked)}
              />
              <span>
                Refresh an existing result with new research. By default, recent identical analyses
                are reused to save your quota.
              </span>
            </label>
            {errorMessage && (
              <div
                role="alert"
                className="rounded-lg border border-danger/20 bg-danger/5 p-3 text-xs text-danger"
              >
                {errorMessage}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-4 border-t border-border bg-background/35 px-6 py-4">
            <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
              <ShieldCheck className="size-3.5 text-primary" /> Your existing API limits stay in
              place
            </span>
            <Button
              type="submit"
              disabled={submitting || !valid}
              className="h-10 rounded-lg px-6 text-xs font-semibold"
            >
              {submitting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Sparkles className="size-4" />
              )}
              {submitting ? "Starting analysis…" : "Analyze policy"}
              <ArrowRight className="ml-2 size-3.5" />
            </Button>
          </div>
        </form>
        <aside className="space-y-5">
          <div className="panel !p-5">
            <div className="label-eyebrow">A complete perspective</div>
            <h2 className="mt-2 text-base font-semibold tracking-tight">
              See beyond the headline.
            </h2>
            <div className="mt-5 space-y-5">
              {[
                {
                  icon: Layers3,
                  title: "Economic impact",
                  body: "Growth, employment, and fiscal trade-offs.",
                },
                {
                  icon: Leaf,
                  title: "Environmental outcomes",
                  body: "Climate, resources, and long-term sustainability.",
                },
                {
                  icon: Users,
                  title: "Social implications",
                  body: "Access, inclusion, and community wellbeing.",
                },
                {
                  icon: Scale,
                  title: "Legal & implementation risks",
                  body: "Authority, funding, and delivery challenges.",
                },
              ].map(({ icon: Icon, title, body }) => (
                <div key={title} className="flex items-start gap-3">
                  <div className="rounded-lg bg-muted/65 p-2 text-primary">
                    <Icon className="size-4" strokeWidth={1.6} />
                  </div>
                  <div>
                    <h3 className="text-xs font-medium">{title}</h3>
                    <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-2xl border border-primary/15 bg-primary/[0.04] p-5">
            <div className="flex items-center gap-2 text-xs font-medium text-primary">
              <Zap className="size-4" /> Designed for your API budget
            </div>
            <p className="mt-3 text-[11px] leading-6 text-muted-foreground">
              Balanced mode combines specialist perspectives into fewer requests. Watch live
              progress, leave the page, and return to your saved results anytime.
            </p>
            <div className="mt-3 border-t border-primary/10 pt-3 text-[10px] text-muted-foreground">
              AI estimates support research. Validate important decisions against primary evidence.
            </div>
          </div>
        </aside>
      </div>
      <section className="mt-7">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-xs font-semibold">Need a starting point?</h2>
          <span className="text-[10px] text-muted-foreground">
            Illustrative proposals · edit before analyzing
          </span>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {POLICY_TEMPLATES.map((template, i) => {
            const Icon = [Leaf, Users, Layers3][i] ?? FileText;
            return (
              <button
                key={template.title}
                type="button"
                disabled={submitting}
                onClick={() => {
                  setText(template.text);
                  setDomain(template.domain);
                  setInputMode("text");
                  setTimeout(() => policyInput.current?.focus(), 0);
                }}
                className="group flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-4 text-left transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-sm"
              >
                <span className="rounded-lg bg-muted p-2 text-primary">
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="text-[9px] uppercase tracking-wider text-muted-foreground">
                    {template.tag}
                  </span>
                  <span className="mt-1 block text-xs font-medium">{template.title}</span>
                </span>
                <ChevronRight className="size-4 text-muted-foreground transition group-hover:text-primary" />
              </button>
            );
          })}
        </div>
      </section>
      <footer className="mt-8 flex flex-wrap justify-between gap-2 border-t border-border pt-4 text-[10px] text-muted-foreground">
        <span>POLARIS · Public policy, in perspective.</span>
        <span>Evidence → Perspectives → Decisions</span>
      </footer>
    </main>
  );
}
