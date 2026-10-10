import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from official_docs_mcp import server
from official_docs_mcp.server import call_tool, result_for


class ServerTests(unittest.TestCase):
    def test_configure_stdio_accepts_stringio(self) -> None:
        """Tests and embedders may replace standard streams without reconfigure()."""
        with (
            patch("official_docs_mcp.server.sys.stdin", io.StringIO()),
            patch("official_docs_mcp.server.sys.stdout", io.StringIO()),
        ):
            server.configure_stdio()

    def test_stdio_uses_utf8_when_pythonioencoding_is_cp932(self) -> None:
        """Windows console encoding must not corrupt UTF-8 MCP JSON-RPC."""
        request = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "未登録🚀", "arguments": {}},
                },
                ensure_ascii=False,
            ).encode("utf-8")
            + b"\n"
        )
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp932"
        environment["PYTHONUTF8"] = "0"
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, "-m", "official_docs_mcp.server"],
            cwd=root,
            env=environment,
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(
            completed.returncode, 0, completed.stderr.decode("utf-8", errors="replace")
        )
        response = json.loads(completed.stdout.decode("utf-8"))
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["error"], "Unknown tool: 未登録🚀")

    def test_stdio_emits_utf8_when_pythonioencoding_is_cp932(self) -> None:
        """A non-CP932 response character must not terminate the stdio server."""
        request = (
            json.dumps(
                {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "未登録🚀"}},
                ensure_ascii=False,
            ).encode("utf-8")
            + b"\n"
        )
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp932"
        environment["PYTHONUTF8"] = "0"
        root = Path(__file__).resolve().parents[1]
        launcher = (
            "from official_docs_mcp import server; "
            "server.result_for = lambda _: {'jsonrpc': '2.0', 'id': 8, "
            "'result': {'message': 'Windows — UTF-8'}}; server.main()"
        )
        completed = subprocess.run(
            [sys.executable, "-c", launcher],
            cwd=root,
            env=environment,
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(
            completed.returncode, 0, completed.stderr.decode("utf-8", errors="replace")
        )
        response = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(response["result"]["message"], "Windows — UTF-8")

    def test_initialize(self) -> None:
        response = result_for(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response["result"]["serverInfo"]["name"], "official-docs-mcp")

    def test_tools_list(self) -> None:
        response = result_for({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertIsNotNone(response)
        assert response is not None
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertLessEqual(
            {
                "list_sources",
                "search_official_docs",
                "fetch_official_doc",
                "check_freshness",
                "collect_official_docs",
            },
            names,
        )

    def test_tool_failure_does_not_expose_traceback(self) -> None:
        """Replacing the protocol error response must not reveal implementation details."""
        response = call_tool("fetch_official_doc", {})
        payload = json.loads(response["content"][0]["text"])

        self.assertTrue(response["isError"])
        self.assertEqual(payload["error"], "Request failed.")
        self.assertNotIn("traceback", payload)


if __name__ == "__main__":
    unittest.main()
