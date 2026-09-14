# POLARIS — Policy intelligence studio

POLARIS is a local research workspace for Indian public policy. Submit a policy or document, inspect specialist assessments and their evidence, ask follow-up questions, and explore changed assumptions. React/TypeScript and TanStack Start power the interface; FastAPI, SQLite, local retrieval, trusted-domain web retrieval, and Groq power the backend.

## What's included

- **Balanced and Deep analysis.** Balanced combines four specialist perspectives into one assessment call, risk/synthesis into another, grounded possible futures into a third, and recommendations into a fourth: **4 planned model calls instead of Deep's 8**. Document parsing runs locally. Scenario and recommendation inputs are compacted from completed findings to remain within the safe request ceiling. Validation repairs and provider retries can still add calls.
- **A shared, durable queue.** Policy analysis, Ask POLARIS, and scenario-lab jobs share a single FIFO worker and the same shared request/token pacing. Queued positions, started/finished timestamps, stage states, and provider wait deadlines come from the backend.
- **Partial results and cancellation.** Validated findings are saved after each stage, including scenarios and recommendations. Cancel queued or running work without deleting completed findings. A late response cannot overwrite a cancelled job. Work interrupted by a backend restart resumes valid saved checkpoints. An already dispatched provider request may still consume quota when cancelled.
- **Recent-result reuse.** Exact matching input, domain, model configuration, analysis mode, and evidence setting reuse active work or a recent completed run. Defaults are one hour with web research and 24 hours with document evidence only. The analysis-code revision is part of the cache key. Refresh bypasses a completed cache hit, but never duplicates an active request.
- **A responsive workspace.** Desktop sidebar and mobile navigation, light/dark themes, editable illustrative proposals, input/upload tabs, drag-and-drop, file validation, automatic local drafts, history search, and readable empty/error states.
- **Six-section Quick summary.** What the policy does; likely benefits; tradeoffs and risks; who is affected; uncertainty; recommended actions. Analyst detail exposes metrics, reasoning summaries, source excerpts, geographic estimates, and recommendations. Switching views uses the same saved results and makes no model request. Reading preference is saved locally.
- **Claim-level evidence drawer.** Important findings expose View evidence. New outputs reference stable document/source IDs. References are checked against the catalog actually sent to that model call, including after prompt compaction and repair. The drawer shows linked excerpts, source URLs, recorded metadata, assumptions, uncertainty, and explicitly linked conflicting evidence. Unlinked findings say so. IDs establish traceability, not proof.
- **Ask POLARIS.** A floating accessible dialog with saved, separate conversation histories for each run. Answers use bounded follow-up context, completed findings, and supplied evidence. Partial answers are labeled. Sending, queued/waiting, retry, and cancellation states are real; responses are not simulated streaming. Minimize and reopen without losing saved messages.
- **What if? scenario lab.** Explicitly submitted changes to relevant qualitative assumptions and free-text notes create saved child variants. Variants show baseline versus revised findings and the assumption causing each change. Reopen, rename, retry, cancel, or delete a variant without modifying its parent analysis. This is **assumption-based reanalysis**, not a validated economic simulation.
- **Comparison and exports.** Compare two saved completed policies without model calls. Download text, JSON, and CSV reports or copy a report. CSV exports neutralize spreadsheet formulas in untrusted text.
- **Background navigation.** Continue browsing keeps backend work running. A persistent in-app indicator reopens the tracked analysis; completion/failure notifications link to saved findings. The selected run survives refresh through `?run=...` and session storage.

## Run locally

Requirements: Node.js compatible with Vite 8 (the workspace was checked with Node 24), Python 3.11+, and a Groq API key.

```powershell
npm install
python -m pip install -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env
```

Fill in `GROQ_API_KEY` in `backend/.env`. Preserve your existing configuration if that file already exists. ScrapingBee is optional; public retrieval works without it where sources allow access.

```powershell
powershell -ExecutionPolicy Bypass -File .\start-polaris.ps1
```

Frontend: http://127.0.0.1:8080  
Backend: http://127.0.0.1:8001  
API documentation: http://127.0.0.1:8001/docs

The startup script reuses already-running services. Restart an existing backend after changing Python code. A backend instance guard prevents accidentally running two independent local quota consumers.

Use `VITE_API_BASE_URL` when the frontend and backend are on different origins. API credentials remain in the backend and are never returned by the runtime endpoint.

## Quota protection

Existing token limits and environment overrides are retained. Default guardrails:

