"""A fake Ollama on a real local port. `start(**cfg)` returns a server with .url, .posts (every JSON body received, with its path) and .stop().
cfg: models (names for /api/tags), loaded (names for /api/ps), reply (list of chunks), first_delay (seconds before the first chunk, like a model that
has to load), gap (seconds between later chunks), stall_after (stop sending after that many chunks, never finishing), chat_status and chat_body
(answer /api/chat with that HTTP error), reply_fn (a function of the request body returning the chunks), chat_error (a mid-stream {"error": ...} line)."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        cfg = self.server.cfg
        if self.path == "/api/tags":
            return self._json(200, {"models": [{"name": n, "size": 1_300_000_000, "details": {"parameter_size": "1.2B"}} for n in cfg["models"]]})
        if self.path == "/api/ps":
            return self._json(200, {"models": [{"name": n, "size": 1_300_000_000} for n in cfg["loaded"]]})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        cfg = self.server.cfg
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.server.posts.append((self.path, body))
        if self.path == "/api/generate":
            time.sleep(cfg.get("generate_delay", 0))
            return self._json(200, {"done": True})
        if cfg.get("chat_status"):
            return self._json(cfg["chat_status"], {"error": cfg.get("chat_body", "failed")})
        time.sleep(cfg.get("first_delay", 0))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def send(obj):
            raw = json.dumps(obj).encode() + b"\n"
            self.wfile.write(b"%x\r\n%s\r\n" % (len(raw), raw))
            self.wfile.flush()

        try:
            chunks = cfg["reply_fn"](body) if cfg.get("reply_fn") else cfg.get("reply", ["Yes, ", "I can ", "hear you."])
            for i, piece in enumerate(chunks):
                if cfg.get("stall_after") is not None and i >= cfg["stall_after"]:
                    time.sleep(cfg.get("stall_seconds", 30))
                    return
                if i:
                    time.sleep(cfg.get("gap", 0))
                send({"message": {"role": "assistant", "content": piece}, "done": False})
            if cfg.get("chat_error"):
                send({"error": cfg["chat_error"]})
            else:
                send({"message": {"role": "assistant", "content": ""}, "done": True, "prompt_eval_count": 42, "eval_count": len(chunks), "load_duration": 1})
            self.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass


class Fake(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, cfg):
        super().__init__(("127.0.0.1", 0), Handler)
        self.cfg = {"models": ["llama3.2:1b"], "loaded": [], **cfg}
        self.posts = []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"

    def stop(self):
        self.shutdown()
        self.server_close()


def start(**cfg):
    return Fake(cfg)


def closed_port():
    """A port nothing listens on."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
