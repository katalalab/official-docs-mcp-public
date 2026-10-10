from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocSource:
    id: str
    name: str
    official_domains: tuple[str, ...]
    seed_urls: tuple[str, ...]
    llms_urls: tuple[str, ...] = ()
    llms_full_urls: tuple[str, ...] = ()
    sitemap_urls: tuple[str, ...] = ()
    version_url: str | None = None


SOURCES: tuple[DocSource, ...] = (
    DocSource(
        id="openai",
        name="OpenAI",
        official_domains=("platform.openai.com", "developers.openai.com", "openai.com"),
        seed_urls=("https://platform.openai.com/docs", "https://developers.openai.com/"),
        llms_urls=(
            "https://platform.openai.com/docs/llms.txt",
            "https://developers.openai.com/llms.txt",
        ),
        llms_full_urls=(
            "https://platform.openai.com/docs/llms-full.txt",
            "https://developers.openai.com/llms-full.txt",
        ),
        sitemap_urls=(
            "https://platform.openai.com/sitemap.xml",
            "https://developers.openai.com/sitemap.xml",
        ),
    ),
    DocSource(
        id="anthropic",
        name="Anthropic Claude",
        official_domains=("docs.anthropic.com", "anthropic.com"),
        seed_urls=("https://docs.anthropic.com/",),
        llms_urls=("https://docs.anthropic.com/llms.txt",),
        llms_full_urls=("https://docs.anthropic.com/llms-full.txt",),
        sitemap_urls=("https://docs.anthropic.com/sitemap.xml",),
    ),
    DocSource(
        id="google-ai",
        name="Google AI Gemini",
        official_domains=("ai.google.dev", "developers.google.com", "cloud.google.com"),
        seed_urls=(
            "https://ai.google.dev/gemini-api/docs",
            "https://cloud.google.com/vertex-ai/generative-ai/docs",
        ),
        llms_urls=("https://ai.google.dev/llms.txt",),
        sitemap_urls=("https://ai.google.dev/sitemap.xml", "https://cloud.google.com/sitemap.xml"),
    ),
    DocSource(
        id="microsoft-learn",
        name="Microsoft Learn",
        official_domains=("learn.microsoft.com",),
        seed_urls=(
            "https://learn.microsoft.com/en-us/azure/ai-foundry/",
            "https://learn.microsoft.com/en-us/azure/ai-services/openai/",
        ),
        sitemap_urls=("https://learn.microsoft.com/sitemap.xml",),
    ),
    DocSource(
        id="github",
        name="GitHub Docs",
        official_domains=("docs.github.com",),
        seed_urls=("https://docs.github.com/",),
        llms_urls=("https://docs.github.com/llms.txt",),
        sitemap_urls=("https://docs.github.com/sitemap.xml",),
    ),
    DocSource(
        id="notion",
        name="Notion Developers",
        official_domains=("developers.notion.com",),
        seed_urls=(
            "https://developers.notion.com/",
            "https://developers.notion.com/guides/mcp/overview",
        ),
        llms_urls=("https://developers.notion.com/llms.txt",),
        llms_full_urls=("https://developers.notion.com/llms-full.txt",),
        sitemap_urls=("https://developers.notion.com/sitemap.xml",),
    ),
    DocSource(
        id="mcp",
        name="Model Context Protocol",
        official_domains=("modelcontextprotocol.io",),
        seed_urls=(
            "https://modelcontextprotocol.io/docs",
            "https://modelcontextprotocol.io/specification/2025-11-25",
        ),
        llms_urls=("https://modelcontextprotocol.io/llms.txt",),
        llms_full_urls=("https://modelcontextprotocol.io/llms-full.txt",),
        sitemap_urls=("https://modelcontextprotocol.io/sitemap.xml",),
        version_url="https://modelcontextprotocol.io/specification",
    ),
    DocSource(
        id="vercel",
        name="Vercel",
        official_domains=("vercel.com",),
        seed_urls=("https://vercel.com/docs", "https://vercel.com/docs/ai-sdk"),
        llms_urls=("https://vercel.com/llms.txt",),
        llms_full_urls=("https://vercel.com/llms-full.txt",),
        sitemap_urls=("https://vercel.com/sitemap.xml",),
    ),
    DocSource(
        id="cloudflare",
        name="Cloudflare Developers",
        official_domains=("developers.cloudflare.com",),
        seed_urls=(
            "https://developers.cloudflare.com/",
            "https://developers.cloudflare.com/workers-ai/",
        ),
        llms_urls=("https://developers.cloudflare.com/llms.txt",),
        llms_full_urls=("https://developers.cloudflare.com/llms-full.txt",),
        sitemap_urls=("https://developers.cloudflare.com/sitemap.xml",),
    ),
    DocSource(
        id="cursor",
        name="Cursor",
        official_domains=("docs.cursor.com", "cursor.com"),
        seed_urls=("https://docs.cursor.com/",),
        llms_urls=("https://docs.cursor.com/llms.txt",),
        llms_full_urls=("https://docs.cursor.com/llms-full.txt",),
        sitemap_urls=("https://docs.cursor.com/sitemap.xml",),
    ),
)


def get_source(source_id: str | None) -> DocSource | None:
    if not source_id:
        return None
    for source in SOURCES:
        if source.id == source_id:
            return source
    return None
