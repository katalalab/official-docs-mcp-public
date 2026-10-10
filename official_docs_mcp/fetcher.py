from __future__ import annotations

import hashlib
import html.parser
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sources import SOURCES, DocSource, get_source

DEFAULT_TIMEOUT_SECONDS = 12
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
USER_AGENT = "official-docs-mcp/0.1 (+local MCP official documentation retriever)"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / ".cache"
CATALOG_PATH = CACHE_DIR / "catalog.json"


class SafeFetchError(Exception):
    pass


class VerifiedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a validated address while retaining the hostname for TLS."""

    def __init__(self, host: str, port: int, address: str) -> None:
        super().__init__(host, port=port, timeout=DEFAULT_TIMEOUT_SECONDS)
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class VerifiedHTTPConnection(http.client.HTTPConnection):
    """Connect to a configured local service without resolving a second time."""

    def __init__(self, host: str, port: int, address: str) -> None:
        super().__init__(host, port=port, timeout=DEFAULT_TIMEOUT_SECONDS)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class HtmlTextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "a":
            attrs_dict = dict(attrs)
            self._current_href = attrs_dict.get("href")
            self._current_text = []
        if tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag == "a" and self._current_href:
            text = normalize_space(" ".join(self._current_text))
            self.links.append((self._current_href, text))
            self._current_href = None
            self._current_text = []
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._current_href is not None:
            self._current_text.append(data)
        self.parts.append(data)

    def text(self) -> str:
        return normalize_text(" ".join(self.parts))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_text(value: str) -> str:
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n\s+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _safe_error(url: Any, error: str, status: int | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "url": url if isinstance(url, str) else "",
        "status": status,
        "headers": {},
        "body": b"",
        "error": error,
        "retrieved_at": now_iso(),
    }


def _hostname_is_official(host: str) -> bool:
    return any(
        host == domain or host.endswith(f".{domain}")
        for source in SOURCES
        for domain in source.official_domains
    )


def _parse_url(url: str, *, allow_local_service: bool = False) -> urllib.parse.SplitResult:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except (AttributeError, TypeError, ValueError) as exc:
        raise SafeFetchError from exc
    if parsed.scheme not in {"https"} and not (allow_local_service and parsed.scheme == "http"):
        raise SafeFetchError
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise SafeFetchError
    if not allow_local_service and port not in {None, 443}:
        raise SafeFetchError
    return parsed


def _resolve_address(host: str, port: int, *, require_public: bool) -> str:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SafeFetchError from exc
    for record in records:
        address = record[4][0]
        try:
            if not require_public or ipaddress.ip_address(address).is_global:
                return address
        except ValueError:
            continue
    raise SafeFetchError


def _resolve_public_address(host: str, port: int) -> str:
    return _resolve_address(host, port, require_public=True)


def _validated_official_url(url: str) -> tuple[urllib.parse.SplitResult, str]:
    parsed = _parse_url(url)
    host = parsed.hostname
    assert host is not None
    if not _hostname_is_official(host.lower()):
        raise SafeFetchError
    return parsed, _resolve_public_address(host, parsed.port or 443)


def _searxng_validator(base_url: str):
    try:
        base = _parse_url(base_url, allow_local_service=True)
    except SafeFetchError:
        return None
    base_host = base.hostname
    assert base_host is not None
    base_origin = (
        base.scheme,
        base_host.lower(),
        base.port or (443 if base.scheme == "https" else 80),
    )

    def validate(url: str) -> tuple[urllib.parse.SplitResult, str]:
        parsed = _parse_url(url, allow_local_service=True)
        host = parsed.hostname
        assert host is not None
        origin = (
            parsed.scheme,
            host.lower(),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
        if origin != base_origin:
            raise SafeFetchError
        return parsed, _resolve_address(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            require_public=False,
        )

    return validate


def _request_once(
    parsed: urllib.parse.SplitResult, address: str, method: str
) -> tuple[int, dict[str, str], bytes]:
    path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    host = parsed.hostname
    assert host is not None
    if parsed.scheme == "https":
        connection: http.client.HTTPConnection = VerifiedHTTPSConnection(
            host, parsed.port or 443, address
        )
    else:
        connection = VerifiedHTTPConnection(host, parsed.port or 80, address)
    try:
        connection.request(
            method,
            path,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,text/plain,application/json,application/xml,*/*",
            },
        )
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        body = b"" if method == "HEAD" else response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise SafeFetchError
        return response.status, headers, body
    finally:
        connection.close()


def _fetch_url(url: str, method: str, validator: Any) -> dict[str, Any]:
    current_url = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            parsed, address = validator(current_url)
            status, headers, body = _request_once(parsed, address, method)
            if status not in {301, 302, 303, 307, 308}:
                return {
                    "ok": 200 <= status < 400,
                    "url": current_url,
                    "status": status,
                    "headers": headers,
                    "body": body,
                    "retrieved_at": now_iso(),
                }
            location = headers.get("location")
            if not location:
                return _safe_error(current_url, "Unable to retrieve URL.", status)
            current_url = urllib.parse.urljoin(current_url, location)
    except SafeFetchError:
        return _safe_error(current_url, "Request blocked by URL safety policy.")
    except (http.client.HTTPException, OSError, ssl.SSLError, ValueError):
        return _safe_error(current_url, "Unable to retrieve URL.")
    return _safe_error(current_url, "Request blocked by URL safety policy.")


def fetch_url(url: str, method: str = "GET") -> dict[str, Any]:
    return _fetch_url(url, method, _validated_official_url)


def fetch_searxng_url(url: str, base_url: str, method: str = "GET") -> dict[str, Any]:
    validator = _searxng_validator(base_url)
    if validator is None:
        return _safe_error(url, "Request blocked by URL safety policy.")
    return _fetch_url(url, method, validator)


def is_official_url(url: str, source: DocSource | None = None) -> bool:
    try:
        parsed = _parse_url(url)
    except SafeFetchError:
        return False
    host = parsed.hostname
    if not host:
        return False
    sources = (source,) if source else SOURCES
    return any(
        host.lower() == domain or host.lower().endswith(f".{domain}")
        for item in sources
        for domain in item.official_domains
    )


def source_for_url(url: str) -> DocSource | None:
    for source in SOURCES:
        if is_official_url(url, source):
            return source
    return None


def response_to_document(url: str, fetched: dict[str, Any]) -> dict[str, Any]:
    body = fetched.get("body", b"")
    content_type = fetched.get("headers", {}).get("content-type", "")
    text = body.decode("utf-8", errors="replace")
    links: list[dict[str, str]] = []
    if "html" in content_type or "<html" in text[:1000].lower():
        parser = HtmlTextExtractor()
        parser.feed(text)
        base_url = fetched.get("url") or url
        text = parser.text()
        links = [
            {"url": urllib.parse.urljoin(base_url, href), "text": label}
            for href, label in parser.links
            if href and not href.startswith(("#", "mailto:", "javascript:"))
        ]
    elif "xml" in content_type or text.lstrip().startswith("<?xml"):
        text = normalize_text(re.sub(r"<[^>]+>", "\n", text))
    else:
        text = normalize_text(text)
    digest = hashlib.sha256(body).hexdigest() if body else None
    source = source_for_url(fetched.get("url") or url)
    return {
        "url": fetched.get("url") or url,
        "requested_url": url,
        "status": fetched.get("status"),
        "ok": fetched.get("ok"),
        "source_id": source.id if source else None,
        "source_name": source.name if source else None,
        "official": is_official_url(fetched.get("url") or url, source),
        "retrieved_at": fetched.get("retrieved_at"),
        "content_type": content_type,
        "etag": fetched.get("headers", {}).get("etag"),
        "last_modified": fetched.get("headers", {}).get("last-modified"),
        "sha256": digest,
        "text": text[:120_000],
        "links": links[:200],
    }


def fetch_document(url: str) -> dict[str, Any]:
    fetched = fetch_url(url)
    doc = response_to_document(url, fetched)
    if not doc["official"]:
        doc["warning"] = "URL is outside registered official documentation domains."
    return doc


def freshness(url: str) -> dict[str, Any]:
    head = fetch_url(url, method="HEAD")
    if not head.get("ok"):
        get = fetch_url(url)
        doc = response_to_document(url, get)
        return {
            "url": doc["url"],
            "ok": doc["ok"],
            "status": doc["status"],
            "retrieved_at": doc["retrieved_at"],
            "etag": doc["etag"],
            "last_modified": doc["last_modified"],
            "sha256": doc["sha256"],
            "official": doc["official"],
            "warning": "HEAD failed; GET was used to compute hash.",
        }
    return {
        "url": head["url"],
        "ok": head["ok"],
        "status": head["status"],
        "retrieved_at": head["retrieved_at"],
        "etag": head["headers"].get("etag"),
        "last_modified": head["headers"].get("last-modified"),
        "sha256": None,
        "official": is_official_url(head["url"]),
    }


def collect_candidate_urls(source: DocSource, limit: int = 80) -> list[str]:
    urls: list[str] = []
    for url in (*source.llms_full_urls, *source.llms_urls, *source.sitemap_urls, *source.seed_urls):
        if url not in urls:
            urls.append(url)
            if len(urls) >= limit:
                return urls[:limit]
    for llms_url in (*source.llms_urls, *source.llms_full_urls):
        fetched = fetch_url(llms_url)
        if not fetched.get("ok"):
            continue
        text = fetched["body"].decode("utf-8", errors="replace")
        for match in re.findall(r"https?://[^\s)\]>\"']+", text):
            if is_official_url(match, source) and match not in urls:
                urls.append(match)
                if len(urls) >= limit:
                    return urls[:limit]
    for sitemap_url in source.sitemap_urls:
        fetched = fetch_url(sitemap_url)
        if not fetched.get("ok"):
            continue
        try:
            root = ET.fromstring(fetched["body"])
        except ET.ParseError:
            continue
        for loc in root.iter():
            if loc.tag.endswith("loc") and loc.text:
                candidate = loc.text.strip()
                if is_official_url(candidate, source) and candidate not in urls:
                    urls.append(candidate)
                    if len(urls) >= limit:
                        return urls[:limit]
    return urls[:limit]


def searxng_search(query: str, source: DocSource | None, limit: int) -> list[dict[str, Any]]:
    base_url = os.environ.get("OFFICIAL_DOCS_SEARXNG_URL", "").strip().rstrip("/")
    if not base_url:
        return []
    scoped_query = query
    if source:
        domain_filter = " OR ".join(f"site:{domain}" for domain in source.official_domains)
        scoped_query = f"({domain_filter}) {query}"
    params = urllib.parse.urlencode({"q": scoped_query, "format": "json", "language": "en"})
    fetched = fetch_searxng_url(f"{base_url}/search?{params}", base_url)
    if not fetched.get("ok"):
        return []
    try:
        payload = json.loads(fetched["body"].decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    results: list[dict[str, Any]] = []
    for item in payload.get("results", []):
        url = item.get("url")
        if not url or not is_official_url(url, source):
            continue
        found_source = source_for_url(url)
        results.append(
            {
                "title": item.get("title") or url,
                "url": url,
                "snippet": item.get("content") or "",
                "source": found_source.id if found_source else None,
                "official": True,
                "backend": "searxng",
            }
        )
        if len(results) >= limit:
            break
    return results


def direct_search(query: str, source: DocSource | None, limit: int) -> list[dict[str, Any]]:
    sources = (source,) if source else SOURCES
    terms = [term.lower() for term in re.findall(r"[\w.-]+", query) if len(term) > 1]
    results: list[dict[str, Any]] = []
    for item in sources:
        for url in collect_candidate_urls(item, limit=max(60, limit * 12)):
            url_score = sum(1 for term in terms if term in url.lower())
            score = url_score
            snippet = f"Official candidate from {item.name}. Fetch for exact content and citation."
            title = url.rstrip("/").rsplit("/", 1)[-1] or item.name
            if score == 0 and terms and len(results) < limit:
                doc = fetch_document(url)
                text = doc.get("text", "")
                lowered = text.lower()
                score = sum(lowered.count(term) for term in terms)
                if score:
                    title = first_line(text) or title
                    snippet = snippet_for_terms(text, terms)
            if score == 0 and terms:
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source": item.id,
                    "official": True,
                    "backend": "direct-index",
                    "score": score,
                }
            )
            if len(results) >= limit:
                return sorted(results, key=lambda row: row.get("score", 0), reverse=True)[:limit]
    if not results and source:
        results = [
            {
                "title": url.rstrip("/").rsplit("/", 1)[-1] or source.name,
                "url": url,
                "snippet": f"Seed URL from {source.name}.",
                "source": source.id,
                "official": True,
                "backend": "seed",
                "score": 0,
            }
            for url in source.seed_urls[:limit]
        ]
    return results[:limit]


def first_line(text: str) -> str:
    for line in text.splitlines():
        line = normalize_space(line)
        if line:
            return line[:160]
    return ""


def snippet_for_terms(text: str, terms: list[str], width: int = 320) -> str:
    lowered = text.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if not positions:
        return first_line(text)
    start = max(0, min(positions) - width // 3)
    end = min(len(text), start + width)
    return normalize_space(text[start:end])


def search_official_docs(
    query: str, source_id: str | None = None, limit: int = 8
) -> dict[str, Any]:
    source = get_source(source_id)
    if source_id and not source:
        return {
            "ok": False,
            "error": f"Unknown source_id: {source_id}",
            "sources": [item.id for item in SOURCES],
        }
    results = searxng_search(query, source, limit)
    backend = "searxng"
    if not results:
        results = direct_search(query, source, limit)
        backend = "direct-index"
    return {
        "ok": True,
        "query": query,
        "source_id": source_id,
        "backend": backend,
        "retrieved_at": now_iso(),
        "results": results[:limit],
    }


def list_sources() -> list[dict[str, Any]]:
    return [asdict(source) for source in SOURCES]


def collect_official_docs(
    source_id: str | None = None,
    limit_per_source: int = 60,
    fetch_metadata: bool = False,
    write_cache: bool = True,
) -> dict[str, Any]:
    source = get_source(source_id)
    if source_id and not source:
        return {
            "ok": False,
            "error": f"Unknown source_id: {source_id}",
            "sources": [item.id for item in SOURCES],
        }
    sources = (source,) if source else SOURCES
    limit_per_source = max(1, min(int(limit_per_source), 250))
    catalog_sources: list[dict[str, Any]] = []
    total_urls = 0
    for item in sources:
        entries: list[dict[str, Any]] = []
        for url in collect_candidate_urls(item, limit=limit_per_source):
            entry: dict[str, Any] = {"url": url, "official": is_official_url(url, item)}
            if fetch_metadata:
                fresh = freshness(url)
                entry.update(
                    {
                        "status": fresh.get("status"),
                        "retrieved_at": fresh.get("retrieved_at"),
                        "etag": fresh.get("etag"),
                        "last_modified": fresh.get("last_modified"),
                        "sha256": fresh.get("sha256"),
                    }
                )
            entries.append(entry)
        total_urls += len(entries)
        catalog_sources.append(
            {
                "source_id": item.id,
                "name": item.name,
                "official_domains": item.official_domains,
                "url_count": len(entries),
                "urls": entries,
            }
        )
    payload = {
        "ok": True,
        "generated_at": now_iso(),
        "source_id": source_id,
        "limit_per_source": limit_per_source,
        "fetch_metadata": fetch_metadata,
        "total_sources": len(catalog_sources),
        "total_urls": total_urls,
        "sources": catalog_sources,
    }
    if write_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CATALOG_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        payload["cache_path"] = str(CATALOG_PATH)
    return payload
