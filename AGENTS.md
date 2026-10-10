# official-docs-mcp Instructions

Global baseline: follow the operating baseline configured in your own environment.

Repo-specific rules:

- This server only indexes and fetches public official documentation. Do not add community sources to default `SOURCES`.
- Do not store tokens, cookies, auth headers, SearXNG credentials, or private docs in cache files.
- `OFFICIAL_DOCS_SEARXNG_URL` is optional. The server must work without it by using official `llms.txt`, `llms-full.txt`, sitemap, and seed URLs.
- Verify protocol changes with `python3 -m unittest discover -s tests`.
- Verify network behavior with a small official source, for example `source_id="mcp"` and low limits.
