/* Input and focus: controller, keyboard and mouse all become the same buttons.

   Buttons: up down left right a b x y lb rb start select
   Gamepad (standard mapping): D-pad or left stick moves (hold to repeat, faster the longer you hold),
   A select · B back · X favorite · Y options · LB/RB previous/next system · LT/RT jump by letter
   Start settings · Select sort (on a shelf) or surprise me (at home)
   Keyboard: arrows, Enter, Esc/Backspace, F (X), Tab or I (Y), Q/E (LB/RB), PageUp/PageDown (LT/RT),
   S (Select), comma (Start)
   Controller presses only count while Relic is the window in front. */
(() => {
"use strict";
const { $$ } = R;
const N = (R.nav = { cur: null, handlers: [], usingPad: false });
const BTN = { 0: "a", 1: "b", 2: "x", 3: "y", 4: "lb", 5: "rb", 6: "lt", 7: "rt", 8: "select", 9: "start", 12: "up", 13: "down", 14: "left", 15: "right" };
const KEY = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Enter: "a", " ": "a",
  Escape: "b", Backspace: "b", f: "x", F: "x", Tab: "y", i: "y", I: "y", q: "lb", Q: "lb", e: "rb", E: "rb",
  s: "select", S: "select", ",": "start", PageUp: "lt", PageDown: "rt" };
const DIRS = new Set(["up", "down", "left", "right"]);

/** Handlers get (button) and return true if they used it. Newest first. */
N.on = (fn) => { N.handlers.unshift(fn); return () => (N.handlers = N.handlers.filter((h) => h !== fn)); };

function press(btn) {
  for (const h of N.handlers) if (h(btn)) return;
  if (DIRS.has(btn)) N.move(btn);
  else if (btn === "a" && N.cur) { R.sound("select"); N.cur.click(); }
}

// ---------- focus ----------
N.scope = () => {
  const ov = $$(".overlay:not([hidden])").pop();
  return ov || $$(".screen:not([hidden])")[0] || document.body;
};
const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2 && !el.closest("[hidden]"); };
N.items = () => $$("[data-nav]", N.scope()).filter(visible);

N.focus = (el, { scroll = true, quiet = false } = {}) => {
  if (!el) return;
  if (N.cur && N.cur !== el) N.cur.classList.remove("focus");
  N.cur = el;
  el.classList.add("focus");
  if (scroll) {
    const rail = el.closest(".rail");
    if (rail) {  // keep the focused tile a little in from the left edge
      const target = el.offsetLeft - rail.clientWidth * 0.12;
      rail.scrollTo({ left: Math.max(0, target), behavior: "smooth" });
    }
    // Glide to nearby items; jump straight to far ones (a letter jump shouldn't scroll for a second).
    const r = el.getBoundingClientRect();
    const far = r.bottom < -innerHeight * 0.5 || r.top > innerHeight * 1.5;
    el.scrollIntoView({ block: far ? "center" : "nearest", inline: "nearest", behavior: far ? "auto" : "smooth" });
  }
  if (!quiet) document.dispatchEvent(new CustomEvent("relic:focus", { detail: el }));
};

/** The nearest item in a direction, preferring ones lined up with the current one. */
/** Candidates for a move. In a big grid or rail only the neighbours nearby are measured, so moving
    stays instant with thousands of games. */
function nearby() {
  const scope = N.scope();
  const box = N.cur && N.cur.closest(".grid, .rail");
  if (!box || !scope.contains(box) || box.children.length < 120) return N.items();
  const kids = [...box.children];
  const i = kids.indexOf(N.cur);
  const near = kids.slice(Math.max(0, i - 60), i + 61);
  const rest = $$("[data-nav]", scope).filter((el) => !box.contains(el) && visible(el));
  return near.concat(rest);
}

