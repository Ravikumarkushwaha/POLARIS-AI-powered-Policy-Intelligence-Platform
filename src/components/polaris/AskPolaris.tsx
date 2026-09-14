import { MessageCircle, Minus, Send, Sparkles } from "lucide-react";
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { askPolaris, cancelJob, getChat, isRunActive, retryJob, type Run } from "@/lib/polaris-api";
import { EvidenceButton } from "./EvidenceDrawer";
import { JobStatus } from "./JobStatus";
const SUGGESTIONS = [
  "Explain the biggest risk in simple language.",
  "What evidence supports this finding?",
  "Who is most affected?",
  "What remains uncertain?",
  "What should policymakers do next?",
];
export function AskPolaris({ run }: { run: Run }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const guard = useRef(false);
  const request = useRef<{ text: string; id: string } | null>(null);
  const qc = useQueryClient();
  const key = ["chat", run.run_id];
  const history = useQuery({
    queryKey: key,
    queryFn: () => getChat(run.run_id),
    enabled: open,
    refetchInterval: (q) =>
      q.state.data?.items.some((item) => isRunActive(item.status)) ? 3500 : false,
    retry: false,
  });
  const jobs = history.data?.items ?? [];
  const waiting = jobs.some((item) => isRunActive(item.status));
  const send = async () => {
    const text = question.trim();
    if (!text || guard.current || waiting) return;
    guard.current = true;
    setSending(true);
    setError(null);
    if (request.current?.text !== text) request.current = { text, id: crypto.randomUUID() };
    try {
      await askPolaris(run.run_id, text, request.current.id);
      setQuestion("");
      request.current = null;
      await qc.invalidateQueries({ queryKey: key });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Message could not be sent");
    } finally {
      guard.current = false;
      setSending(false);
    }
  };
  const action = async (id: string, retry: boolean) => {
    try {
      await (retry ? retryJob(id) : cancelJob(id));
      await qc.invalidateQueries({ queryKey: key });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Request failed");
    }
  };
  return (
    <>
      <Button
        onClick={() => setOpen(true)}
        className="floating-action fixed bottom-5 right-5 z-40 rounded-full px-5 lg:bottom-7 lg:right-8"
      >
        <MessageCircle className="size-4" />
        Ask POLARIS
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="inset-x-0 bottom-0 top-auto flex h-[90dvh] max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-t-2xl p-0 sm:bottom-6 sm:left-auto sm:right-6 sm:h-[min(680px,85dvh)] sm:w-[450px] sm:max-w-[450px] sm:rounded-2xl">
          <DialogHeader className="border-b p-5 pr-14">
            <DialogTitle className="flex items-center gap-2 text-base">
              <Sparkles className="size-4 text-primary" />
              Ask POLARIS
              <button
                onClick={() => setOpen(false)}
                className="ml-auto rounded p-1 hover:bg-muted"
                aria-label="Minimize chat"
              >
                <Minus className="size-4" />
              </button>
            </DialogTitle>
            <DialogDescription className="line-clamp-2 text-xs">
              Discussing:{" "}
              {run.policy_input.source_name ?? run.policy_input.policy_text.slice(0, 130)}
            </DialogDescription>
          </DialogHeader>
          <div
            className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5"
            role="log"
            aria-label="Policy conversation"
          >
            {history.isLoading && (
              <p className="text-xs text-muted-foreground">Loading saved conversation…</p>
            )}
            {history.error && (
              <div role="alert" className="text-xs text-danger">
                Could not load messages.{" "}
                <button onClick={() => void history.refetch()} className="underline">
                  Retry
                </button>
              </div>
            )}
            {!jobs.length && !history.isLoading && (
              <div>
                <h3 className="text-sm font-medium">A conversation grounded in your policy.</h3>
                <p className="mt-2 text-xs leading-6 text-muted-foreground">
                  Ask about findings, evidence, or uncertainty. Each answer uses your shared API
                  budget and is saved with this run.
                </p>
                <div className="mt-4 space-y-2">
                  {SUGGESTIONS.map((text) => (
                    <button
                      key={text}
                      onClick={() => setQuestion(text)}
                      className="block w-full rounded-lg border p-3 text-left text-xs text-muted-foreground hover:border-primary/40 hover:text-primary"
                    >
                      {text}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {jobs.map((job) => (
              <article key={job.run_id} className="space-y-3">
                <div className="ml-7 rounded-xl bg-primary/10 p-3 text-sm leading-6">
                  {job.question}
                </div>
                <div className="mr-3 rounded-xl border bg-card p-4">
                  {job.output?.answer ? (
                    <>
                      {job.output.partial_findings && (
                        <p className="mb-2 text-[10px] font-medium text-warning">
                          Answer uses partial findings
                        </p>
                      )}
                      <p className="whitespace-pre-wrap text-sm leading-7">{job.output.answer}</p>
                      <EvidenceButton
                        text={job.output.answer}
                        trace={job.output}
                        catalog={job.evidence_catalog}
                      />
                    </>
                  ) : (
                    <>
                      <JobStatus job={job} />
                      {job.error && <p className="mt-2 text-xs text-danger">{job.error}</p>}
                      {isRunActive(job.status) ? (
                        <button
                          className="mt-3 text-xs text-muted-foreground underline"
                          onClick={() => void action(job.run_id, false)}
                        >
                          Cancel reply
                        </button>
                      ) : (
                        <button
                          className="mt-3 text-xs text-primary underline"
                          onClick={() => void action(job.run_id, true)}
                        >
                          Retry reply
                        </button>
                      )}
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
            className="space-y-2 border-t bg-background p-4"
          >
            <label htmlFor="chat-question" className="sr-only">
              Question about this policy
            </label>
            <Textarea
              id="chat-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={2000}
              placeholder="Ask about this policy…"
              className="min-h-20 resize-none text-sm"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            {error && (
              <p role="alert" className="text-xs text-danger">
                {error}
              </p>
            )}
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground">
                Saved per policy · Ctrl/⌘ + Enter to send
              </span>
              <Button type="submit" size="sm" disabled={!question.trim() || sending || waiting}>
                {sending ? "Sending…" : waiting ? "Reply queued" : "Send"}
                <Send className="size-3" />
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
