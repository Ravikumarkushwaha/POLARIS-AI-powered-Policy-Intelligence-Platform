import type { Run } from "@/lib/polaris-api";

export type ReportFormat = "text" | "json" | "csv";

export function policyTitle(text: string, maxLength = 105): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return "Untitled policy";
  const firstSentence = normalized.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? normalized;
  return firstSentence.length > maxLength
    ? `${firstSentence.slice(0, maxLength - 1).trimEnd()}…`
    : firstSentence;
}

export function asPercent(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  return Math.round(Math.max(0, Math.min(100, value <= 1 ? value * 100 : value)));
}

export function safeSourceUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export function buildReportText(run: Run): string {
  const synthesis = run.synthesis;
  const lines = [
    "POLARIS | Policy analysis report",
    `Run: ${run.run_id}`,
    `Status: ${run.status}`,
    `Domain: ${run.parsed_policy?.domain ?? run.policy_input.domain_hint ?? "Unclassified"}`,
    "",
    "POLICY INPUT",
    run.policy_input.policy_text,
    "",
    "ASSESSMENT",
    synthesis?.verdict ?? "No synthesis is available for this run.",
    `Impact score (model estimate): ${synthesis?.overall_impact_score ?? "Unavailable"} / 100`,
    `Risk level: ${synthesis?.risk_level ?? "Unavailable"}`,
    `Model confidence: ${asPercent(synthesis?.confidence) ?? "Unavailable"}${synthesis ? "%" : ""}`,
    ...(synthesis?.top_3_effects ?? []).map((effect) => `• ${effect}`),
    synthesis?.impact_score_rationale ?? "",
    synthesis?.confidence_basis?.note ?? "",
  ];
  if (synthesis?.brief) {
    lines.push("", "SIX-SECTION SUMMARY");
    for (const [section, claims] of Object.entries(synthesis.brief)) {
      lines.push(
        section.toUpperCase(),
        ...claims.map(
          (claim) =>
            claim.text +
            (claim.evidence_ids?.length ? " [Sources: " + claim.evidence_ids.join(", ") + "]" : ""),
        ),
      );
    }
  }
  for (const [name, agent] of Object.entries(run.agents ?? {})) {
    lines.push("", `${name.replace(/_/g, " ").toUpperCase()} · ${agent.status}`);
    if (!agent.output) continue;
    if ("reasoning" in agent.output) {
      lines.push(agent.output.reasoning);
      for (const metric of agent.output.metric_effects)
        lines.push(
          `• ${metric.metric}: ${metric.direction}, ${metric.magnitude}; confidence ${asPercent(metric.confidence)}%`,
        );
    } else lines.push(agent.output.justification);
  }
  lines.push("", "SCENARIOS · Model estimates");
  for (const scenario of run.scenario_set?.scenarios ?? [])
    lines.push(
      `${scenario.label}: ${scenario.title} (${scenario.probability}%)`,
      scenario.body,
      scenario.probability_rationale ?? "No likelihood rationale recorded.",
      ...scenario.points.map((point) => `• ${point}`),
      "",
    );
  lines.push("", "RECOMMENDATIONS");
  for (const item of run.recommendations?.recommendations ?? [])
    lines.push(
      `[${item.priority}] ${item.title}`,
      item.description,
      `Why: ${item.why}`,
      ...item.supporting_signals.map((signal) => `• ${signal}`),
      "",
    );
  lines.push("", "STATE IMPACT · Model-estimated relative weights, not measured outcomes");
  for (const [state, score] of Object.entries(run.state_impact ?? {}))
    lines.push(`${state}: ${score} / 100`);
  lines.push("", "EVIDENCE FROM THE SUBMITTED POLICY");
  for (const chunk of run.retrieved_context ?? [])
    lines.push(
      `[${chunk.chunk_id}] Lexical coverage: ${Math.round(chunk.relevance * 100)}%`,
      chunk.text,
      "",
    );
  lines.push("", "EXTERNAL REFERENCES");
  for (const source of run.web_sources ?? [])
    lines.push(
      `${source.title} — ${source.source}`,
      safeSourceUrl(source.url) ?? "Invalid source URL",
      source.text,
      "",
    );
  lines.push(
    "",
    "INTERPRETATION",
    "Scores, confidence values, and scenario probabilities are model estimates, not calibrated forecasts. Source excerpts provide context; a source list does not verify every generated claim. Geographic estimates may use illustrative baseline data; verify with official state statistics before use.",
  );
  return lines.join("\n");
}

/** Quote every cell and neutralize spreadsheet formulas in untrusted policy/model text. */
function csvCell(value: unknown): string {
  const text = String(value ?? "");
  const leadingStripped = [...text].findIndex(
    (character) => character.charCodeAt(0) > 31 && !/\s/.test(character),
  );
  const first = leadingStripped < 0 ? "" : text[leadingStripped];
  const safe = first && "=+@-".includes(first) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function buildReportCsv(run: Run): string {
  const rows: unknown[][] = [
    [
      "run_id",
      "section",
      "domain_or_state",
      "metric_or_title",
      "value",
      "direction",
      "magnitude",
      "confidence_percent",
      "detail",
    ],
  ];
  if (run.synthesis) {
    rows.push([
      run.run_id,
      "synthesis",
      "",
      "impact_score",
      run.synthesis.overall_impact_score,
      "",
      "",
      asPercent(run.synthesis.confidence),
      run.synthesis.verdict,
    ]);
    rows.push([
      run.run_id,
      "synthesis",
      "",
      "risk_level",
      run.synthesis.risk_level,
      "",
      "",
      "",
      "",
    ]);
  }
  for (const [name, agent] of Object.entries(run.agents ?? {})) {
    if (!agent.output || !("metric_effects" in agent.output)) continue;
    for (const effect of agent.output.metric_effects)
      rows.push([
        run.run_id,
        "metric",
        name,
        effect.metric,
        "",
        effect.direction,
        effect.magnitude,
        asPercent(effect.confidence),
        agent.output.reasoning,
      ]);
  }
  for (const [state, score] of Object.entries(run.state_impact ?? {}))
    rows.push([
      run.run_id,
      "state_impact",
      state,
      "model_estimated_weight",
      score,
      "",
      "",
      "",
      "Not measured state outcomes",
    ]);
  for (const item of run.recommendations?.recommendations ?? [])
    rows.push([
      run.run_id,
      "recommendation",
      "",
      item.title,
      item.priority,
      "",
      "",
      "",
      `${item.description} Why: ${item.why}`,
    ]);
  return `\uFEFF${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}`;
}

export function downloadReport(run: Run, format: ReportFormat): void {
  const formats = {
    text: {
      content: () => buildReportText(run),
      mime: "text/plain;charset=utf-8",
      extension: "txt",
    },
    json: {
      content: () => JSON.stringify(run, null, 2),
      mime: "application/json;charset=utf-8",
      extension: "json",
    },
    csv: { content: () => buildReportCsv(run), mime: "text/csv;charset=utf-8", extension: "csv" },
  };
  const selected = formats[format];
  const url = URL.createObjectURL(new Blob([selected.content()], { type: selected.mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `polaris-${run.run_id.slice(0, 12)}.${selected.extension}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
