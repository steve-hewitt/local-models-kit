#!/usr/bin/env python3
"""Fake Ollama API and Headroom health endpoints for tests/compare-mock.sh.

Ollama API on 11434:
  GET  /api/tags     -> empty model list (the harness only checks it answers)
  POST /api/generate -> fixed counters: eval_count 100 over 2 s = 50.0 tok/s
  POST /api/show     -> parameters string pinning num_ctx 131072

Headroom proxy on 8787:
  GET  /health       -> 200

No other routes. Anything else gets a 404 JSON error.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class OllamaHandler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": []})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if self.path == "/api/generate":
            self._json({
                "model": "mock",
                "response": "def is_palindrome(s): ...",
                "done": True,
                "eval_count": 100,
                "eval_duration": 2_000_000_000,
                "prompt_eval_count": 10,
                "prompt_eval_duration": 100_000_000,
            })
        elif self.path == "/api/show":
            self._json({"parameters": "num_ctx                        131072\nnum_predict                    8192"})
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, *args):
        pass


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ollama = ThreadingHTTPServer(("127.0.0.1", 11434), OllamaHandler)
    proxy = ThreadingHTTPServer(("127.0.0.1", 8787), HealthHandler)
    import threading
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    ollama.serve_forever()
