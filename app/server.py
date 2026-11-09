"""Painel web e API local do Ogwiro."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from app.channels import ChannelError, check_telegram, check_whatsapp
from app.engine import Engine
from app.store import PUBLIC, Store

HOST = "127.0.0.1"
PORT = 8787


class App:
    def __init__(self) -> None:
        self.store = Store()
        self.engine = Engine(self.store)


APP = App()


class Handler(BaseHTTPRequestHandler):
    server_version = "Ogwiro/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/session":
            self.respond({"authRequired": bool(APP.store.config["dashboard"].get("token"))})
            return
        if path.startswith("/api/") and not self.authorized():
            self.respond({"authRequired": True, "detail": "Informe a senha do painel."}, 401)
            return
        if path == "/api/config":
            self.respond(APP.store.public())
            return
        if path == "/api/status":
            self.respond(APP.engine.status())
            return
        if path == "/api/offers":
            with APP.store._lock:
                offers = list(reversed(APP.store.offers))
            self.respond({"offers": offers[:200]})
            return
        if path == "/api/logs":
            with APP.store._lock:
                logs = list(reversed(APP.store.logs))
            self.respond({"logs": logs[:200]})
            return
        self.static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/login" and not self.authorized():
            self.respond({"authRequired": True, "detail": "Informe a senha do painel."}, 401)
            return
        payload = self.read_json()
        if path == "/api/login":
            expected = str(APP.store.config["dashboard"].get("token") or "")
            given = str(payload.get("token") or "")
            if expected and not constant_equal(given, expected):
                self.respond({"ok": False, "detail": "Senha incorreta."}, 403)
                return
            self.respond({"ok": True, "token": expected})
            return
        if path == "/api/config":
            try:
                saved = APP.store.save_panel(
                    str(payload.get("shopId") or ""),
                    payload.get("shop") or {},
                    payload.get("dashboard"),
                    payload.get("roster"),
                )
            except KeyError:
                self.respond({"detail": "Grupo não encontrado."}, 404)
                return
            self.respond(saved)
            return
        if path == "/api/shops":
            action = str(payload.get("action") or "")
            try:
                if action == "enable":
                    saved = APP.engine.set_group_enabled(str(payload.get("id") or ""), bool(payload.get("enabled")))
                elif action == "reset":
                    saved = APP.store.reset_shop(str(payload.get("id") or ""), str(payload.get("section") or "all"))
                else:
                    saved = APP.store.mutate_shop(action, payload)
            except KeyError:
                self.respond({"detail": "Grupo não encontrado."}, 404)
                return
            except ValueError as error:
                self.respond({"detail": str(error)}, 400)
                return
            self.respond(saved)
            return
        if path == "/api/bot":
            action = payload.get("action")
            shop_id = str(payload.get("shopId") or "") or APP.store.active_id()
            try:
                if action == "start":
                    APP.engine.set_group_enabled(shop_id, True)
                elif action == "stop":
                    APP.engine.set_group_enabled(shop_id, False)
                else:
                    self.respond({"ok": False, "detail": "Ação inválida."}, 400)
                    return
            except KeyError:
                self.respond({"detail": "Grupo não encontrado."}, 404)
                return
            self.respond({"ok": True, "status": APP.engine.status(shop_id)})
            return
        if path == "/api/cycle":
            names = payload.get("stores")
            if names is not None and not isinstance(names, list):
                names = None
            summary = APP.engine.cycle(shop_id=str(payload.get("shopId") or "") or None, names=names, send=bool(payload.get("send", True)))
            self.respond(summary, 200 if summary.get("ok") else 409)
            return
        if path == "/api/test":
            self.respond(APP.engine.test(payload.get("channel"), str(payload.get("shopId") or "") or None))
            return
        if path == "/api/check":
            self.check_channel(str(payload.get("channel") or ""), str(payload.get("shopId") or "") or None)
            return
        if path == "/api/offers/send":
            self.respond(APP.engine.resend(str(payload.get("id") or ""), str(payload.get("shopId") or "") or None))
            return
        if path == "/api/offers/manual":
            self.respond(APP.engine.publish_manual(payload, send=bool(payload.get("send")), shop_id=str(payload.get("shopId") or "") or None))
            return
        self.respond({"detail": "Rota não encontrada."}, 404)

    def check_channel(self, channel: str, shop_id: str | None = None) -> None:
        config = APP.store.snapshot_shop(shop_id)
        if config is None:
            self.respond({"ok": False, "detail": "Grupo não encontrado."}, 404)
            return
        timeout = config["timing"]["requestTimeoutSec"]
        try:
            if channel == "telegram":
                detail = check_telegram(config["channels"]["telegram"], timeout)
            elif channel == "whatsapp":
                detail = check_whatsapp(config["channels"]["whatsapp"], timeout)
            else:
                self.respond({"ok": False, "detail": "Canal inválido."}, 400)
                return
        except ChannelError as error:
            APP.engine.log("error", str(error), config)
            self.respond({"ok": False, "detail": str(error)})
            return
        APP.engine.log("info", detail, config)
        self.respond({"ok": True, "detail": detail})

    def authorized(self) -> bool:
        expected = str(APP.store.config["dashboard"].get("token") or "")
        if not expected:
            return True
        header = self.headers.get("Authorization") or ""
        given = header[7:].strip() if header.lower().startswith("bearer ") else ""
        return constant_equal(given, expected)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_000_000:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        root = PUBLIC.resolve()
        target = (PUBLIC / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self.respond({"detail": "Não encontrado."}, 404)
            return
        if not target.is_file():
            self.respond({"detail": "Não encontrado."}, 404)
            return
        mime = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "text/javascript",
        }.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        if mime.startswith("text/") or mime.endswith("javascript"):
            mime = f"{mime}; charset=utf-8"
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def respond(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


def constant_equal(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    mismatch = 0
    for a, b in zip(left, right):
        mismatch |= ord(a) ^ ord(b)
    return mismatch == 0


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Ogwiro no ar: http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
    finally:
        APP.engine.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
