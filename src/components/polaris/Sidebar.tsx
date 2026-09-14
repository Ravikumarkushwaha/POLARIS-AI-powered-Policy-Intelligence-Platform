import {
  ArrowUpRight,
  ChartNoAxesCombined,
  Compass,
  GitCompareArrows,
  History,
  LayoutDashboard,
  Plus,
  Settings2,
  ShieldCheck,
} from "lucide-react";
export type WorkspaceView = "analysis" | "history" | "compare";
export function Sidebar({
  activeAction,
  onDashboard,
  onNewAnalysis,
  onHistory,
  onCompare,
  onSettings,
  online,
  configured,
}: {
  activeAction: "dashboard" | "new" | "history" | "compare";
  onDashboard: () => void;
  onNewAnalysis: () => void;
  onHistory: () => void;
  onCompare: () => void;
  onSettings: () => void;
  online: boolean | null;
  configured: boolean;
}) {
  const items = [
    { label: "Analysis workspace", icon: LayoutDashboard, action: "dashboard", click: onDashboard },
    { label: "Policy library", icon: History, action: "history", click: onHistory },
    { label: "Compare policies", icon: GitCompareArrows, action: "compare", click: onCompare },
  ];
  return (
    <aside className="glass-sidebar hidden h-screen w-[248px] shrink-0 flex-col border-r border-sidebar-border px-5 py-7 text-sidebar-foreground lg:flex">
      <button
        onClick={onNewAnalysis}
        className="flex items-center gap-3 text-left"
        aria-label="POLARIS home"
      >
        <div className="brand-orbit flex size-11 items-center justify-center rounded-2xl border border-teal-400/30 bg-teal-400/10 text-teal-300">
          <Compass className="size-6" strokeWidth={1.5} />
        </div>
        <div>
          <div className="text-xl font-semibold tracking-[0.16em]">POLARIS</div>
          <div className="mt-0.5 text-[9px] uppercase tracking-[0.22em] text-slate-400">
            Policy intelligence studio
          </div>
        </div>
      </button>
      <button
        onClick={onNewAnalysis}
        className="premium-button mt-9 flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-cyan-300 px-4 py-3.5 text-sm font-semibold text-slate-950 shadow-[0_16px_30px_-18px_rgba(45,212,191,.8)] hover:from-teal-300 hover:to-cyan-200"
      >
        <Plus className="size-4" /> New analysis
      </button>
      <div className="mt-8 px-3 text-[10px] font-medium uppercase tracking-[0.18em] text-slate-500">
        Your workspace
      </div>
      <nav aria-label="Main navigation" className="mt-3 space-y-1.5">
        {items.map(({ label, icon: Icon, action, click }) => (
          <button
            key={action}
            onClick={click}
            aria-current={
              activeAction === action || (action === "dashboard" && activeAction === "new")
                ? "page"
                : undefined
            }
            className={`group flex w-full items-center gap-3 rounded-xl border px-3 py-3 text-left text-[13px] transition-all duration-200 ${activeAction === action || (action === "dashboard" && activeAction === "new") ? "border-teal-300/15 bg-gradient-to-r from-teal-400/12 to-cyan-300/5 text-teal-200 shadow-[0_12px_30px_-24px_rgba(45,212,191,.8)]" : "border-transparent text-slate-400 hover:border-white/5 hover:bg-white/[0.045] hover:text-white"}`}
          >
            <Icon className="size-[17px]" />
            {label}
          </button>
        ))}
      </nav>
      <div className="mt-9 rounded-2xl border border-white/10 bg-gradient-to-br from-white/[0.07] via-white/[0.025] to-teal-400/[0.025] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,.06)] backdrop-blur-xl">
        <ChartNoAxesCombined className="size-5 text-teal-300" />
        <h3 className="mt-3 text-xs font-medium">A clearer view of policy.</h3>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
          Explore the trade-offs. Examine the evidence. Make informed decisions.
        </p>
        <button
          onClick={onCompare}
          className="mt-4 flex items-center gap-1 text-[11px] font-medium text-teal-300"
        >
          Explore comparisons <ArrowUpRight className="size-3" />
        </button>
      </div>
      <div className="mt-auto pt-8">
        <button
          onClick={onSettings}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-3 text-[13px] text-slate-400 hover:bg-white/5 hover:text-white"
        >
          <Settings2 className="size-4" />
          Preferences & system
        </button>
        <div className="mt-4 border-t border-white/10 px-3 pt-5">
          <div className="flex items-center gap-2 text-xs">
            <span
              className={`size-1.5 rounded-full ${online && configured ? "bg-teal-400" : online === null ? "bg-slate-500" : "bg-amber-400"}`}
            />
            {online === null
              ? "Checking connection"
              : online
                ? configured
                  ? "Analysis server connected"
                  : "API setup required"
                : "Analysis server offline"}
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-[10px] text-slate-500">
            <ShieldCheck className="size-3" /> Requests paced within your limits
          </div>
        </div>
      </div>
    </aside>
  );
}
