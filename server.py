"""Tiny local HTTP server that feeds the Relic UI. Binds to 127.0.0.1 only."""

from __future__ import annotations

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import art as artmod
import standalone
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
                 ui_dir, theme_dirs, data_dir, window_api=None, updater=None, restart=None, activate=None):
        self.token, self.ra, self.library, self.art = token, ra, library, art
        self.config, self.meta, self.sessions, self.player = config, meta, sessions, player
        self.ui_dir, self.theme_dirs, self.data_dir = ui_dir, theme_dirs, data_dir
        self.window_api = window_api
        self.updater = updater
        self.restart = restart or (lambda: None)
        self.activate = activate or (lambda: None)


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
            return self._file(p, "max-age=604800") if p else self._send(404, b"", "text/plain", "max-age=300")

        if not path.startswith("/api/"):
            return self._send(404, b"not found", "text/plain")
        if not self._authed():
            return self._json({"ok": False, "error": "forbidden"}, 403)
        if path == "/api/state":
            return self._json(self._state())
        if path == "/api/update":
            return self._json(c.updater.snapshot() if c.updater else {})
        if path == "/api/library":
            q = parse_qs(parts.query)
            if "rev" in q:  # wait for the background rescan to change something
                rev = int(q["rev"][0] or 0)
                if c.library.wait(rev) == rev:
                    return self._json({"ok": True, "unchanged": True, "rev": rev})
            return self._json(self._library())
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
            "update": c.updater.snapshot() if c.updater else None,
            "emulators": self._emulators(),
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
        if refresh:
            c.library.refresh()
        games = c.library.games()
        totals = c.sessions.totals()
        out = []
        for g in games:
            m = c.meta.get(g["id"])
            t = totals.get(g["id"], {})
            out.append({k: g[k] for k in ("id", "title", "label", "sort", "system", "region", "source")} | {
                "added": g.get("added", 0),
                "favorite": bool(m.get("favorite")),
                "hidden": bool(m.get("hidden")),
                "rating": m.get("rating", 0),
                "core": m.get("core", ""),
                "played": t.get("seconds", 0),
                "last": t.get("last", 0),
                "plays": t.get("plays", 0),
            })
        return {"games": out, "systems": c.library.systems_public(), "rev": c.library.rev}

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
                    c.library.refresh()
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
            if path == "/api/update":
                return self._update(body.get("action"))
            if path == "/api/customart":
                return self._custom_art(body)
            if path == "/api/activate":  # a second copy of Relic was opened: show this one
                c.activate()
                return self._json({"ok": True})
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
        if g["system"] in standalone.EMULATORS:
            return self._launch_standalone(g)
        core = c.library.core_path(g, c.meta.get(gid))
        if not core:
            s = c.library.system(g["system"])
            want = ", ".join(s.cores[:2]) if s and s.cores else "a core for this system"
            raise RuntimeError(f"No core installed for {s.name if s else 'this system'}. "
                               f"Get {want} from RetroArch's Online Updater → Core Downloader.")
        fs = bool(c.config["launch_fullscreen"])
        c.player.run(g, lambda: c.ra.launch(core, g["path"], fs))
        return self._json({"ok": True, "core": Path(core).name})

    def _launch_standalone(self, g):
        c = self.ctx
        sid = g["system"]
        emu = standalone.EMULATORS[sid]
        exe = standalone.find(sid, (c.config["emulators"] or {}).get(sid, ""))
        if not exe:
            s = c.library.system(sid)
            raise RuntimeError(f"{s.name} games run in {emu['name']}, which isn't on this PC yet. "
                               f"Get it from {emu['site']}, then choose it in Settings → Other emulators.")
        fs = bool(c.config["launch_fullscreen"])
        c.player.run(g, lambda: standalone.launch(sid, exe, g["path"], fs))
        return self._json({"ok": True, "core": exe.name})

    def _emulators(self) -> list[dict]:
        """Standalone emulators, for Settings: which systems they're for and whether Relic can find them."""
        c = self.ctx
        have = {g["system"] for g in c.library.games()}
        chosen = c.config["emulators"] or {}
        out = []
        for sid, emu in standalone.EMULATORS.items():
            s = c.library.system(sid)
            exe = standalone.find(sid, chosen.get(sid, ""))
            out.append({"id": sid, "system": s.name if s else sid, "name": emu["name"], "site": emu["site"],
                        "exe": str(exe or ""), "has_games": sid in have})
        return out

    def _update(self, action):
        u = self.ctx.updater
        if not u:
            raise RuntimeError("Updates aren't available in this copy")
        if action == "check":
            return self._json({"ok": True} | u.check())
        if action == "apply":
            if not u.apply_async():
                s = u.snapshot()
                raise RuntimeError(s.get("error") or ("Already updating" if s["busy"] else "No update to install"))
            return self._json({"ok": True} | u.snapshot())
        if action == "restart":
            if self.ctx.player.current:
                raise RuntimeError("Close your game first, then restart Relic")
            self.ctx.restart()
            return self._json({"ok": True})
        return self._json({"ok": False, "error": "unknown"}, 404)

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


def make_server(ctx: Context, port: int = 0) -> ThreadingHTTPServer:
    handler = type("RelicHandler", (Handler,), {"ctx": ctx})
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    srv.daemon_threads = True
    return srv
