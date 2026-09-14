import asyncio

import httpx

import web_retriever


def test_retrieval_keeps_at_least_two_unique_trusted_search_results(monkeypatch):
    markup = """
    <a class="result__a" href="https://www.rbi.org.in/report-one">RBI report</a>
    <a class="result__a" href="https://www.niti.gov.in/report-two">NITI report</a>
    """

    async def fake_request(_client, url):
        return httpx.Response(200, text=markup, request=httpx.Request("GET", url))

    async def fake_fetch(_client, result):
        return {**result, "source": result["url"].split("/")[2], "text": "Verified source text " * 20}

    monkeypatch.setattr(web_retriever, "_request_url", fake_request)
    monkeypatch.setattr(web_retriever, "_fetch_page", fake_fetch)

    async def run():
        async with httpx.AsyncClient() as client:
            return await web_retriever.retrieve_web_sources(client, "India monetary policy")

    sources = asyncio.run(run())
    assert len(sources) >= web_retriever.MIN_RESULTS
    assert len({source["url"] for source in sources}) == len(sources)


def test_failed_page_extraction_preserves_real_link_without_inventing_text(monkeypatch):
    async def fail_request(_client, _url):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(web_retriever, "_request_url", fail_request)
    result = {"title": "Official policy page", "url": "https://www.niti.gov.in/policy"}

    async def run():
        async with httpx.AsyncClient() as client:
            return await web_retriever._fetch_page(client, result)

    source = asyncio.run(run())
    assert source is not None
    assert source["url"] == result["url"]
    assert source["retrieval_status"] == "link_only"
    assert "could not be retrieved" in source["text"]
