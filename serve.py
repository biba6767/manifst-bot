"""Entry point for Render web services: keep a health port open while the bot polls."""

import asyncio
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import main


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args: object) -> None:
        pass


def start_health_server() -> None:
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def keep_awake() -> None:
    url = os.environ.get("RENDER_EXTERNAL_URL", "https://manifst-bot.onrender.com").rstrip("/") + "/"
    while True:
        time.sleep(300)
        try:
            urllib.request.urlopen(url, timeout=10).read()
        except Exception:
            pass


if __name__ == "__main__":
    start_health_server()
    threading.Thread(target=keep_awake, daemon=True).start()
    asyncio.run(main.main())
