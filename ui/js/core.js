/* Relic core: helpers, API, toasts, sounds. Everything hangs off window.R. */
(() => {
"use strict";
const R = (window.R = {});

R.$ = (s, el = document) => el.querySelector(s);
R.$$ = (s, el = document) => [...el.querySelectorAll(s)];
R.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
R.S = { config: {}, games: [], systems: [], themes: [], ra: {}, native: false, playing: null };

R.api = async (path, body) => {
  const opts = { method: body === undefined ? "GET" : "POST", headers: { "X-Relic-Token": window.RELIC_TOKEN } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok || data.ok === false) {
    const err = new Error(data.error || r.statusText);
    err.data = data;
    throw err;
  }
  return data;
};

R.native = () => window.pywebview && window.pywebview.api;

R.setConfig = async (changes) => {
  const r = await R.api("/api/config", changes);
  R.S.config = r.config;
  return r.config;
};

// ---------- toast ----------
let toastTimer = 0;
R.toast = (msg, bad = false) => {
  const t = R.$("#toast");
  t.textContent = msg;
  t.classList.toggle("bad", bad);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), bad ? 6000 : 3000);
};

// ---------- formatting ----------
R.playtime = (s) => {
  if (!s) return "Never played";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min played`;
  const h = s / 3600;
  return `${h < 10 ? h.toFixed(1) : Math.round(h)} hrs played`;
};
R.ago = (t) => {
  if (!t) return "";
  const d = (Date.now() / 1000 - t) / 86400;
  if (d < 1 / 24) return "just now";
  if (d < 1) return `${Math.round(d * 24)}h ago`;
  if (d < 2) return "yesterday";
  if (d < 30) return `${Math.round(d)} days ago`;
  return new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
};

// A colour per system, for tiles and placeholder covers.
R.sysColor = (id) => ({
  nes: "#c8283c", snes: "#7a5cff", n64: "#2ea84f", gb: "#8bac0f", gbc: "#9b3bd6", gba: "#4b3fbf",
  nds: "#9aa4b5", vb: "#d01010", sms: "#d23b2f", genesis: "#1f6fe0", segacd: "#2a8ac9", "32x": "#e0a21f",
  gamegear: "#2c2c34", saturn: "#5a6dbd", dreamcast: "#f06a1d", psx: "#9aa0ac", ps2: "#2b4fa3", psp: "#3b3f48", gamecube: "#6a4fd1", wii: "#b9c2cf",
  pce: "#ff8a00", atari2600: "#a0522d", atari7800: "#b5651d", lynx: "#d8b23a", ngp: "#00a3a3",
  wonderswan: "#5c8ad6", arcade: "#e6328c",
  ps3: "#1d1d24", ps4: "#1f4fb8", wiiu: "#1aa0d8", switch: "#e60012", xbox: "#5b9e2d", xbox360: "#7cbf2a",
  fds: "#c8a032", n64dd: "#2a7c3f", "3ds": "#d33a3a", gw: "#b8862e", pokemini: "#e8c83a", sg1000: "#7e1f2b",
  naomi: "#3a6fb5", pcecd: "#ff9a2a", sgx: "#e07a00", pcfx: "#6b6f7e", pc98: "#3f6f8f", atari5200: "#8a5a2b",
  atari800: "#7a4b2a", jaguar: "#c41e1e", atarist: "#5a7a9a", neocd: "#c79a2a", "3do": "#7a2f2f", cdi: "#3d5fb0",
  coleco: "#2f4f7f", intv: "#a4782b", vectrex: "#4a4a52", odyssey2: "#2f5f9f", channelf: "#8f6b3a",
  supervision: "#4d7f5f", msx: "#3f5fa0", c64: "#6b5fb5", amiga: "#d94f2b", zx: "#3a3a44", cpc: "#3a6f3a",
  x68000: "#6f6f78", dos: "#3a6fb5", scummvm: "#4fae4f", pico8: "#ff004d", tic80: "#41a6f6",
}[id] || "#6c7a96");

// Box shapes: SNES and N64 boxes are wide (US), disc cases and handhelds squarer, the rest tall.
R.boxRatio = (id) => ({ snes: 1.38, n64: 1.38, gb: 1, gbc: 1, gba: 1, vb: 1, nds: .9, psx: 1, dreamcast: 1,
  psp: .58, gamegear: .76, lynx: .9, ngp: .9, wonderswan: .9, "3ds": .9, pokemini: .9, gw: 1, neocd: 1,
  pcecd: 1, "3do": 1, ps3: .86, ps4: .8, wiiu: .72, switch: .62, xbox: .7, xbox360: .7, cdi: 1, saturn: .62, segacd: .62, supervision: .9 }[id] || .72);

// ---------- sounds (tiny synthesized blips, no files) ----------
let ac = null;
R.sound = (kind) => {
  if (R.S.config.sounds === false) return;
  try {
    ac = ac || new (window.AudioContext || window.webkitAudioContext)();
    const o = ac.createOscillator(), g = ac.createGain();
    const p = { move: [520, 0.025, 0.04], select: [880, 0.05, 0.09], back: [330, 0.04, 0.08], fav: [1046, 0.05, 0.12], bump: [160, 0.04, 0.06] }[kind] || [600, 0.03, 0.05];
    o.type = kind === "bump" ? "square" : "triangle";
    o.frequency.setValueAtTime(p[0], ac.currentTime);
    if (kind === "select" || kind === "fav") o.frequency.exponentialRampToValueAtTime(p[0] * 1.5, ac.currentTime + p[2]);
    g.gain.setValueAtTime(p[1], ac.currentTime);
    g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + p[2]);
    o.connect(g).connect(ac.destination);
    o.start();
    o.stop(ac.currentTime + p[2] + 0.02);
  } catch (e) { /* no audio, no problem */ }
};
})();
