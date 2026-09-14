"""Behavioral tests with temporary SQLite and mocked providers; no user documents or network."""
import asyncio
import copy
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest

sys.path.insert(0, os.path.dirname(__file__))
import db
import main
import pipeline
import workspace
import groq_client
from evidence import BRIEF_KEYS, build_catalog, model_catalog, sanitize_citations, supplied_ids
from json_util import as_score_100, normalize_scenario_output, normalize_parsed_policy
from models import new_run_payload
from run_manager import RunManager
from web_retriever import _is_trusted
from test_pipeline_efficiency import outputs, install_fake_model

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "workspace.db")
    monkeypatch.setattr(db, "_initialized", False)
    monkeypatch.setattr(db, "_lock", asyncio.Lock())
    monkeypatch.setattr(workspace, "_submit_lock", asyncio.Lock())
    monkeypatch.setattr(main, "_submission_lock", asyncio.Lock())
    return tmp_path

def sample_parent(run_id):
    parent = new_run_payload(run_id, "A district solar pilot funds household installations. Funding and uptake are uncertain.", "energy", False)
    parent.update(status="complete", parsed_policy={"domain":"energy", "goals":["Support solar access"], "stakeholders":["Households"], "affected_sectors":["Energy"], "timeline_years":None})
    parent["retrieved_context"] = [{"chunk_id":"policy-001","text":parent["policy_input"]["policy_text"],"relevance":1}]
    parent["evidence_catalog"] = build_catalog(parent["retrieved_context"], [])
    parent["citation_version"] = 1
    return parent

async def settled(job_id):
    for _ in range(300):
        job = await db.get_run(job_id)
        if job and job["status"] in db.TERMINAL_STATUSES:
            return job
        await asyncio.sleep(0.005)
    raise AssertionError("Mock job did not settle")

def test_exact_score_and_unspecified_timeline_and_trust_boundaries():
    assert as_score_100(1) == 1
    assert as_score_100(0.5) == 0.5
    assert normalize_parsed_policy({"domain":"energy"})["timeline_years"] is None
    for url in ("https://worldbank.org/policy", "https://data.worldbank.org/x", "https://mospi.gov.in/x"):
        assert _is_trusted(url)
    for url in ("https://evilworldbank.org/x", "https://worldbank.org.evil.com/x", "https://fakewho.int/x", "file://worldbank.org/x"):
        assert not _is_trusted(url)

def test_probability_bounds_and_rationales_cannot_be_normalized_away():
    base = outputs()["Scenario"]
    for values in ((1,49,50), (99,0.5,0.5), (30,30,30), (float("nan"),50,50)):
        raw = copy.deepcopy(base)
        for item, value in zip(raw["scenarios"], values):
            item["probability"] = value
        normalized = normalize_scenario_output(raw)
        assert pipeline._validate_scenario_output(normalized)
    raw = copy.deepcopy(base)
    raw["scenarios"][0]["probability_rationale"] = ""
    assert pipeline._validate_scenario_output(normalize_scenario_output(raw))
    for item, value in zip(raw["scenarios"], (34,33,32)):
        item["probability"] = value
        item["probability_rationale"] = "Delivery evidence gives a rationale for this estimate."
    fixed = normalize_scenario_output(raw)
    assert sum(item["probability"] for item in fixed["scenarios"]) == 100
    assert not pipeline._validate_scenario_output(fixed)

def test_citations_stable_and_only_supplied_catalog_can_authorize():
    catalog = build_catalog([{"chunk_id":"x","text":"A real policy excerpt"}], [{"url":"https://rbi.org.in/a","title":"Reference","text":"","retrieval_status":"link_only"}])
    assert catalog == build_catalog([{"chunk_id":"x","text":"A real policy excerpt"}], [{"url":"https://rbi.org.in/a","title":"Reference","text":"","retrieval_status":"link_only"}])
    assert "page" not in catalog[0] and "published_at" not in catalog[0]
    model = model_catalog(catalog)
    allowed = supplied_ids({"evidence_catalog":model,"previous":{"evidence_ids":["invented"]}})
    valid = catalog[0]["evidence_id"]
    assert allowed == {valid}
    assert sanitize_citations({"evidence_ids":[valid,"invented",valid],"claims":[{"conflicting_evidence_ids":["invented"]}]},allowed) == {"evidence_ids":[valid],"claims":[{"conflicting_evidence_ids":[]}]}
    assert all(item["kind"] == "document" for item in model)

