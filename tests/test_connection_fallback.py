import io
import socket
import ssl
import unittest
from unittest.mock import patch

from official_docs_mcp.fetcher import fetch_searxng_url, fetch_url


class ConnectionFallbackTests(unittest.TestCase):
    def fetch_fixture(
        self,
        addresses: list[str],
        *,
        local: bool = False,
        tls: bool = True,
        fail_all: bool = False,
        tls_error: bool = False,
        response_error: bool = False,
    ):
        host = "localhost" if local else "platform.openai.com"
        port = 8080 if local else 443
        url = f"{'https' if tls else 'http'}://{host}:{port}/docs"
        records = [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (address, port, 0, 0) if ":" in address else (address, port),
            )
            for address in addresses
        ]
        attempts = []
        tls_hosts = []
        sent = []
        sockets = []

        class ResponseSocket:
            closed = False

            def sendall(self, data):
                sent.append(data)

            def makefile(self, mode):
                if response_error:
                    raise OSError("fixture response failed")
                return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\ndocs")

            def close(self):
                self.closed = True

        def connect(endpoint, timeout):
            address, requested_port = endpoint
            self.assertEqual(requested_port, port)
            attempts.append(address)
            if fail_all or (not tls_error and not response_error and address == addresses[0]):
                raise ConnectionRefusedError("fixture address unavailable")
            result = ResponseSocket()
            sockets.append(result)
            return result

        def wrap_socket(sock, *, server_hostname):
            tls_hosts.append(server_hostname)
            if tls_error:
                raise ssl.SSLCertVerificationError("fixture certificate invalid")
            return sock

        with (
            patch("official_docs_mcp.fetcher.socket.getaddrinfo", return_value=records) as dns,
            patch("official_docs_mcp.fetcher.socket.create_connection", side_effect=connect),
            patch("official_docs_mcp.fetcher.ssl.SSLContext.wrap_socket", side_effect=wrap_socket),
        ):
            result = fetch_searxng_url(url, url) if local else fetch_url(url)

        dns.assert_called_once_with(host, port, type=socket.SOCK_STREAM)
        return result, attempts, tls_hosts, sent, sockets

    def test_tries_remaining_validated_addresses_for_official_and_local_services(self):
        for local, tls, addresses in [
            (False, True, ["2001:4860:4860::8888", "8.8.8.8"]),
            (True, False, ["::1", "127.0.0.1"]),
            (True, True, ["::1", "127.0.0.1"]),
        ]:
            with self.subTest(local=local, tls=tls):
                result, attempts, tls_hosts, sent, sockets = self.fetch_fixture(
                    addresses, local=local, tls=tls
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["body"], b"docs")
                self.assertEqual(attempts, addresses)
                self.assertEqual(
                    tls_hosts, ["localhost" if local else "platform.openai.com"] if tls else []
                )
                self.assertEqual(len(sent), 1)
                self.assertTrue(all(sock.closed for sock in sockets))

    def test_does_not_retry_private_addresses_for_official_docs(self):
        result, attempts, _, _, _ = self.fetch_fixture(["8.8.8.8", "127.0.0.1"])
        self.assertFalse(result["ok"])
        self.assertEqual(attempts, ["8.8.8.8"])

    def test_all_connect_failures_return_a_safe_error(self):
        addresses = ["2001:4860:4860::8888", "8.8.8.8"]
        result, attempts, _, sent, _ = self.fetch_fixture(addresses, fail_all=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Unable to retrieve URL.")
        self.assertEqual(attempts, addresses)
        self.assertEqual(sent, [])

    def test_certificate_failure_closes_socket_without_retrying(self):
        result, attempts, tls_hosts, sent, sockets = self.fetch_fixture(
            ["8.8.8.8", "8.8.4.4"], tls_error=True
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Unable to retrieve URL.")
        self.assertEqual(attempts, ["8.8.8.8"])
        self.assertEqual(tls_hosts, ["platform.openai.com"])
        self.assertEqual(sent, [])
        self.assertTrue(sockets[0].closed)

    def test_does_not_retry_after_sending_a_request(self):
        result, attempts, _, sent, sockets = self.fetch_fixture(
            ["8.8.8.8", "8.8.4.4"], response_error=True
        )
        self.assertFalse(result["ok"])
        self.assertEqual(attempts, ["8.8.8.8"])
        self.assertEqual(len(sent), 1)
        self.assertTrue(sockets[0].closed)


if __name__ == "__main__":
    unittest.main()
