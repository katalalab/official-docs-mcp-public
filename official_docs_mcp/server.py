from __future__ import annotations

import json
import sys
from typing import Any, Callable

from . import __version__
from .fetcher import (
    collect_official_docs,
    fetch_document,
    freshness,
    list_sources,
    search_official_docs,
)

JSON = dict[str, Any]


TOOLS: dict[str, dict[str, Any]] = {
    "list_sources": {
        "description": "List registered official AI and developer tool documentation sources.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "search_official_docs": {
        "description": (
            "Search current official documentation. Uses SearXNG when "
            "OFFICIAL_DOCS_SEARXNG_URL is set, otherwise official "
            "llms/sitemap/seed URLs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "source_id": {
                    "type": "string",
                    "description": "Optional source id from list_sources.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "fetch_official_doc": {
        "description": (
            "Fetch an official documentation URL and return extracted text plus freshness metadata."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Official documentation URL."}},
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    "check_freshness": {
        "description": (
            "Check ETag, Last-Modified, retrieval time, and optional "
            "content hash for a documentation URL."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Official documentation URL."}},
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    "collect_official_docs": {
        "description": (
            "Collect official documentation URL catalogs from registered "
            "sources and optionally write .cache/catalog.json."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "Optional source id from list_sources.",
                },
                "limit_per_source": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 250,
                    "default": 60,
                },
                "fetch_metadata": {
                    "type": "boolean",
                    "default": False,
                    "description": "Fetch HEAD/metadata for each URL. Slower.",
                },
                "write_cache": {
                    "type": "boolean",
                    "default": True,
                    "description": "Write .cache/catalog.json in this project.",
                },
            },
            "additionalProperties": False,
        },
    },
}


def content(payload: Any) -> list[JSON]:
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]


def call_tool(name: str, arguments: JSON) -> JSON:
    handlers: dict[str, Callable[[JSON], Any]] = {
        "list_sources": lambda _: {"ok": True, "sources": list_sources()},
        "search_official_docs": lambda args: search_official_docs(
            args["query"], args.get("source_id"), int(args.get("limit", 8))
        ),
        "fetch_official_doc": lambda args: fetch_document(args["url"]),
        "check_freshness": lambda args: freshness(args["url"]),
        "collect_official_docs": lambda args: collect_official_docs(
            args.get("source_id"),
            int(args.get("limit_per_source", 60)),
            bool(args.get("fetch_metadata", False)),
            bool(args.get("write_cache", True)),
        ),
    }
    if name not in handlers:
        return {
            "content": content({"ok": False, "error": f"Unknown tool: {name}"}),
            "isError": True,
        }
    try:
        return {"content": content(handlers[name](arguments or {}))}
    except Exception:  # pragma: no cover - defensive protocol boundary
        return {
            "content": content({"ok": False, "error": "Request failed."}),
            "isError": True,
        }


def result_for(request: JSON) -> JSON | None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "official-docs-mcp", "version": __version__},
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": name,
                        "description": spec["description"],
                        "inputSchema": spec["inputSchema"],
                    }
                    for name, spec in TOOLS.items()
                ]
            },
        }
    if method == "tools/call":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": call_tool(params.get("name", ""), params.get("arguments") or {}),
        }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def configure_stdio() -> None:
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def main() -> None:
    configure_stdio()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = result_for(request)
        except Exception:  # pragma: no cover - defensive protocol boundary
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Invalid request."},
            }
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
