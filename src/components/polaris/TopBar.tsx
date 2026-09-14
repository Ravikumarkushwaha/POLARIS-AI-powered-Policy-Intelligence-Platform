import {
  ChevronRight,
  Compass,
  GitCompareArrows,
  History,
  Moon,
  Plus,
  Settings2,
  Sun,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import type { WorkspaceView } from "./Sidebar";
export function TopBar({
  view,
  hasRun,
  onNewAnalysis,
  onHistory,
  onCompare,
  onSettings,
}: {
  view: WorkspaceView;
  hasRun: boolean;
  onNewAnalysis: () => void;
  onHistory: () => void;
  onCompare: () => void;
  onSettings: () => void;
}) {
  const [light, setLight] = useState(true);
  useEffect(() => {
    try {
      const saved = localStorage.getItem("polaris-theme");
      setLight(saved !== "dark");
    } catch {
      /* Browser storage is optional. */
    }
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("light", light);
    document.documentElement.classList.toggle("dark", !light);
  }, [light]);
  const toggle = () => {
    setLight(!light);
    try {
      localStorage.setItem("polaris-theme", light ? "dark" : "light");
    } catch {
      /* Theme works without persistence. */
    }
  };
  return (
    <header className="glass-topbar sticky top-0 z-30 flex min-h-[72px] shrink-0 flex-wrap items-center justify-between gap-2 border-b px-5 lg:px-9">
      <div className="flex items-center gap-3 text-xs">
        <Compass className="size-5 text-primary lg:hidden" />
        <span className="hidden text-muted-foreground sm:inline">Workspace</span>
        <ChevronRight className="hidden size-3 text-muted-foreground sm:block" />
        <span className="font-medium">
          {view === "history"
            ? "Policy library"
            : view === "compare"
              ? "Compare policies"
              : hasRun
                ? "Policy analysis"
                : "New analysis"}
        </span>
      </div>
      <div className="flex items-center gap-1 sm:gap-3">
        <span className="mr-2 hidden rounded-full border border-primary/15 bg-primary/[0.055] px-3 py-1.5 text-[10px] font-medium tracking-wide text-primary shadow-[inset_0_1px_0_rgba(255,255,255,.35)] sm:inline-flex">
          India edition
        </span>
        <Button
          variant="ghost"
          size="icon"
          onClick={onNewAnalysis}
          aria-label="New analysis"
          className="lg:hidden"
        >
          <Plus className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onHistory}
          aria-label="Policy library"
          className="lg:hidden"
        >
          <History className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onCompare}
          aria-label="Compare policies"
          className="lg:hidden"
        >
          <GitCompareArrows className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={toggle}
          aria-label={light ? "Use dark theme" : "Use light theme"}
        >
          {light ? <Moon className="size-4" /> : <Sun className="size-4" />}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onSettings}
          aria-label="Preferences and system"
        >
          <Settings2 className="size-4" />
        </Button>
      </div>
    </header>
  );
}
