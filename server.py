"""Tiny local HTTP server that feeds the Relic UI. Binds to 127.0.0.1 only."""

from __future__ import annotations

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import art as artmod
from reliclog import log
from version import VERSION

THEME_META = re.compile(r"@(\w+)\s+([^\n*]+)")


def list_themes(dirs: list[Path]) -> list[dict]:
    themes: dict[str, dict] = {}
    for d in dirs:
        for f in sorted(d.glob("*.css")):
            head = f.read_text(encoding="utf-8", errors="replace")[:600]
            meta = {k: v.strip() for k, v in THEME_META.findall(head)}
            themes[f.stem] = {"id": f.stem, "name": meta.get("name", f.stem.title()),
                              "swatch": meta.get("swatch", "").split()}
    return list(themes.values())


class Context:
    def __init__(self, *, token, ra, library, art, config, meta, sessions, player,
                 ui_dir, theme_dirs, data_dir, window_api=None):
        self.token, self.ra, self.library, self.art = token, ra, library, art
        self.config, self.meta, self.sessions, self.player = config, meta, sessions, player
        self.ui_dir, self.theme_dirs, self.data_dir = ui_dir, theme_dirs, data_dir
        self.window_api = window_api


class Handler(BaseHTTPRequestHandler):
    server_version = "Relic"
    protocol_version = "HTTP/1.1"
    ctx: Context

    def log_message(self, *args):
        pass

    # -- helpers --------------------------------------------------------------
    def _send(self, code, body: bytes, ctype, cache="no-store", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _file(self, path: Path, cache="max-age=86400"):
        try:
            data = path.read_bytes()
        except OSError:
            return self._send(404, b"not found", "text/plain")
        self._send(200, data, mimetypes.guess_type(path.name)[0] or "application/octet-stream", cache)

    def _safe(self, root: Path, rel: str) -> Path | None:
        p = (root / rel).resolve()
        return p if p.is_file() and root.resolve() in p.parents else None

    def _host_ok(self) -> bool:
        """Only answer requests addressed to this PC (blocks DNS-rebinding pages)."""
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _authed(self) -> bool:
        return self.headers.get("X-Relic-Token") == self.ctx.token

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n or n > 1 << 20:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return {}

    # -- GET ------------------------------------------------------------------
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        try:
            self._get()
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as e:
            log.exception("GET %s failed", self.path)
            try:
                self._json({"ok": False, "error": f"Something went wrong ({type(e).__name__})"}, 500)
            except OSError:
                pass

    do_HEAD = do_GET

    def _get(self):
        parts = urlsplit(self.path)
        path = parts.path
        c = self.ctx
        if path in ("/", "/index.html"):
            html = (c.ui_dir / "index.html").read_text(encoding="utf-8")
            html = html.replace("{{TOKEN}}", c.token).replace("{{VERSION}}", VERSION)
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        if path.startswith("/ui/"):
            p = self._safe(c.ui_dir, path[4:])
            return self._file(p, "no-cache") if p else self._send(404, b"", "text/plain")
        if path.startswith("/themes/") and path.endswith(".css"):
            for d in reversed(c.theme_dirs):
                p = self._safe(d, path[8:])
                if p:
                    return self._file(p, "no-cache")
            return self._send(404, b"", "text/css")
        m = re.fullmatch(r"/art/([0-9a-f]{12})/(\w+)", path)
        if m:
            g = c.library.get(m[1])
            s = g and c.library.system(g["system"])
            p = c.art.find(g, s.db, m[2]) if g and s else None
            return self._file(p, "max-age=3600") if p else self._send(404, b"", "text/plain", "max-age=120")

        if not path.startswith("/api/"):
            return self._send(404, b"not found", "text/plain")
        if not self._authed():
            return self._json({"ok": False, "error": "forbidden"}, 403)
        if path == "/api/state":
            return self._json(self._state())
        if path == "/api/library":
            refresh = parse_qs(parts.query).get("refresh") == ["1"]
            return self._json(self._library(refresh))
        return self._json({"ok": False, "error": "unknown"}, 404)

    def _state(self) -> dict:
        c = self.ctx
        ra = c.ra
        return {
            "version": VERSION,
            "config": c.config.public(),
            "themes": list_themes(c.theme_dirs),
            "native": bool(c.window_api),
            "playing": c.player.snapshot(),
            "retroarch": {
                "found": ra.found,
                "exe": str(ra.exe or ""),
                "config": str(ra.cfg_path or ""),
                "playlists": str(ra.playlist_dir or ""),
                "cores": len(c.library.cores()),
            },
        }

    def _library(self, refresh=False) -> dict:
        c = self.ctx
        games = c.library.games(refresh)
        totals = c.sessions.totals()
        out = []
        for g in games:
            m = c.meta.get(g["id"])
            t = totals.get(g["id"], {})
            out.append({k: g[k] for k in ("id", "title", "label", "sort", "system", "region", "source")} | {
                "file": Path(g["path"]).name,
                "favorite": bool(m.get("favorite")),
                "hidden": bool(m.get("hidden")),
                "rating": m.get("rating", 0),
                "core": m.get("core", ""),
                "played": t.get("seconds", 0),
                "last": t.get("last", 0),
                "plays": t.get("plays", 0),
            })
        return {"games": out, "systems": c.library.systems_public()}

    # -- POST -----------------------------------------------------------------
    def do_POST(self):
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        if not self._authed():
            return self._json({"ok": False, "error": "forbidden"}, 403)
        path = urlsplit(self.path).path
        body = self._body()
        c = self.ctx
        try:
            if path == "/api/config":
                before = {k: c.config[k] for k in ("retroarch_path", "rom_folders", "hidden_playlists")}
                c.config.update(body)
                if c.config["retroarch_path"] != before["retroarch_path"]:
                    c.ra.find(c.config["retroarch_path"] or None)
                if any(c.config[k] != v for k, v in before.items()):
                    c.library.games(refresh=True)
                return self._json({"ok": True, "config": c.config.public()})
            if path == "/api/meta":
                g = c.library.get(str(body.get("id", "")))
                if not g:
                    return self._json({"ok": False, "error": "No such game"}, 404)
                return self._json({"ok": True, "meta": c.meta.update(g["id"], body.get("changes") or {})})
            if path == "/api/launch":
                return self._launch(str(body.get("id", "")))
            if path == "/api/rescan":
                c.ra.find(c.config["retroarch_path"] or None)
                c.art.forget_misses()
                return self._json({"ok": True} | self._library(refresh=True))
            if path == "/api/customart":
                return self._custom_art(body)
            if path == "/api/window":
                return self._window(body)
            if path == "/api/log":
                log.info("page: %s", str(body.get("msg", ""))[:500])
                return self._json({"ok": True})
            return self._json({"ok": False, "error": "unknown"}, 404)
        except RuntimeError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            log.exception("POST %s failed", path)
            return self._json({"ok": False, "error": f"Something went wrong ({type(e).__name__})"}, 500)

    def _launch(self, gid: str):
        c = self.ctx
        g = c.library.get(gid)
        if not g:
            return self._json({"ok": False, "error": "No such game"}, 404)
        core = c.library.core_path(g, c.meta.get(gid))
        if not core:
            s = c.library.system(g["system"])
            want = ", ".join(s.cores[:2]) if s and s.cores else "a core for this system"
            raise RuntimeError(f"No core installed for {s.name if s else 'this system'}. "
                               f"Get {want} from RetroArch's Online Updater → Core Downloader.")
        fs = bool(c.config["launch_fullscreen"])
        c.player.run(g, lambda: c.ra.launch(core, g["path"], fs))
        return self._json({"ok": True, "core": Path(core).name})

    def _custom_art(self, body):
        c = self.ctx
        g = c.library.get(str(body.get("id", "")))
        kind = body.get("kind", "boxart")
        src = Path(str(body.get("path", "")))
        if not g or kind not in artmod.KINDS:
            return self._json({"ok": False, "error": "No such game"}, 404)
        if src.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp") or not src.is_file():
            raise RuntimeError("Pick a PNG, JPG or WebP picture.")
        c.art.set_custom(g["id"], kind, src.read_bytes(), ".jpg" if src.suffix.lower() == ".jpeg" else src.suffix.lower())
        return self._json({"ok": True})

    def _window(self, body):
        w = self.ctx.window_api
        if not w:
            return self._json({"ok": True, "result": None})
        act = body.get("action")
        if act == "pick_folder":
            return self._json({"ok": True, "result": w.pick_folder()})
        if act == "pick_image":
            return self._json({"ok": True, "result": w.pick_file("image")})
        return self._json({"ok": False, "error": "unknown"}, 404)


def make_server(ctx: Context, port: int = 0) -> ThreadingHTTPServer:
    handler = type("RelicHandler", (Handler,), {"ctx": ctx})
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    srv.daemon_threads = True
    return srv