| Setting                         | Default | Purpose                                       |
| ------------------------------- | ------- | --------------------------------------------- |
| `GROQ_TOKENS_PER_MINUTE`        | 8000    | Configured provider token budget              |
| `GROQ_TPM_SAFETY_RATIO`         | 0.70    | Reserve tokenizer headroom                    |
| `GROQ_TOKEN_WINDOW_SECONDS`     | 65      | Conservative rolling window                   |
| `GROQ_MAX_REQUEST_TOKENS`       | 5500    | Estimated input plus maximum output ceiling   |
| `GROQ_REQUESTS_PER_MINUTE`      | 30      | Shared request pacing                         |
| `GROQ_REQUEST_SPACING`          | 0.75    | Minimum configured inter-call spacing         |
| `GROQ_BYTES_PER_TOKEN_ESTIMATE` | 2.0     | UTF-8 based conservative estimate             |
| `GROQ_TOKEN_BUDGET_SCOPE`       | shared  | Default account budget across model fallbacks |

The system serializes jobs and model calls, honors provider reset information and Retry-After, compacts repeated/secondary prompt content, and reconciles reserved tokens against returned usage. Long policy text is sampled across the document; the full document remains in SQLite/local retrieval. A request that cannot fit the configured ceiling fails locally rather than sending an oversized request.