def test_real_groq_boundary_filters_hallucinated_citations(monkeypatch):
    monkeypatch.setenv("POLARIS_AI_PROVIDER", "groq")
    async def scenario():
        monkeypatch.setenv("GROQ_API_KEY", "test-only")
        monkeypatch.setenv("GROQ_MODEL", "test-model")
        monkeypatch.setenv("GROQ_FALLBACK_MODELS", "")
        monkeypatch.setenv("GROQ_REQUEST_SPACING", "0")
        monkeypatch.setattr(groq_client, "_groq_semaphore", asyncio.Semaphore(1))
        monkeypatch.setattr(groq_client, "_token_window_lock", asyncio.Lock())
        monkeypatch.setattr(groq_client, "_token_windows", {})
        monkeypatch.setattr(groq_client, "_request_window", [])
        monkeypatch.setattr(groq_client, "_cooldown_until", 0)
        captured = []
        def transport(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"choices":[{"message":{"content":json.dumps({"answer":"Grounded explanation", "evidence_ids":["doc-real","doc-fake"]})}}],"usage":{"total_tokens":40}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            output = await groq_client.chat_json(client, system="Return JSON.", user=json.dumps({"evidence_catalog":[{"evidence_id":"doc-real","text":"Actual supplied passage"}]}), max_tokens=120)
        assert len(captured) == 1
        assert output["evidence_ids"] == ["doc-real"]
        prepared = captured[0]["messages"][1]["content"]
        assert "doc-real" in prepared
    asyncio.run(scenario())

def test_chat_persistence_isolation_followup_and_scenario_lifecycle(isolated, monkeypatch):
    async def scenario():
        calls = []
        async def provider(_client, *, stage_name, system, user, max_tokens, **kwargs):
            data = json.loads(user)
            _, size = groq_client._prepare_user_for_token_budget(system, user, max_tokens)
            assert size <= 5500
            calls.append(data)
            ids = list(supplied_ids(data))
            if stage_name == "Policy chat":
                return {"answer":"Funding gaps may limit household access; the supplied policy does not establish costs.", "evidence_ids":ids, "uncertainty":"Costs are unspecified."}
            claim = {"text":"A funding constraint may narrow access.", "evidence_ids":ids}
            return {"summary":"Funding constraints may limit access under this user hypothesis.",
                    "changes":[{"area":"benefits","baseline":"Access depends on funding.","revised":"Fewer households may receive support.","cause":"Funding constrained","evidence_ids":ids}],
                    "brief":{key:[claim] for key in BRIEF_KEYS}}
        monkeypatch.setattr(pipeline, "chat_json", provider)
        manager = RunManager(workspace.run_workspace_job)
        monkeypatch.setattr(main.app.state, "run_manager", manager, raising=False)
        a, b = sample_parent("a"), sample_parent("b")
        await db.save_run(a); await db.save_run(b)
        before = await db.get_run("a")
        await manager.start()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url="http://test") as client:
                body={"question":"Who faces the largest risk?","request_id":"chat-request-1"}
                response=await client.post("/api/runs/a/chat",json=body)
                assert response.status_code==200,response.text
                first=response.json()
                assert (await client.post("/api/runs/a/chat",json=body)).json()["run_id"]==first["run_id"]
                result=await settled(first["run_id"])
                assert result["status"]=="complete",result.get("error")
                assert result["output"]["evidence_ids"] == [a["evidence_catalog"][0]["evidence_id"]]
                assert (await client.get("/api/runs/b/chat")).json()["items"]==[]
                assert len((await client.get("/api/runs/a/chat")).json()["items"])==1
                next_reply=(await client.post("/api/runs/a/chat",json={"question":"What should be checked next?","request_id":"chat-request-2"})).json()
                await settled(next_reply["run_id"])
                assert len(calls[-1]["conversation"])==1
                variant=(await client.post("/api/runs/a/scenarios",json={"title":"Funding constrained","assumptions":{"Funding adequacy":"Funding constrained"},"request_id":"scenario-1"})).json()
                completed=await settled(variant["run_id"])
                assert completed["status"]=="complete",completed.get("error")
                assert completed["parent_run_id"]=="a"
                assert len((await client.get("/api/runs/a/scenarios")).json()["items"])==1
                assert (await client.get("/api/runs")).json()["total"]==2
                renamed=await client.patch("/api/scenarios/"+variant["run_id"],json={"title":"Revised pilot"})
                assert renamed.json()["title"]=="Revised pilot"
                assert (await client.get("/api/jobs/"+variant["run_id"])).json()["title"]=="Revised pilot"
                assert (await client.delete("/api/scenarios/"+variant["run_id"])).status_code==200
                assert (await client.get("/api/runs/a/scenarios")).json()["items"]==[]
                assert (await client.get("/api/runs/b/chat")).json()["items"]==[]
                assert await db.get_run("a")==before
        finally:
            await manager.stop()
        # Persistence survives a new manager, with no replay of completed jobs.
        new_manager=RunManager(workspace.run_workspace_job)
        await new_manager.start()
        assert len(await db.related_jobs("a","chat"))==2
        await new_manager.stop()
    asyncio.run(scenario())

