"""Moving, snapping and resizing for Relic's borderless window on Windows.

Moving and resizing are handed to Windows itself (the same move/size loop a
normal title bar uses), so they keep working however the mouse moves and
whatever the page sees. On top of that, Relic adds what a borderless window
doesn't get for free:

  * let go at the top edge of the screen   -> maximize (taskbar stays visible)
  * let go at the left or right edge       -> snap to that half of the screen
  * drag a maximized/snapped window        -> it pops back to its normal size
  * double-click the title bar             -> maximize / restore

Everything that touches the window runs on the window's own UI thread.
Not on Windows: no-ops.
"""

from __future__ import annotations

import os
import sys

from reliclog import log

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
MONITOR_DEFAULTTONEAREST = 2
WM_NCLBUTTONDOWN = 0x00A1
HIT = {"caption": 2, "w": 10, "e": 11, "n": 12, "nw": 13, "ne": 14, "s": 15, "sw": 16, "se": 17}
EDGE_PX = 2  # how close to the screen edge counts as "at the edge"


class WinSnap:
    def __init__(self, title: str = "Relic"):
        self.title = title
        self.window = None          # pywebview window
        self._hwnd = None
        self.state = "normal"       # normal | max | left | right
        self._restore = None        # (x, y, w, h) before max/snap

    # ---------------------------------------------------------------- helpers
    def hwnd(self):
        if self._hwnd or not IS_WIN:
            return self._hwnd
        try:
            h = self.window.native.Handle
            self._hwnd = int(h.ToInt64()) if hasattr(h, "ToInt64") else int(h)
            log.info("window handle from form: %s", self._hwnd)
            return self._hwnd
        except Exception as e:
            log.warning("form handle unavailable (%r); searching by title", e)
        pid, found = os.getpid(), []

        def cb(h, _):
            p = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid and user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(h, buf, 256)
                if buf.value == self.title:
                    found.append(h)
                    return False
            return True

        user32.EnumWindows(EnumProc(cb), 0)
        self._hwnd = found[0] if found else None
        log.info("window handle by title: %s", self._hwnd)
        return self._hwnd

    @staticmethod
    def _cursor():
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return pt

    def _rect(self):
        r = wintypes.RECT()
        user32.GetWindowRect(self.hwnd(), ctypes.byref(r))
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    @staticmethod
    def _monitor(pt=None, hwnd=None):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        h = (user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST) if pt is not None
             else user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST))
        user32.GetMonitorInfoW(h, ctypes.byref(mi))
        return mi.rcMonitor, mi.rcWork

    def _place(self, x, y, w=None, h=None):
        """Call on the UI thread."""
        flags = SWP_NOZORDER | SWP_NOACTIVATE | (SWP_NOSIZE if w is None else 0)
        if not user32.SetWindowPos(self.hwnd(), None, int(x), int(y), int(w or 0), int(h or 0), flags):
            log.warning("SetWindowPos failed: error %s", ctypes.GetLastError())

    def _scale(self) -> float:
        try:
            return user32.GetDpiForWindow(self.hwnd()) / 96
        except Exception:
            return 1.0

    def on_ui(self, fn):
        """Run fn on the window's UI thread and return its result."""
        out = {}

        def run():
            try:
                out["v"] = fn()
            except Exception as e:  # never let an error escape into WinForms
                log.exception("window action failed")
                out["e"] = e
        try:
            form = self.window.native
            if form.InvokeRequired:
                from System import Action  # pythonnet, loaded by pywebview on Windows
                form.Invoke(Action(run))
            else:
                run()
        except Exception as e:
            log.warning("couldn't run on the UI thread (%r); running directly", e)
            run()
        return out.get("v")

    # --------------------------------------------------------------- fullscreen
    def fullscreen(self, on: bool) -> bool:
        """Borderless full screen on the window's monitor: no title bar, frame or edge lines.

        The WinForms form loses its frame and is maximized (a maximized frameless window
        covers the whole monitor, taskbar included). Windows 11 also draws a thin accent
        border and rounds the corners of normal windows; both are switched off while full
        screen and restored afterwards."""
        if not IS_WIN:
            return False

        def dwm(hwnd, attr, value):
            try:
                v = ctypes.c_uint(value)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
            except Exception:
                pass  # Windows 10: no such attributes, and no border to remove

        def do():
            from System.Windows.Forms import FormBorderStyle, FormWindowState  # pythonnet
            form = self.window.native
            hwnd = self.hwnd()
            if on:
                if getattr(self, "_fs", None) is None:
                    self._fs = (form.FormBorderStyle, form.WindowState, form.Bounds, form.TopMost)
                form.WindowState = FormWindowState.Normal  # re-maximize after the frame changes
                form.FormBorderStyle = getattr(FormBorderStyle, "None")
                form.WindowState = FormWindowState.Maximized
                dwm(hwnd, 34, 0xFFFFFFFE)  # DWMWA_BORDER_COLOR = none
                dwm(hwnd, 33, 1)           # DWMWA_WINDOW_CORNER_PREFERENCE = don't round
                form.Activate()
                self._focus_browser(form)  # keyboard and controller input go to the page, not the bare form
            elif getattr(self, "_fs", None) is not None:
                style, state, bounds, top = self._fs
                self._fs = None
                dwm(hwnd, 34, 0xFFFFFFFF)  # default border
                dwm(hwnd, 33, 0)           # default corners
                form.WindowState = FormWindowState.Normal
                form.FormBorderStyle = style
                form.Bounds = bounds
                form.WindowState = state
                form.TopMost = top
                self._focus_browser(form)
            log.info("full screen %s: bounds %s", "on" if on else "off", form.Bounds)
            return True
        return bool(self.on_ui(do))

    @staticmethod
    def _focus_browser(form):
        """Give focus to the WebView2 control inside the form (changing the frame leaves it on the form)."""
        def walk(c):
            for child in c.Controls:
                if "WebView2" in child.GetType().Name:
                    return child
                found = walk(child)
                if found is not None:
                    return found
            return None
        try:
            wv = walk(form)
            if wv is not None:
                wv.Focus()
        except Exception:
            log.exception("couldn't focus the page")

    def foreground(self) -> bool:
        """Is Relic the window you're using right now?"""
        if not IS_WIN:
            return True
        try:
            fg = ctypes.windll.user32.GetForegroundWindow()
            h = self.hwnd()
            if not h:
                return True
            return int(fg or 0) == int(h) or int(ctypes.windll.user32.GetAncestor(fg, 2) or 0) == int(h)  # GA_ROOT
        except Exception:
            return True

    # --------------------------------------------------------------- actions
    def _maximize(self, pt=None, save=True):
        if save and self.state == "normal":
            self._restore = self._rect()
        _, work = self._monitor(pt=pt) if pt is not None else self._monitor(hwnd=self.hwnd())
        self._place(work.left, work.top, work.right - work.left, work.bottom - work.top)
        self.state = "max"

    def _snap(self, side, pt, save=True):
        if save and self.state == "normal":
            self._restore = self._rect()
        _, work = self._monitor(pt=pt)
        full = work.right - work.left
        half = full // 2
        x = work.left if side == "left" else work.left + half
        self._place(x, work.top, half if side == "left" else full - half, work.bottom - work.top)
        self.state = side

    def _restore_size(self):
        if self._restore:
            self._place(*self._restore)
        self.state = "normal"

    def toggle_maximize(self):
        if not IS_WIN or not self.hwnd():
            return self.state

        def do():
            if self.state == "normal":
                self._maximize()
            else:
                self._restore_size()
            return self.state
        return self.on_ui(do)

    # ------------------------------------------------------------------ drag
    def drag(self):
        """Start a title-bar drag. Call while the left button is held; returns when it's released."""
        if not IS_WIN or not self.hwnd():
            return self.state

        def do():
            hwnd = self.hwnd()
            pre = self._rect() if self.state == "normal" else None
            if self.state != "normal":
                # Pop out of maximized/snapped at the normal size, keeping the cursor
                # at the same spot across the title bar.
                pt = self._cursor()
                x, y, w, h = self._rect()
                frac = (pt.x - x) / max(w, 1)
                rw, rh = (self._restore[2], self._restore[3]) if self._restore else (int(w * .7), int(h * .7))
                grab_y = min(pt.y - y, int(20 * self._scale()))
                self._place(pt.x - int(rw * frac), pt.y - grab_y, rw, rh)
                self.state = "normal"
            pt = self._cursor()
            # Hand the drag to Windows' own move loop. SendMessage returns when the
            # mouse button is released.
            user32.ReleaseCapture()
            user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HIT["caption"],
                                (pt.x & 0xFFFF) | ((pt.y & 0xFFFF) << 16))
            pt = self._cursor()
            mon, _ = self._monitor(pt=pt)
            target = None
            if pt.y <= mon.top + EDGE_PX:
                target = "max"
            elif pt.x <= mon.left + EDGE_PX:
                target = "left"
            elif pt.x >= mon.right - 1 - EDGE_PX:
                target = "right"
            if target:
                # Remember where the window was before this drag, like Windows does.
                if pre:
                    self._restore = pre
                elif self._restore is None:
                    self._restore = self._rect()
                if target == "max":
                    self._maximize(pt, save=False)
                else:
                    self._snap(target, pt, save=False)
            return self.state
        return self.on_ui(do)

    # ---------------------------------------------------------------- resize
    def resize(self, edge: str):
        """Start a resize from an edge/corner (n, s, e, w, ne, nw, se, sw). Returns when released."""
        if not IS_WIN or not self.hwnd() or edge not in HIT or edge == "caption":
            return self.state

        def do():
            self.state = "normal"
            pt = self._cursor()
            user32.ReleaseCapture()
            user32.SendMessageW(self.hwnd(), WM_NCLBUTTONDOWN, HIT[edge],
                                (pt.x & 0xFFFF) | ((pt.y & 0xFFFF) << 16))
            return self.state
        return self.on_ui(do)
