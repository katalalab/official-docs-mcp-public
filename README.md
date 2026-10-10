# official-docs-mcp

公式ドキュメントだけを対象に、最新版探索・取得・引用用メタデータを返すローカルMCP serverです。

## 目的

- AI/CLI/開発ツール系の公式ドキュメントを横断検索する
- 取得日、URL、source種別、公式ドメイン判定を返す
- SearXNGがある場合は検索バックエンドとして使う
- SearXNGがない場合も `llms.txt`、`llms-full.txt`、sitemap、seed URLから直接探索する

## Tools

- `list_sources`: 登録済み公式ソース一覧
- `search_official_docs`: 公式docsを検索
- `fetch_official_doc`: URLまたは検索結果URLを取得して本文化
- `check_freshness`: URLの `ETag` / `Last-Modified` / content hash を確認
- `collect_official_docs`: 公式docs URLカタログをsource横断で収集し、任意で `.cache/catalog.json` に保存

## SearXNG

任意です。使う場合だけ環境変数を設定します。

```sh
export OFFICIAL_DOCS_SEARXNG_URL="http://127.0.0.1:8080"
```

SearXNG未設定時は、各sourceの `llms.txt` / `llms-full.txt` / sitemap / seed URLを直接取得して簡易検索します。

## 取得時の安全性

公式ドキュメントの取得は HTTPS、登録済み公式ホスト、標準 HTTPS ポートだけを許可します。接続前と各 redirect 後に DNS 解決結果が公開アドレスであることを確認し、その検証済みアドレスへ TLS 接続するため、URL の userinfo、private/loopback 宛て、非公式ホスト、許可条件外への redirect は取得しません。応答本文は 2 MiB で打ち切ります。

`OFFICIAL_DOCS_SEARXNG_URL` は明示的に設定した検索サービスだけへの別経路です。ローカル HTTP の SearXNG は利用できますが、redirect は同一 origin に限定します。検索結果から本文を取得する際は、通常の公式 URL 検証を必ず通します。

## 起動

```sh
cd /path/to/official-docs-mcp
python3 -m official_docs_mcp.server
```

## 検証

```sh
bash scripts/verify.sh
```

この verifier は依存追加なしで、`official_docs_mcp/*.py` の構文確認と `tests/` の unittest を実行します。`.python-version` に固定 Python があればそれを使います。

Codex/Claude/Cursor等には stdio MCP server として登録します。

```json
{
  "mcpServers": {
    "official-docs": {
      "command": "python3",
      "args": ["-m", "official_docs_mcp.server"],
      "cwd": "/path/to/official-docs-mcp",
      "env": {
        "OFFICIAL_DOCS_SEARXNG_URL": ""
      }
    }
  }
}
```

Codex への登録例:

```sh
codex mcp add official-docs --env PYTHONPATH=/path/to/official-docs-mcp -- python3 -m official_docs_mcp.server
```

確認:

```sh
codex mcp get official-docs
```

削除:

```sh
codex mcp remove official-docs
```

## 方針

このMCPは「Web全体の発見」ではなく、「公式ソースへの収束」を狙います。未知の障害やコミュニティ事例は通常のWeb検索、仕様確認・引用・版差分はこのMCP、という使い分けを想定しています。

## Lazy Loading 前提

このMCPは常時ロードしてもtool数は少なめですが、各社公式docsの本文取得は重くなり得ます。MCP clientがlazy/on-demand設定をサポートする場合は、このserverを通常セッション常駐ではなく、docs調査用Agent/Skillにだけ割り当てる運用を推奨します。

```json
{
  "mcpServers": {
    "official-docs": {
      "command": "python3",
      "args": ["-m", "official_docs_mcp.server"],
      "cwd": "/path/to/official-docs-mcp",
      "lazy": true
    }
  }
}
```

`lazy` は全MCP clientの標準設定ではありません。未対応clientでは無視されるかエラーになる可能性があるため、その場合は通常のstdio MCP設定を使ってください。

## カタログ収集

```json
{
  "name": "collect_official_docs",
  "arguments": {
    "source_id": "mcp",
    "limit_per_source": 50,
    "fetch_metadata": true,
    "write_cache": true
  }
}
```

`write_cache` は `/path/to/official-docs-mcp/.cache/catalog.json` だけを書き換えます。認証情報やグローバルMCP設定には触れません。
