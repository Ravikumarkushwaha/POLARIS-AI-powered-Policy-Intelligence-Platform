import assert from "node:assert/strict";
import { resolve } from "node:path";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const server = await createServer({
  configFile: false,
  cacheDir: "node_modules/.vite-frontend-tests",
  plugins: [react()],
  resolve: { alias: { "@": resolve("src") } },
  server: { middlewareMode: true },
  appType: "custom",
});
try {
  const { QuickSummary } = await server.ssrLoadModule("/src/components/polaris/QuickSummary.tsx");
  const { DetailedDashboard } = await server.ssrLoadModule(
    "/src/components/polaris/DetailedDashboard.tsx",
  );
  const { EvidenceProvider } = await server.ssrLoadModule(
    "/src/components/polaris/EvidenceDrawer.tsx",
  );
  const { RunProgress } = await server.ssrLoadModule("/src/components/polaris/RunProgress.tsx");
  const { PolicyForm } = await server.ssrLoadModule("/src/components/polaris/PolicyForm.tsx");
  const { buildReportText, buildReportCsv, safeSourceUrl } = await server.ssrLoadModule(
    "/src/lib/report-export.ts",
  );
  const { BRIEF_SECTIONS } = await server.ssrLoadModule("/src/lib/brief-sections.ts");
  const base = {
    run_id: "render-test",
    status: "pending",
    policy_input: { policy_text: "Illustrative policy test", domain_hint: null },
    parsed_policy: null,
    retrieved_context: [],
    web_sources: [],
    agents: Object.fromEntries(
      ["economic", "environment", "social", "legal_budget", "risk"].map((name) => [
        name,
        { status: "pending", output: null },
      ]),
    ),
    synthesis: null,
    state_impact: null,
    scenario_set: null,
    recommendations: null,
    error: null,
  };
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, enabled: false } },
  });
  const render = (element) =>
    renderToStaticMarkup(
      React.createElement(QueryClientProvider, { client: queryClient }, element),
    );
  const { StateInsights } = await server.ssrLoadModule("/src/components/polaris/StateInsights.tsx");
  const { normalizeState } = await server.ssrLoadModule("/src/lib/state-geography.ts");
  const atlas = render(React.createElement(StateInsights, { run: base }));
  assert.equal(
    (atlas.match(/role="button"/g) ?? []).length,
    36,
    "All 36 regions have accessible map controls",
  );
  assert.ok(atlas.includes("Jammu and Kashmir"));
  assert.ok(atlas.includes("Ladakh"));
  assert.ok(atlas.includes("No saved source passage names this region"));
  assert.ok(atlas.includes("Generate state dossier"));
  assert.notEqual(normalizeState("Telangana"), normalizeState("Andhra Pradesh"));
  assert.equal(normalizeState("Orissa"), normalizeState("Odisha"));
  for (const status of [
    "pending",
    "parsing",
    "analyzing",
    "synthesizing",
    "complete",
    "cancelled",
    "error",
  ]) {
    const run = { ...base, status };
    const html = render(
      React.createElement(
        EvidenceProvider,
        { run },
        React.createElement(DetailedDashboard, { run }),
      ),
    );
    assert.ok(html.includes("Quick summary"));
    for (const { label } of BRIEF_SECTIONS)
      assert.ok(html.includes(label.replaceAll("&", "&amp;")), label);
    assert.ok(!html.includes("Pilot procurement"), "No fabricated recommendations");
    const progress = render(
      React.createElement(RunProgress, { run, onCancel: () => {}, cancelling: false }),
    );
    assert.ok(progress.includes("Analysis progress"));
    if (status === "cancelled" || status === "complete" || status === "error")
      assert.ok(!progress.includes("Cancel run"));
  }
  const partial = {
    ...base,
    status: "analyzing",
    agents: {
      ...base.agents,
      risk: {
        status: "done",
        output: {
          risk_level: "High",
          justification: "A recorded funding gap threatens delivery.",
          confidence: 0.5,
        },
      },
    },
  };
  assert.ok(
    render(React.createElement(QuickSummary, { run: partial })).includes("A recorded funding gap"),
  );
  const brief = Object.fromEntries(
    BRIEF_SECTIONS.map(({ key }) => [
      key,
      [{ text: `Saved finding for ${key}`, evidence_ids: ["doc-test"] }],
    ]),
  );
  const complete = {
    ...base,
    status: "complete",
    synthesis: {
      overall_impact_score: 1,
      confidence: 0.5,
      verdict: "A recorded assessment",
      risk_level: "Medium",
      top_3_effects: [],
      brief,
    },
    recommendations: {
      recommendations: [
        {
          title: "=UNSAFE()",
          priority: "High",
          description: "Recorded recommendation",
          why: "Recorded evidence",
          supporting_signals: [],
        },
      ],
    },
  };
  const html = render(React.createElement(QuickSummary, { run: complete }));
  assert.ok(html.includes("Saved finding for benefits"));
  assert.ok(buildReportText(complete).includes("Impact score (model estimate): 1 / 100"));
  assert.ok(buildReportText(complete).includes("Sources: doc-test"));
  assert.ok(buildReportCsv(complete).includes("'=UNSAFE()"));
  assert.equal(safeSourceUrl("javascript:alert(1)"), undefined);
  assert.equal(safeSourceUrl("https://rbi.org.in/"), "https://rbi.org.in/");
  const form = render(
    React.createElement(PolicyForm, {
      onSubmit: () => {},
      submitting: false,
      errorMessage: null,
      webEnabled: true,
      onWebEnabledChange: () => {},
    }),
  );
  assert.ok(form.includes("Balanced"));
  assert.ok(form.includes("Upload document"));
  assert.ok(form.includes("aria-label"));
  console.log(
    "Frontend render checks passed: 7 run states, partial findings, six-section summary, safe exports, evidence IDs, and initial form.",
  );
} finally {
  await server.close();
}