N.move = (dir) => {
  const items = N.cur && document.body.contains(N.cur) ? nearby() : N.items();
  if (!items.length) return;
  if (!N.cur || !items.includes(N.cur)) return N.focus(items[0]);
  const a = N.cur.getBoundingClientRect();
  const ax = a.left + a.width / 2, ay = a.top + a.height / 2;
  let best = null, bestScore = Infinity;
  for (const el of items) {
    if (el === N.cur) continue;
    const b = el.getBoundingClientRect();
    const bx = b.left + b.width / 2, by = b.top + b.height / 2;
    const dx = bx - ax, dy = by - ay;
    let main, cross;
    if (dir === "left") { main = -dx; cross = Math.abs(dy); if (b.right > a.left + 4) continue; }
    else if (dir === "right") { main = dx; cross = Math.abs(dy); if (b.left < a.right - 4) continue; }
    else if (dir === "up") { main = -dy; cross = Math.abs(dx); if (b.bottom > a.top + 4) continue; }
    else { main = dy; cross = Math.abs(dx); if (b.top < a.bottom - 4) continue; }
    // Same row or column first, then closest.
    const overlap = dir === "left" || dir === "right" ? (b.bottom > a.top && b.top < a.bottom) : (b.right > a.left && b.left < a.right);
    const score = main + cross * (overlap ? 0.2 : 2.5) + (overlap ? 0 : 400);
    if (score < bestScore) { bestScore = score; best = el; }
  }
  if (best) { R.sound("move"); N.focus(best); }
  else R.sound("bump");
};

// ---------- keyboard ----------
document.addEventListener("keydown", (e) => {
  const t = e.target;
  const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA");
  if (typing && e.key !== "Escape") return;
  if (e.key === "F11") { e.preventDefault(); R.app && R.app.toggleFullscreen(); return; }
  const btn = KEY[e.key];
  if (!btn || e.ctrlKey || e.altKey || e.metaKey) return;
  e.preventDefault();
  N.usingPad = false;
  press(btn);
});

// ---------- mouse ----------
document.addEventListener("mousemove", (e) => {
  const el = e.target.closest && e.target.closest("[data-nav]");
  if (el && el !== N.cur && N.scope().contains(el)) N.focus(el, { scroll: false });
}, { passive: true });

// ---------- gamepad ----------
const P = { prev: new Set(), hold: { btn: "", next: 0, n: 0 }, fg: true, fgAt: 0 };
function pads() {
  const all = navigator.getGamepads ? [...navigator.getGamepads()].filter((p) => p && p.connected !== false) : [];
  const std = all.filter((p) => p.mapping === "standard");
  return std.length ? std : all;
}
function held() {
  const out = new Set();
  for (const p of pads()) {
    p.buttons.forEach((b, i) => { if ((b.pressed || b.value > 0.5) && BTN[i]) out.add(BTN[i]); });
    const [x = 0, y = 0] = p.axes;
    if (x < -0.55) out.add("left"); else if (x > 0.55) out.add("right");
    if (y < -0.55) out.add("up"); else if (y > 0.55) out.add("down");
  }
  return out;
}
async function inFront(now) {
  if (now - P.fgAt < 400) return P.fg;
  P.fgAt = now;
  const api = R.native();
  if (api && api.foreground) { try { P.fg = await api.foreground(); } catch (e) { P.fg = true; } }
  else P.fg = document.hasFocus();
  return P.fg;
}
async function poll(now) {
  requestAnimationFrame(poll);
  if (R.S.config.controller_nav === false) return;
  const h = held();
  if (!h.size && !P.prev.size) return;
  if (!(await inFront(now))) { P.prev = h; return; }
  for (const b of h) {
    if (!P.prev.has(b)) {
      N.usingPad = true;
      press(b);
      if (DIRS.has(b)) P.hold = { btn: b, next: now + 380, n: 0 };
    }
  }
  // Holding a direction repeats, speeding up.
  if (P.hold.btn && h.has(P.hold.btn) && now >= P.hold.next) {
    press(P.hold.btn);
    P.hold.n++;
    P.hold.next = now + Math.max(45, 130 - P.hold.n * 8);
  } else if (P.hold.btn && !h.has(P.hold.btn)) P.hold.btn = "";
  P.prev = h;
}
window.addEventListener("gamepadconnected", () => { document.body.classList.add("has-pad"); R.toast("Controller connected"); });
window.addEventListener("gamepaddisconnected", () => { if (!pads().length) document.body.classList.remove("has-pad"); });
requestAnimationFrame(poll);
})();
