"""Local browser application for generating an email from a public website."""

from __future__ import annotations

import argparse
import http.client
import json
import socket
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from campaign import analyze_page, public_addresses, render_email, validate_url


ROOT = Path(__file__).resolve().parent
MAX_PAGE = 1_500_000


def fetch_page(url: str) -> tuple[str, str]:
    """Fetch HTML using a vetted, pinned public IP on each redirect."""
    current = validate_url(url)
    for _ in range(5):
        parts = urlsplit(current)
        addresses = public_addresses(current)
        error = None
        for address in addresses:
            try:
                # Pin the vetted IP while retaining the original Host and TLS SNI.
                class PinnedHTTP(http.client.HTTPConnection):
                    def connect(self):
                        self.sock = socket.create_connection((address, self.port), timeout=10)
                class PinnedHTTPS(http.client.HTTPSConnection):
                    def connect(self):
                        raw = socket.create_connection((address, self.port), timeout=10)
                        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
                conn = (PinnedHTTPS if parts.scheme == "https" else PinnedHTTP)(parts.hostname, parts.port, timeout=10)
                try:
                    path = parts.path or "/"
                    if parts.query:
                        path += "?" + parts.query
                    conn.request("GET", path, headers={"Host": parts.netloc, "User-Agent": "Mozilla/5.0 (compatible; EmailBuilder/1.0)", "Accept": "text/html", "Accept-Encoding": "identity"})
                    response = conn.getresponse()
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.getheader("Location")
                        if not location:
                            raise ValueError("Redirección sin destino.")
                        current = validate_url(urljoin(current, location))
                        break
                    if response.status >= 400:
                        raise ValueError(f"La web respondió con HTTP {response.status}.")
                    if "text/html" not in (response.getheader("Content-Type") or "").lower():
                        raise ValueError("La URL no devuelve una página HTML.")
                    body = response.read(MAX_PAGE + 1)
                    if len(body) > MAX_PAGE:
                        raise ValueError("La página supera el límite de 1,5 MB.")
                    charset = response.headers.get_content_charset() or "utf-8"
                    return current, body.decode(charset, errors="replace")
                finally:
                    conn.close()
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                error = exc
                continue
        else:
            raise ValueError("No se pudo conectar con la web.") from error
    raise ValueError("Demasiadas redirecciones.")


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            body = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src https: http: data:; frame-src 'self' blob:; connect-src 'self'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path != "/api/generate":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 4096:
                    raise ValueError("La petición es demasiado grande o está vacía.")
                payload = json.loads(self.rfile.read(length))
                url = validate_url(payload.get("url", ""))
                final_url, source = fetch_page(url)
                analysis = analyze_page(final_url, source)
                self.send_json({"analysis": analysis, "html": render_email(analysis)})
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json({"error": str(exc)}, 400)
            except Exception:
                self.send_json({"error": "No se pudo analizar la página."}, 502)

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generador local de emails desde una URL")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print(f"Abre http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
