"""
llm_worker.py — LLM 独立 Worker 进程

常驻后台，复用单例 GaitAgent，通过 HTTP 与主进程通信。
启动: python agent/llm_worker.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from agent import GaitAgent, AthleteProfile

PORT_FILE = Path(tempfile.gettempdir()) / "ironjump_llm_port.txt"
IDLE_TIMEOUT = 600  # 10 分钟

_agent: GaitAgent | None = None
_last_active = time.monotonic()
_agent_lock = threading.RLock()
_state_lock = threading.Lock()
_status = "warming"
_startup_error = ""


def _get_agent() -> GaitAgent:
    global _agent
    with _agent_lock:
        if _agent is None:
            agent = GaitAgent(mode="online")
            agent.warmup_online()
            _agent = agent
        return _agent


def _set_status(status: str, error: str = ""):
    global _status, _startup_error
    with _state_lock:
        _status = status
        _startup_error = error


def _get_status() -> tuple[str, str]:
    with _state_lock:
        return _status, _startup_error


def _warmup_agent():
    try:
        print("[llm_worker] warming up agent...")
        _get_agent()
        _set_status("ready")
        print("[llm_worker] ready")
    except Exception:
        error = traceback.format_exc()
        _set_status("error", error)
        print(f"[llm_worker] warmup failed:\n{error}")


def _touch_active():
    global _last_active
    _last_active = time.monotonic()


def _profile_from_dict(data: dict) -> AthleteProfile:
    return AthleteProfile(
        age=data.get("age", 30),
        weight=data.get("weight", 70.0),
        height=data.get("height", 170.0),
        level=data.get("level", "intermediate"),
        focus_side=data.get("focus_side", ""),
        device_channels=data.get("device_channels", 8),
        history=data.get("history", []),
    )


class _Handler(BaseHTTPRequestHandler):

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            status, error = _get_status()
            payload = {"status": status}
            if error:
                payload["error"] = error
            self._send_json(payload)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # curl on Windows Git Bash may send GBK-encoded Chinese
            try:
                data = json.loads(raw.decode("gbk", errors="replace"))
            except Exception:
                self._send_json({"error": "invalid json"}, 400)
                return

        if self.path == "/chat":
            self._handle_chat(data)
        elif self.path == "/chat_stream":
            self._handle_chat_stream(data)
        elif self.path == "/reset":
            self._handle_reset()
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_chat(self, data: dict):
        _touch_active()
        status, error = _get_status()
        if status != "ready":
            self._send_json({"error": error or "worker not ready", "status": status}, 503)
            return
        agent = _get_agent()
        message = data.get("message", "")
        profile = _profile_from_dict(data.get("athlete", {}))
        try:
            with _agent_lock:
                config, reply = agent.chat_online(message, profile)
            result: dict = {"reply": reply}
            if config is not None:
                result["config"] = config.to_dict()
            self._send_json(result)
        except Exception:
            self._send_json({"error": traceback.format_exc()}, 500)

    def _handle_chat_stream(self, data: dict):
        _touch_active()
        status, error = _get_status()
        if status != "ready":
            self._send_json({"error": error or "worker not ready", "status": status}, 503)
            return
        agent = _get_agent()
        message = data.get("message", "")
        profile = _profile_from_dict(data.get("athlete", {}))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            def on_chunk(text: str):
                chunk = json.dumps({"text": text}, ensure_ascii=False)
                self.wfile.write(f"data: {chunk}\n\n".encode())
                self.wfile.flush()
            with _agent_lock:
                config, reply = agent.chat_online_stream(message, profile, on_chunk)
            done = json.dumps({"reply": reply, "config": config.to_dict() if config else None}, ensure_ascii=False)
            self.wfile.write(f"data: {done}\n\n".encode())
        except Exception:
            err = json.dumps({"error": traceback.format_exc()})
            self.wfile.write(f"data: {err}\n\n".encode())

    def _handle_reset(self):
        _touch_active()
        status, error = _get_status()
        if status != "ready":
            self._send_json({"error": error or "worker not ready", "status": status}, 503)
            return
        agent = _get_agent()
        with _agent_lock:
            agent.reset_chat()
        self._send_json({"status": "ok"})

    def log_message(self, format, *args):
        pass  # silence HTTP log


class _ThreadingServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True


def _idle_monitor():
    while True:
        time.sleep(10)
        if time.monotonic() - _last_active > IDLE_TIMEOUT:
            print("[llm_worker] idle timeout, exiting")
            os._exit(0)


def main():
    server = _ThreadingServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    PORT_FILE.write_text(json.dumps({"pid": os.getpid(), "port": port}))
    print(f"[llm_worker] listening on 127.0.0.1:{port}")

    threading.Thread(target=_warmup_agent, daemon=True).start()
    threading.Thread(target=_idle_monitor, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        PORT_FILE.unlink(missing_ok=True)
        server.server_close()


if __name__ == "__main__":
    main()
