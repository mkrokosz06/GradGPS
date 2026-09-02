#!/usr/bin/env python3
"""Preview website/ locally the way GitHub Pages actually serves it.

    python tools/site/serve.py [port]

A plain `python -m http.server` is misleading here: it 404s on /faq because the
file is faq.html. GitHub Pages resolves an extensionless request to <name>.html,
which is what every internal link on the site relies on. This mirrors that:

    /            -> index.html
    /faq         -> faq.html          (the rule http.server lacks)
    /faq/        -> faq/index.html
    anything else-> 404.html, served with a real 404 status

Serves the committed output — run build.py first if you changed a partial.
"""

from __future__ import annotations

import functools
import http.server
import socket
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "website"


class PagesHandler(http.server.SimpleHTTPRequestHandler):
    # HTTP/1.1 + keep-alive, so a page's dozen assets reuse connections instead
    # of racing to open new ones.
    protocol_version = "HTTP/1.1"

    def handle_one_request(self):
        """A browser dropping a connection is normal, not a crash worth logging."""
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def translate_path(self, path: str) -> str:
        local = Path(super().translate_path(path))
        # Directory requests still want their index.html.
        if local.is_dir():
            index = local / "index.html"
            if index.exists():
                return str(index)
        # The GitHub Pages rule: /faq -> faq.html
        if not local.exists() and not local.suffix:
            with_html = local.with_suffix(".html")
            if with_html.exists():
                return str(with_html)
        return str(local)

    def send_error(self, code, message=None, explain=None):
        """Serve the real 404 page, with a real 404 status."""
        custom = SITE / "404.html"
        if code == 404 and custom.exists():
            body = custom.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        super().send_error(code, message, explain)

    def end_headers(self):
        # Never cache during preview, or you'll debug a stale stylesheet.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    handler = functools.partial(PagesHandler, directory=str(SITE))

    # Bound to 0.0.0.0 so you can open the site on your phone over Wi-Fi and see
    # the real mobile layout. That means anyone on this network can reach it --
    # fine for a laptop on home Wi-Fi, not something to leave running on public
    # Wi-Fi. Pass an explicit 127.0.0.1 bind by editing this line if you'd rather.
    lan = None
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))          # no packets sent; just picks the route
        lan = probe.getsockname()[0]
        probe.close()
    except OSError:
        pass
    # Threaded: a single-threaded server serialises requests, and a browser
    # opening several connections at once gets them aborted mid-response —
    # which looks exactly like "the links don't work".
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    http.server.ThreadingHTTPServer.daemon_threads = True
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"GradGPS site preview -> http://localhost:{port}/")
        print(f"serving {SITE}")
        print("Ctrl+C to stop.\n")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
