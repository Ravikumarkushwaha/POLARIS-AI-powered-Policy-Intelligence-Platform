from __future__ import annotations

import asyncio
import html
import io
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from rag import compact_text

SEARCH_URL = "https://html.duckduckgo.com/html/?q={}"
BING_SEARCH_URL = "https://www.bing.com/search?q={}"
SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
MAX_RESULTS = 8
MIN_RESULTS = 2
MAX_PAGE_CHARACTERS = 1200
TRUSTED_DOMAINS = (
    ".gov.in",
    ".nic.in",
    ".ac.in",
    ".org.in",
    "worldbank.org",
    "rbi.org.in",
    "mospi.gov.in",
    "niti.gov.in",
    "un.org",
    "iea.org",
    "imf.org",
    "oecd.org",
    "who.int",
    "unicef.org",
    "undp.org",
    "data.gov.in",
    "prsindia.org",
)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0
        self.published_at = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            values = dict(attrs)
            key = str(values.get("property") or values.get("name") or "").lower()
            date = values.get("content") or ""
            if key in {"article:published_time", "date", "dc.date", "dcterms.issued"} and re.match(r"^\d{4}-\d{2}-\d{2}", date):
                self.published_at = date
        if tag in {"script", "style", "nav", "header", "footer", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "header", "footer", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            value = re.sub(r"\s+", " ", html.unescape(data)).strip()
            if value:
                self.parts.append(value)


def _is_trusted(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return urlparse(url).scheme in {"http", "https"} and any(hostname == domain.lstrip(".") or hostname.endswith("." + domain.lstrip(".")) for domain in TRUSTED_DOMAINS)


def _result_url(href: str) -> str:
    parsed = urlparse(href)
    if parsed.hostname == "duckduckgo.com":
        target = parse_qs(parsed.query).get("uddg", [href])[0]
        return unquote(target)
    return href


def _search_results(markup: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', markup, re.I | re.S
    ):
        url = _result_url(html.unescape(match.group(1)))
        title = re.sub(r"<[^>]+>", "", html.unescape(match.group(2))).strip()
        if _is_trusted(url) and title:
            results.append({"title": title, "url": url})
        if len(results) >= MAX_RESULTS:
            break
    return results


def _bing_results(markup: str) -> list[dict[str, str]]:
    results = []
    for match in re.finditer(
        r'<li[^>]+class="b_algo".*?<h2><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        markup,
        re.I | re.S,
    ):
        url = html.unescape(match.group(1))
        title = re.sub(r"<[^>]+>", "", html.unescape(match.group(2))).strip()
        if _is_trusted(url) and title:
            results.append({"title": title, "url": url})
        if len(results) >= MAX_RESULTS:
            break
    return results


def _is_pdf_url_or_response(url: str, response: httpx.Response) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    if "pdf" in content_type:
        return True
    path = urlparse(url).path.lower()
    return path.endswith(".pdf")


def _extract_pdf_text(response: httpx.Response) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(response.content))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        cleaned = "\n".join(pages).strip()
        if not cleaned:
            return "PDF content was available but no readable text could be extracted."
        return compact_text(cleaned, MAX_PAGE_CHARACTERS)
    except Exception:
        return "PDF content was available but could not be converted to readable text."


async def _fetch_page(client: httpx.AsyncClient, result: dict[str, str]) -> dict[str, Any] | None:
    if not _is_trusted(result["url"]):
        return None
    result = {**result, "retrieved_at": datetime.now(timezone.utc).isoformat()}
    try:
        response = await _request_url(client, result["url"])
        response.raise_for_status()
        if not _is_trusted(result["url"]):
            return None

        # A direct trusted page redirected elsewhere must not inherit trust.
        final_host = urlparse(str(response.url)).hostname
        if not _is_trusted(str(response.url)) and final_host != urlparse(SCRAPINGBEE_URL).hostname:
            return {**result, "text": "", "source": urlparse(result["url"]).hostname, "retrieval_status": "link_only"}
        published_at = None
        if _is_pdf_url_or_response(result["url"], response):
            text = _extract_pdf_text(response)
        else:
            parser = _TextParser()
            parser.feed(response.text)
            published_at = parser.published_at
            text = compact_text(" ".join(parser.parts), MAX_PAGE_CHARACTERS)

        if len(text) < 160:
            return {
                **result,
                "text": "Page text was unavailable; review the linked source.",
                "retrieval_status": "link_only",
                "source": urlparse(result["url"]).hostname,
            }
        return {**result, "text": text, "source": urlparse(result["url"]).hostname, "retrieval_status": "extracted", **({"published_at": published_at} if published_at else {})}
    except Exception:
        # The trusted search result is still a real source even when its page
        # blocks automated extraction. Keep the link, but never invent text.
        return {
            **result,
            "text": "Trusted source identified; page text could not be retrieved during this run.",
            "source": urlparse(result["url"]).hostname,
            "retrieval_status": "link_only",
        }


def _search_queries(query: str) -> list[str]:
    compact = " ".join(query.split()[:18])
    return [
        query,
        f"{compact} site:gov.in",
        f"{compact} India research report",
    ]


async def retrieve_web_sources(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    """Search and scrape a small set of current, allowlisted public sources."""
    candidates: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for search_query in _search_queries(query):
        for search_url, parser in ((SEARCH_URL, _search_results), (BING_SEARCH_URL, _bing_results)):
            try:
                response = await _request_url(client, search_url.format(quote_plus(search_query)))
                response.raise_for_status()
                for candidate in parser(response.text):
                    if candidate["url"] in seen_urls:
                        continue
                    seen_urls.add(candidate["url"])
                    candidates.append(candidate)
                    if len(candidates) >= MAX_RESULTS:
                        break
                if len(candidates) >= MAX_RESULTS:
                    break
            except Exception:
                continue
        if len(candidates) >= MAX_RESULTS:
            break
    if not candidates:
        return []
    pages = await asyncio.gather(*(_fetch_page(client, result) for result in candidates))
    sources = [page for page in pages if page is not None]
    return sources[:MAX_RESULTS]


async def _request_url(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """Fetch through ScrapingBee when configured, otherwise use a direct request."""
    api_key = os.getenv("SCRAPINGBEE_API_KEY")
    if not api_key:
        return await client.get(
            url,
            headers={"User-Agent": "POLARIS/1.0 policy research"},
            timeout=12.0,
            follow_redirects=True,
        )
    try:
        response = await client.get(
            SCRAPINGBEE_URL,
            params={
                "api_key": api_key,
                "url": url,
                "render_js": "false",
                "premium_proxy": "false",
                "timeout": "10000",
            },
            headers={"User-Agent": "POLARIS/1.0 policy research"},
            timeout=25.0,
        )
        if response.is_success:
            return response
    except (httpx.HTTPError, TimeoutError):
        pass
    return await client.get(
        url,
        headers={"User-Agent": "POLARIS/1.0 policy research"},
        timeout=12.0,
        follow_redirects=True,
    )