def test_cancellation_blocks_late_overwrite_and_preserves_partial_work(isolated):
    async def scenario():
        started=asyncio.Event()
        async def late_worker(run_id):
            await db.patch_run(run_id,lambda p:p.update(parsed_policy={"domain":"saved"}))
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                # Even an uncooperative late completion cannot overwrite cancellation.
                await db.patch_run(run_id,lambda p:p.update(status="complete",synthesis={"verdict":"late"}))
        await db.save_run(new_run_payload("late","Policy",None))
        manager=RunManager(late_worker)
        await manager.start()
        try:
            await started.wait()
            await manager.cancel("late")
            saved=await db.get_run("late")
            assert saved["status"]=="cancelled"
            assert saved["parsed_policy"]=={"domain":"saved"}
            assert saved["synthesis"] is None
        finally:
            await manager.stop()
    asyncio.run(scenario())

def test_job_wait_telemetry_and_queued_cancellation(isolated, monkeypatch):
    async def scenario():
        waiting=asyncio.Event(); finish=asyncio.Event(); calls=[]
        async def provider(_client, **kwargs):
            calls.append(kwargs["stage_name"])
            await groq_client._emit_progress(event="waiting", wait_until=(datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat(),wait_reason="provider_cooldown")
            waiting.set()
            await finish.wait()
            return {"answer":"The policy does not establish costs, so the funding risk remains uncertain.","evidence_ids":[]}
        monkeypatch.setattr(pipeline,"chat_json",provider)
        parent=sample_parent("wait")
        await db.save_run(parent)
        manager=RunManager(workspace.run_workspace_job)
        monkeypatch.setattr(main.app.state,"run_manager",manager,raising=False)
        await manager.start()
        try:
            chat=await workspace.create_chat("wait",workspace.ChatRequest(question="What is uncertain?",request_id="wait-chat"))
            await waiting.wait()
            saved=await db.get_run(chat["run_id"])
            assert saved["telemetry"]["wait_reason"]=="provider_cooldown"
            variant=await workspace.create_scenario("wait",workspace.ScenarioRequest(notes="Assume slower implementation.",request_id="queued-scenario"))
            assert manager.run_state(variant["run_id"])["queue_position"]==1
            await manager.cancel(variant["run_id"])
            finish.set()
            await settled(chat["run_id"])
            assert calls==["Policy chat"]
            assert (await db.get_run(variant["run_id"]))["status"]=="cancelled"
        finally:
            await manager.stop()
    asyncio.run(scenario())

def test_full_pipeline_persists_findings_before_overall_completion(monkeypatch):
    from test_pipeline_efficiency import outputs as stage_outputs
    async def scenario():
        saved = new_run_payload("checkpoints", "Expand railway access with phased funding.", None, False)
        responses = stage_outputs()
        observed = []
        async def get(_):
            return copy.deepcopy(saved)
        async def patch(_, mutator):
            mutator(saved)
            return copy.deepcopy(saved)
        async def provider(_client, *, stage_name, **kwargs):
            if stage_name == "Risk Synthesis":
                assert all(saved["agents"][name]["status"] == "done" for name in pipeline.DOMAIN_NAMES)
            if stage_name == "Scenario":
                assert saved["synthesis"]["brief"]
                assert saved["synthesis"]["confidence"] > 0
                assert saved["status"] != "complete"
            if stage_name == "Recommendation":
                assert len(saved["scenario_set"]["scenarios"]) == 3
                assert saved["stages"]["scenario"] == "completed"
                assert saved["recommendations"] is None
                assert saved["status"] != "complete"
            observed.append(stage_name)
            return copy.deepcopy(responses[stage_name])
        monkeypatch.setattr(pipeline.db,"get_run",get)
        monkeypatch.setattr(pipeline.db,"patch_run",patch)
        monkeypatch.setattr(pipeline,"chat_json",provider)
        await pipeline.run_pipeline("checkpoints")
        assert saved["status"] == "complete",saved["error"]
        assert observed == ["Specialists","Risk Synthesis","Scenario","Recommendation"]
    asyncio.run(scenario())

def test_indic_policy_compaction_and_evidence_ids_remain_bounded(monkeypatch):
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE","8000")
    monkeypatch.setenv("GROQ_MAX_REQUEST_TOKENS","5500")
    monkeypatch.setenv("GROQ_TPM_SAFETY_RATIO","0.70")
    payload = {"policy_text":"सरकारी शिक्षा नीति " * 1200,
        "evidence_catalog":[{"evidence_id":"doc-stable","text":"वित्त और कार्यान्वयन " * 300}]}
    prepared, tokens = groq_client._prepare_user_for_token_budget("Analyze the supplied policy. Return JSON.",json.dumps(payload),600)
    assert tokens <= 5500
    assert "doc-stable" in prepared
    assert supplied_ids(json.loads(prepared)) == {"doc-stable"}