Groq's remaining-request header refers to the daily request limit; token headers refer to the per-minute token limit. A non-exhausted daily reset is not treated as a mandatory pause. See [Groq's rate-limit documentation](https://console.groq.com/docs/rate-limits).

Quota telemetry in Preferences & system shows **local reservations**, not a provider account balance. API limits imposed by other applications sharing your account can still delay work.

Optional cache settings can shorten or disable reuse:

```env
POLARIS_WEB_CACHE_TTL_SECONDS=3600
POLARIS_DOCUMENT_CACHE_TTL_SECONDS=86400
```

Chat and scenario analysis each have one planned call, plus bounded validation/provider retries. Merely opening chat, moving assumption controls, browsing history, switching summary/detail, comparing runs, or exporting reports makes no Groq calls.

## Evidence and analytical quality

New synthesis output includes a `brief` with six keys:

```json
{
  "policy": [],
  "benefits": [],
  "risks": [],
  "affected": [],
  "uncertainty": [],
  "actions": []
}
```

Each section contains concise claims:

```json
{
  "text": "A policy-specific finding",
  "kind": "ai_inference",
  "evidence_ids": ["doc-..."],
  "assumptions": [],
  "uncertainty": "What the available evidence does not establish",
  "conflicting_evidence_ids": []
}
```

Kinds distinguish document facts, external evidence, AI inferences, and user assumptions. Model classification is not independent fact verification. Invalid IDs are removed, not replaced by guessed sources. Model inputs treat policy text, external excerpts, prior responses, and user assumptions as untrusted data rather than instructions.

Metadata is shown only when actually available. Plain text/PDF extraction currently does not retain original document pagination; passage IDs are retrieval identifiers, not invented page numbers. Web publication dates appear only when provided in supported source metadata. A blocked or unreadable page remains a link-only reference and is not supplied as page-content evidence.

Older runs remain readable. They do not receive fabricated citations, new brief sections, or recommendations. Any later chat on an older run can cite the specific catalog supplied to that chat; this does not retroactively attach those citations to the original analysis.

Impact values are **0–100 magnitude indices**, not benefit percentages. A score of 1 stays 1/100. Confidence is model-assessed evidence support, not measured accuracy. Aggregate confidence is the arithmetic mean of four domain confidences and risk confidence. Scenario likelihoods must be finite, individually between 5 and 90, have rationales, and total 100; only minor rounding discrepancies are normalized.

## Persistence and API

The existing `backend/polaris.db` is preserved. Schema changes add a cache-key column/index; no history is dropped or rewritten. Chat/scenario jobs use the existing durable job storage, keyed by parent run and job kind, and are excluded from the main policy library. Completed checkpoints are saved with each policy.

| Method     | Endpoint                       | Behavior                                                     |
| ---------- | ------------------------------ | ------------------------------------------------------------ |
| GET        | `/api/health`                  | Service health                                               |
| GET        | `/api/runtime`                 | Safe queue, quota configuration, cache, and mode metadata    |
| POST       | `/api/runs`                    | Submit policy text or reuse an identical run                 |
| POST       | `/api/runs/upload`             | Extract and submit a document                                |
| GET        | `/api/runs?limit=100&offset=0` | Policy history without full policy text                      |
| GET        | `/api/runs/{id}`               | Saved findings, stages, evidence, and current queue position |
| POST       | `/api/runs/{id}/cancel`        | Cancel while preserving partial findings                     |
| GET / POST | `/api/runs/{id}/chat`          | List saved chat exchanges / queue a question                 |
| GET / POST | `/api/runs/{id}/scenarios`     | List variants / queue assumption reanalysis                  |
| GET        | `/api/jobs/{id}`               | Inspect a chat or scenario job                               |
| POST       | `/api/jobs/{id}/cancel`        | Cancel a chat/scenario job                                   |
| POST       | `/api/jobs/{id}/retry`         | Retry a failed/cancelled chat/scenario job                   |
| PATCH      | `/api/scenarios/{id}`          | Rename a variant                                             |
| DELETE     | `/api/scenarios/{id}`          | Cancel if necessary and delete a variant                     |

Create an analysis:

```json
{
  "policy_text": "Your policy proposal",
  "domain_hint": null,
  "web_enabled": true,
  "analysis_mode": "balanced",
  "force_refresh": false
}
```

Response includes `run_id`, `reused`, `reuse_reason` (active/cached/null), and `queue_position`. Position 0 is active; positive positions are queued; null means no live queue entry. Upload accepts the same options as multipart fields.

Chat POST: `{ "question": "...", "request_id": "client-generated-UUID" }`.  
Scenario POST: `{ "title": "...", "assumptions": {"Funding adequacy": "Funding constrained"}, "notes": "...", "request_id": "client-generated-UUID" }`.  
Rename PATCH: `{ "title": "New variant name" }`.

Request IDs make retries idempotent. One active chat reply per policy prevents accidental overlapping follow-ups. HTTP errors return readable details to the frontend.

## Checks

```powershell
python -m pip install -r backend/requirements-dev.txt
npm run typecheck
npm run lint
npm test
npm run build
```

The backend tests use temporary databases and mocked providers. They cover quota pacing, bounded requests, 4/8-call modes, local document parsing, immediate stage persistence, checkpoint recovery, cache separation and expiry, cancellation, source-ID validation, scenario validation, and workspace persistence.

The frontend test renders seven run states plus partial findings and old analyses using React server rendering. It checks six-section summaries, safe exports, citation identifiers, and initial input controls. This is not a substitute for interactive browser/accessibility testing.

Groq is the only supported model provider. Browser automation may still be needed for a full visual and accessibility QA pass.

## Remaining limits

- This is a local/shared workspace without authentication or per-user authorization. Do not expose the backend publicly as a multi-tenant service.
- Geographic weights still use illustrative, unsourced seed data. They are clearly labeled heuristic exposure, not empirical state effects. The bundled atlas has 36 regions, separate Telangana, Jammu and Kashmir, and Ladakh. It follows an Indian claimed-boundary depiction; disputed areas are labeled. Source provenance is in `src/data/india-map-sources.md`.
- Retrieval is lightweight keyword-based RAG, not a calibrated economic/legal model. Source allowlisting and valid citation IDs do not prove factual correctness.
- Uploaded files must be PDF, DOCX, TXT, MD, CSV, or JSON, at most 10 MB, with no more than 200,000 extracted characters. Scanned PDFs need OCR before upload.
- Chat can still wait behind the current analysis or the provider's quota window. Scenario reanalysis runs locally.
- The comparison picker currently loads up to 500 recent analyses. Use Load more analyses in the policy library, or the history API's pagination, for older records.
- A client draft is stored locally; files must be selected again after refreshing the input form. Saved runs and conversations live in the backend, not in browser storage.

## Main implementation files

Backend: `main.py`, `run_manager.py`, `db.py`, `run_cache.py`, `pipeline.py`, `groq_client.py`, `evidence.py`, `workspace.py`, `json_util.py`, and `web_retriever.py`.

Frontend: `src/routes/index.tsx`, `src/lib/polaris-api.ts`, and the POLARIS components: PolicyForm, RunProgress, DetailedDashboard, QuickSummary, EvidenceDrawer, AskPolaris, ScenarioLab, ComparisonWorkspace, RunHistory, Sidebar, TopBar, and SettingsPanel.

The Lovable integration rule still applies: do not rewrite published Git history. No deployment or push is needed to run this workspace locally.

The `Resume analysis` button calls `POST /api/runs/{run_id}/resume` for failed or cancelled analyses. Saved successful checkpoints are reused. Validation repair avoids duplicating the system instructions and discards an invalid prior completion when necessary to fit the unchanged 5,500-token ceiling, preserving the grounding context instead. Balanced synthesis explicitly includes the six-section brief in its output schema.

### Regional explorer

The atlas offers keyboard-selectable regions, flat/3D-style relief, zoom/reset, search, domain weights, saved source mentions, and national domain context. Selection and browsing make no model calls. `Generate state dossier` queues a bounded, source-grounded follow-up through the existing worker; stable request IDs reuse each state's saved answer. Dossiers distinguish regional evidence from national inference and cover rural/urban eligibility, affected groups, implementation risks, actions, and monitoring gaps. They do not fetch new regional statistics or claim to be empirical state forecasts.
