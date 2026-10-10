import socket
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from official_docs_mcp.fetcher import (
    MAX_BODY_BYTES,
    SafeFetchError,
    _request_once,
    collect_candidate_urls,
    fetch_searxng_url,
    fetch_url,
    is_official_url,
    response_to_document,
    search_official_docs,
)
from official_docs_mcp.sources import get_source


class FetcherTests(unittest.TestCase):
    def test_fetch_url_rejects_non_https_url_before_network_access(self) -> None:
        """Removing the scheme gate must not permit an HTTP request."""
        with patch("official_docs_mcp.fetcher._request_once") as request_once:
            result = fetch_url("http://platform.openai.com/docs")

        self.assertFalse(result["ok"])
        self.assertIn("blocked", result["error"].lower())
        request_once.assert_not_called()

    def test_fetch_url_rejects_credentials_before_network_access(self) -> None:
        """Removing the credential gate must not permit userinfo-bearing URLs."""
        with patch("official_docs_mcp.fetcher._request_once") as request_once:
            result = fetch_url("https://user@platform.openai.com/docs")

        self.assertFalse(result["ok"])
        self.assertIn("blocked", result["error"].lower())
        request_once.assert_not_called()

    def test_fetch_url_rejects_nonstandard_port_before_network_access(self) -> None:
        """Removing the port gate must not connect to an alternate service."""
        with patch("official_docs_mcp.fetcher._request_once") as request_once:
            result = fetch_url("https://platform.openai.com:444/docs")

        self.assertFalse(result["ok"])
        self.assertIn("blocked", result["error"].lower())
        request_once.assert_not_called()

    def test_fetch_url_returns_safe_error_for_malformed_url_type(self) -> None:
        """Malformed input must not escape the protocol boundary."""
        result = fetch_url({})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Request blocked by URL safety policy.")

    def test_official_domain_matching(self) -> None:
        source = get_source("openai")
        self.assertIsNotNone(source)
        assert source is not None
        self.assertTrue(is_official_url("https://platform.openai.com/docs/api-reference", source))
        self.assertTrue(is_official_url("https://docs.anthropic.com/en/api/messages"))
        self.assertFalse(is_official_url("https://example.com/platform.openai.com/docs", source))
        self.assertFalse(is_official_url("http://platform.openai.com/docs", source))
        self.assertFalse(is_official_url("https://user@platform.openai.com/docs", source))

    def test_fetch_url_rejects_redirect_outside_official_domains_before_following(self) -> None:
        """Removing redirect validation must not fetch a redirect destination."""
        dns_result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        with (
            patch("official_docs_mcp.fetcher.socket.getaddrinfo", return_value=dns_result),
            patch(
                "official_docs_mcp.fetcher._request_once",
                return_value=(302, {"location": "https://example.com/internal"}, b""),
            ) as request_once,
        ):
            result = fetch_url("https://platform.openai.com/docs")

        self.assertFalse(result["ok"])
        self.assertIn("blocked", result["error"].lower())
        request_once.assert_called_once()

    def test_fetch_url_connects_to_the_validated_dns_address(self) -> None:
        """Replacing the resolved address must change the socket connection target."""
        dns_result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        with (
            patch("official_docs_mcp.fetcher.socket.getaddrinfo", return_value=dns_result),
            patch(
                "official_docs_mcp.fetcher._request_once", return_value=(200, {}, b"docs")
            ) as request_once,
        ):
            result = fetch_url("https://platform.openai.com/docs")

        self.assertTrue(result["ok"])
        self.assertEqual(request_once.call_args.args[1], "8.8.8.8")

    def test_fetch_url_rejects_private_dns_address_before_network_access(self) -> None:
        """Removing the public-address check must not allow a private destination."""
        dns_result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with (
            patch("official_docs_mcp.fetcher.socket.getaddrinfo", return_value=dns_result),
            patch("official_docs_mcp.fetcher._request_once") as request_once,
        ):
            result = fetch_url("https://platform.openai.com/docs")

        self.assertFalse(result["ok"])
        self.assertIn("blocked", result["error"].lower())
        request_once.assert_not_called()

    def test_request_once_stops_reading_at_body_limit(self) -> None:
        """Removing the bounded read must allow an oversized response into memory."""

        class LargeResponse:
            status = 200

            def getheaders(self) -> list[tuple[str, str]]:
                return []

            def read(self, size: int) -> bytes:
                if size != MAX_BODY_BYTES + 1:
                    raise AssertionError("response body read was not bounded")
                return b"x" * (MAX_BODY_BYTES + 1)

        class LargeResponseConnection:
            def request(self, *args: object, **kwargs: object) -> None:
                return None

            def getresponse(self) -> LargeResponse:
                return LargeResponse()

            def close(self) -> None:
                return None

        with patch(
            "official_docs_mcp.fetcher.VerifiedHTTPSConnection",
            return_value=LargeResponseConnection(),
        ):
            with self.assertRaises(SafeFetchError):
                _request_once(urlsplit("https://platform.openai.com/docs"), "8.8.8.8", "GET")

    def test_searxng_redirect_cannot_leave_explicitly_configured_service(self) -> None:
        """Removing the SearXNG origin check must allow an arbitrary redirect target."""
        with patch(
            "official_docs_mcp.fetcher._request_once",
            return_value=(302, {"location": "http://example.com/search"}, b""),
        ) as request_once:
            result = fetch_searxng_url("http://127.0.0.1:8080/search", "http://127.0.0.1:8080")

        self.assertFalse(result["ok"])
        self.assertIn("blocked", result["error"].lower())
        request_once.assert_called_once()

    def test_configured_local_searxng_remains_available(self) -> None:
        """Removing the explicit local-service exception must break a configured SearXNG."""
        with patch(
            "official_docs_mcp.fetcher._request_once", return_value=(200, {}, b'{"results": []}')
        ) as request_once:
            result = fetch_searxng_url("http://127.0.0.1:8080/search", "http://127.0.0.1:8080")

        self.assertTrue(result["ok"])
        self.assertEqual(request_once.call_args.args[0].scheme, "http")

    def test_configured_local_https_searxng_remains_available(self) -> None:
        """Applying the public-only DNS rule to configured SearXNG breaks local TLS."""
        dns_result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8443))]
        with (
            patch("official_docs_mcp.fetcher.socket.getaddrinfo", return_value=dns_result),
            patch(
                "official_docs_mcp.fetcher._request_once",
                return_value=(200, {}, b'{"results": []}'),
            ),
        ):
            result = fetch_searxng_url("https://127.0.0.1:8443/search", "https://127.0.0.1:8443")

        self.assertTrue(result["ok"])

    def test_html_extraction_and_hash(self) -> None:
        fetched = {
            "ok": True,
            "url": "https://modelcontextprotocol.io/docs",
            "status": 200,
            "headers": {"content-type": "text/html", "etag": "abc"},
            "body": (
                b"<html><script>ignore()</script><h1>MCP Docs</h1>"
                b"<p>Hello <a href='/specification'>spec</a></p></html>"
            ),
            "retrieved_at": "2026-06-22T00:00:00+00:00",
        }
        doc = response_to_document("https://modelcontextprotocol.io/docs", fetched)
        self.assertTrue(doc["official"])
        self.assertIn("MCP Docs", doc["text"])
        self.assertNotIn("ignore", doc["text"])
        self.assertEqual(doc["links"][0]["url"], "https://modelcontextprotocol.io/specification")
        self.assertTrue(doc["sha256"])

    def test_unknown_source_is_reported(self) -> None:
        result = search_official_docs("messages api", "missing-source")
        self.assertFalse(result["ok"])
        self.assertIn("Unknown source_id", result["error"])

    def test_llms_full_urls_are_first_class_candidates(self) -> None:
        source = get_source("mcp")
        self.assertIsNotNone(source)
        assert source is not None
        self.assertIn("https://modelcontextprotocol.io/llms-full.txt", source.llms_full_urls)
        candidates = collect_candidate_urls(source, limit=2)
        self.assertEqual(candidates[0], "https://modelcontextprotocol.io/llms-full.txt")
        self.assertEqual(len(candidates), 2)


if __name__ == "__main__":
    unittest.main()
