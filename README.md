# POLARIS

POLARIS is a full-stack policy intelligence platform that helps users analyze policy proposals, public documents, and regulatory text using a staged multi-agent workflow powered by Groq and a local evidence pipeline.

It is designed for quick analysis, structured evidence review, state-level relevance checks, scenario generation, and recommendation drafting for policy and governance use cases.

## Features

- Policy text analysis and document upload
- Multi-agent policy review across economic, environmental, social, legal, budget, and risk dimensions
- Local retrieval and evidence tracking for policy passages and documents
- Optional web-enabled research for supplemental context
- Structured verdicts and six-section briefs
- Scenario generation with likelihood and rationale
- Recommendation drafting grounded in analysis results
- State-level and India map insight integration
- Saved run history and result comparison
- Cancel, retry, and resume support for long-running jobs
- Safe report export in text, JSON, and CSV formats

## Tech Stack

- Frontend: React, TypeScript, Vite, TanStack Router, TanStack Query
- UI: Tailwind CSS, Radix UI, reusable dashboard components
- Backend: FastAPI, Python, Pydantic
- Database: SQLite
- AI: Groq API
- Retrieval: local document chunking and retrieval pipeline

## Project Structure

```text
policy-analyzer-hub-main/
├── backend/
│   ├── __init__.py
│   ├── db.py
│   ├── evidence.py
│   ├── groq_client.py
│   ├── json_util.py
│   ├── main.py
│   ├── models.py
│   ├── pipeline.py
│   ├── prompts.py
│   ├── rag.py
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── run_cache.py
│   ├── run_manager.py
│   ├── workspace.py
│   ├── web_retriever.py
│   └── worldbank.py
├── src/
│   ├── components/
│   ├── data/
│   ├── hooks/
│   ├── lib/
│   ├── routes/
│   ├── router.tsx
│   ├── server.ts
│   ├── start.ts
│   └── styles.css
├── public/
├── scripts/
├── AGENTS.md
├── package.json
├── start-polaris.ps1
├── tsconfig.json
├── vite.config.ts
├── README.md
└── ...
```

## Getting Started

### Prerequisites

- Node.js 20.19+ or 22.12+
- Python 3.11+
- A valid Groq API key

### Install dependencies

```powershell
npm install
python -m pip install -r backend/requirements.txt
```

### Environment setup

Create a backend environment file:

```powershell
Copy-Item backend/.env.example backend/.env
```

Then add your Groq key inside `backend/.env`:

```env
GROQ_API_KEY=your_key_here
```

Optional extras in `backend/.env.example`:

- `SCRAPINGBEE_API_KEY` — only needed if you want the web retriever to fetch external pages using ScrapingBee.
- `GROQ_MODEL`, `GROQ_FALLBACK_MODELS`, and related tuning values — optional overrides for model selection and retry behavior.

The backend also supports a local override file at `backend/.env.local`, which is loaded after `.env` and can be used for developer-specific settings without committing them.

### Run the app

```powershell
powershell -ExecutionPolicy Bypass -File .\start-polaris.ps1
```

This starts the backend and frontend for local development.

- Frontend: http://127.0.0.1:8080
- Backend: http://127.0.0.1:8001
- API docs: http://127.0.0.1:8001/docs

## Main API Endpoints

- `GET /api/health` — backend health check
- `GET /api/runtime` — queue, cache, and runtime information
- `POST /api/runs` — create a new policy analysis run
- `POST /api/runs/upload` — upload a document and analyze it
- `GET /api/runs` — list saved runs
- `GET /api/runs/{run_id}` — retrieve run details
- `POST /api/runs/{run_id}/cancel` — cancel a run
- `POST /api/runs/{run_id}/resume` — resume a failed or cancelled run
- `DELETE /api/runs/{run_id}` — delete a saved run

## Example Request

```json
{
  "policy_text": "Expand rural digital access through public-private infrastructure programs.",
  "domain_hint": "digital inclusion",
  "web_enabled": true,
  "analysis_mode": "balanced",
  "force_refresh": false
}
```

## Development and Validation

```powershell
npm run typecheck
npm run lint
npm test
npm run build
```

Backend tests are available under the `backend/` folder and cover policy flow, queue behavior, document processing, validations, and workspace jobs.

## Notes

- This project is intended for local or controlled internal use.
- The app is policy-analysis focused and may require a valid Groq account and internet access for optional web retrieval.
- It stores saved runs locally in SQLite and does not provide authentication or multi-user access by default.

## License

This project does not currently include a specific license file. Please check with the repository owner before public distribution or commercial reuse.
