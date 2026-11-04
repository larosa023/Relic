/* Relic app: home (systems + rows), a system's shelf, game options, settings. */
(() => {
"use strict";
const { $, $$, esc, S } = R;
const A = (R.app = {});
let screen = "home";          // home | shelf | settings
let shelfSys = null;          // system id on the shelf
let lastHomeFocus = null;     // data-key to go back to
let settingsFrom = "home";
let sortModes = ["title", "recent", "played"];
const SORT_LABEL = { title: "A–Z", recent: "Recently played", played: "Most played" };

// ---------- loading ----------
async function loadState() {
  const st = await R.api("/api/state");
  S.config = st.config; S.themes = st.themes; S.ra = st.retroarch; S.native = st.native; S.version = st.version;
  setPlaying(st.playing);
  applyTheme(S.config.theme);
}
async function loadLibrary(refresh = false) {
  const r = refresh ? await R.api("/api/rescan", {}) : await R.api("/api/library");
  S.games = r.games; S.systems = r.systems;
  S.byId = Object.fromEntries(S.games.map((g) => [g.id, g]));
  S.sysById = Object.fromEntries(S.systems.map((s) => [s.id, s]));
}

function applyTheme(id) {
  const link = $("#theme-css");
  const href = `/themes/${id || "relic"}.css`;
  if (link.getAttribute("href") !== href) link.setAttribute("href", href);
}

// ---------- pieces ----------
const visibleGames = () => S.games.filter((g) => !g.hidden);
const art = (g, kind = "boxart") => `/art/${g.id}/${kind}`;

function placeholder(g) {
  const s = S.sysById[g.system];
  return `<div class="ph" style="--sys:${R.sysColor(g.system)}"><span class="ph-sys">${esc(s ? s.name : "")}</span><span class="ph-title">${esc(g.title)}</span></div>`;
}

function card(g, key) {
  return `<div class="card${g.favorite ? " fav" : ""}" data-nav data-game="${g.id}" data-key="${esc(key)}" style="--sys:${R.sysColor(g.system)};--ar:${R.boxRatio(g.system)}">
    <div class="cover">${placeholder(g)}<img loading="lazy" decoding="async" alt="" src="${art(g)}" onload="this.parentNode.classList.add('has-art')" onerror="this.remove()"></div>
    <div class="cap">${esc(g.title)}</div>
    <div class="star">★</div>
  </div>`;
}

function sysTile(s) {
  return `<div class="sys" data-nav data-sys="${s.id}" data-key="sys:${s.id}" style="--sys:${R.sysColor(s.id)}">
    <div class="sys-maker">${esc(s.maker)}${s.year ? ` · ${s.year}` : ""}</div>
    <div class="sys-name">${esc(s.name)}</div>
    <div class="sys-count">${s.count} game${s.count === 1 ? "" : "s"}</div>
  </div>`;
}

// ---------- screens ----------
function show(name) {
  screen = name;
  for (const el of $$(".screen")) el.hidden = el.id !== name;
  document.body.dataset.screen = name;
  renderCrumb();
  hints();
}

function renderHome(focusKey) {
  const games = visibleGames();
  $("#sys-rail").innerHTML = S.systems.filter((s) => games.some((g) => g.system === s.id)).map(sysTile).join("")
    + `<div class="sys sys-settings" data-nav data-do="settings" data-key="settings"><div class="sys-name">Settings</div><div class="sys-count">RetroArch, folders, look</div></div>`;
  const rows = [];
  const recent = games.filter((g) => g.last).sort((a, b) => b.last - a.last).slice(0, 14);
  if (recent.length) rows.push(["Continue playing", "recent", recent]);
  const favs = games.filter((g) => g.favorite).sort((a, b) => a.sort.localeCompare(b.sort));
  if (favs.length) rows.push(["Favorites", "fav", favs]);
  if (!recent.length && games.length) {
    // Something to start with: a handful from across your systems.
    const picks = [...games].sort(() => Math.random() - 0.5).slice(0, 14);
    rows.push(["Pick something", "pick", picks]);
  }
  $("#home-rows").innerHTML = rows.map(([title, k, list]) =>
    `<div class="row-title">${esc(title)}</div><div class="rail cards">${list.map((g) => card(g, `${k}:${g.id}`)).join("")}</div>`).join("");
  const empty = $("#empty");
  empty.hidden = games.length > 0;
  if (!games.length) {
    empty.innerHTML = S.ra.found
      ? `<h2>No games yet</h2><p>Relic found RetroArch but none of its playlists have games in them. Scan a folder in RetroArch (Import Content), or add your ROM folders here.</p><button class="btn" data-nav data-do="settings">Open settings</button>`
      : `<h2>Where's RetroArch?</h2><p>Relic couldn't find RetroArch on this PC. Install it from retroarch.com, or point Relic at its folder.</p><button class="btn" data-nav data-do="settings">Open settings</button>`;
  }
  show("home");
  const el = (focusKey && $(`[data-key="${CSS.escape(focusKey)}"]`, $("#home"))) || $("#home [data-nav]");
  R.nav.focus(el);
}

function sortGames(list) {
  const mode = S.config.shelf_sort || "title";
  const by = {
    title: (a, b) => a.sort.localeCompare(b.sort),
    recent: (a, b) => (b.last - a.last) || a.sort.localeCompare(b.sort),
    played: (a, b) => (b.played - a.played) || a.sort.localeCompare(b.sort),
  }[mode] || ((a, b) => a.sort.localeCompare(b.sort));
  return [...list].sort((a, b) => (b.favorite - a.favorite) || by(a, b));
}

function openShelf(sid, focusId) {
  const s = S.sysById[sid];
  if (!s) return renderHome();
  shelfSys = sid;
  const games = sortGames(visibleGames().filter((g) => g.system === sid));
  $("#shelf-maker").textContent = `${s.maker}${s.year ? ` · ${s.year}` : ""}`;
  $("#shelf-name").textContent = s.name;
  $("#shelf-count").textContent = `${games.length} game${games.length === 1 ? "" : "s"}`;
  $("#shelf-sort").textContent = SORT_LABEL[S.config.shelf_sort] || "A–Z";
  $("#shelf").style.setProperty("--sys", R.sysColor(sid));
  $("#grid").innerHTML = games.map((g) => card(g, `shelf:${g.id}`)).join("");
  show("shelf");
  $("#grid").scrollTop = 0;
  R.nav.focus((focusId && $(`[data-game="${focusId}"]`, $("#grid"))) || $("#grid [data-nav]"));
}

function shelfStep(d) {
  const ids = visibleSystems();
  if (ids.length < 2) return R.sound("bump");
  const i = ids.indexOf(shelfSys);
  R.sound("move");
  openShelf(ids[(i + d + ids.length) % ids.length]);
}
const visibleSystems = () => S.systems.filter((s) => visibleGames().some((g) => g.system === s.id)).map((s) => s.id);

function renderCrumb() {
  const c = $("#crumb");
  if (screen === "shelf" && S.sysById[shelfSys]) c.innerHTML = `<span>${esc(S.sysById[shelfSys].name)}</span>`;
  else if (screen === "settings") c.innerHTML = "<span>Settings</span>";
  else c.innerHTML = "";
}

// ---------- backdrop: the focused game's screenshot, softly ----------
let bdTimer = 0, bdFlip = false, bdUrl = "";
function setBackdrop(url, color) {
  document.documentElement.style.setProperty("--focus-sys", color || "transparent");
  if (url === bdUrl) return;
  bdUrl = url;
  const next = bdFlip ? $("#bd-a") : $("#bd-b"), prev = bdFlip ? $("#bd-b") : $("#bd-a");
  bdFlip = !bdFlip;
  prev.classList.remove("on");
  if (!url) { next.classList.remove("on"); return; }
  const img = new Image();
  img.onload = () => { if (bdUrl === url) { next.style.backgroundImage = `url("${url}")`; next.classList.add("on"); } };
  img.onerror = () => {
    // No screenshot: fall back to the box art, which the blur makes work as a backdrop.
    if (bdUrl === url && url.endsWith("/snap")) { bdUrl = ""; setBackdrop(url.replace(/\/snap$/, "/boxart"), color); }
  };
  img.src = url;
}
document.addEventListener("relic:focus", (e) => {
  const el = e.detail;
  hints();
  clearTimeout(bdTimer);
  bdTimer = setTimeout(() => {
    const g = el.dataset.game && S.byId[el.dataset.game];
    if (g) setBackdrop(art(g, "snap"), R.sysColor(g.system));
    else if (el.dataset.sys) setBackdrop("", R.sysColor(el.dataset.sys));
    else setBackdrop("", "");
  }, 220);
  if (screen === "shelf") showInfo(el);
});

function showInfo(el) {
  const g = el && el.dataset.game && S.byId[el.dataset.game];
  let bar = $("#shelf-info");
  if (!bar) { bar = document.createElement("div"); bar.id = "shelf-info"; $("#shelf").appendChild(bar); }
  if (!g) { bar.innerHTML = ""; return; }
  const bits = [g.region, R.playtime(g.played), g.last ? `last played ${R.ago(g.last)}` : ""].filter(Boolean);
  bar.innerHTML = `<div class="si-title">${g.favorite ? '<span class="si-star">★</span> ' : ""}${esc(g.title)}</div><div class="si-meta">${bits.map(esc).join(" · ")}</div>`;
}

// ---------- hints ----------
const GLYPH = { a: "A", b: "B", x: "X", y: "Y", lb: "LB", rb: "RB", start: "☰", select: "⧉" };
const KEYCAP = { a: "Enter", b: "Esc", x: "F", y: "Tab", lb: "Q", rb: "E", start: ",", select: "S" };
function hints() {
  const pad = R.nav.usingPad || document.body.classList.contains("has-pad");
  const cap = (bs) => bs.split("+").map((b) => pad ? `<b class="g g-${b}">${GLYPH[b]}</b>` : `<b class="k">${KEYCAP[b]}</b>`).join("");
  const cur = R.nav.cur;
  const onGame = cur && cur.dataset.game && !$("#game-pop:not([hidden])");
  let list = [];
  if (!$("#game-pop").hidden) list = [["a", "Select"], ["b", "Close"]];
  else if (screen === "settings") list = [["a", "Select"], ["b", "Back"]];
  else {
    list.push(["a", onGame ? "Play" : "Open"]);
    if (onGame) list.push(["x", "Favorite"], ["y", "Options"]);
    if (screen === "shelf") list.push(["lb+rb", "System"], ["select", "Sort"], ["b", "Back"]);
    list.push(["start", "Settings"]);
  }
  $("#hints").innerHTML = list.map(([b, t]) => `<span class="hint-i">${cap(b)}${t ? `<span>${esc(t)}</span>` : ""}</span>`).join("");
}

// ---------- playing ----------
let playPoll = 0;
function setPlaying(p) {
  const was = S.playing;
  S.playing = p;
  const pill = $("#now-playing");
  pill.hidden = !p;
  if (p) pill.innerHTML = `<span class="dot"></span>Playing ${esc(p.title)}`;
  clearInterval(playPoll);
  if (p) playPoll = setInterval(async () => {
    try { const st = await R.api("/api/state"); setPlaying(st.playing); } catch (e) {}
  }, 3000);
  if (was && !p) afterPlay(was.id);
}
async function afterPlay(gid) {
  await loadLibrary();
  if (screen === "shelf") openShelf(shelfSys, gid);
  else if (screen === "home") renderHome(`recent:${gid}`);
}

async function launch(g) {
  if (!g) return;
  if (S.playing) return R.toast(`${S.playing.title} is still running`, true);
  R.sound("select");
  $("#launching-text").textContent = `Starting ${g.title}…`;
  $("#launching").hidden = false;
  try {
    await R.api("/api/launch", { id: g.id });
    setPlaying({ id: g.id, title: g.title, since: Date.now() / 1000 });
    setTimeout(() => ($("#launching").hidden = true), 1800);
  } catch (e) {
    $("#launching").hidden = true;
    R.toast(e.message, true);
  }
}

async function setMeta(g, changes) {
  await R.api("/api/meta", { id: g.id, changes });
  Object.assign(g, changes);
}

async function toggleFav(g, el) {
  await setMeta(g, { favorite: !g.favorite });
  R.sound(g.favorite ? "fav" : "back");
  R.toast(g.favorite ? `Added ${g.title} to favorites` : `Removed ${g.title} from favorites`);
  for (const c of $$(`[data-game="${g.id}"]`)) c.classList.toggle("fav", g.favorite);
  if (screen === "shelf") showInfo(el);
}

// ---------- game options (Y) ----------
let popGame = null, popReturn = null;
function openPop(g) {
  popGame = g; popReturn = R.nav.cur;
  const s = S.sysById[g.system];
  $("#pop-art").style.cssText = `--sys:${R.sysColor(g.system)};aspect-ratio:${R.boxRatio(g.system)}`;
  $("#pop-art").innerHTML = `${placeholder(g)}<img alt="" src="${art(g)}?t=${Date.now()}" onload="this.parentNode.classList.add('has-art')" onerror="this.remove()">`;
  $("#pop-sys").textContent = s ? s.name : "";
  $("#pop-title").textContent = g.title;
  const meta = [g.region, R.playtime(g.played), g.plays ? `${g.plays} session${g.plays === 1 ? "" : "s"}` : "", g.last ? `last played ${R.ago(g.last)}` : ""].filter(Boolean);
  $("#pop-meta").innerHTML = meta.map(esc).join(" · ") + `<div class="pop-file">${esc(g.label)}</div>`;
  renderPopActions();
  $("#game-pop").hidden = false;
  R.sound("select");
  R.nav.focus($("#pop-actions [data-nav]"));
  hints();
}
function coreLabel(g) {
  const s = S.sysById[g.system];
  const cores = (s && s.cores) || [];
  const mine = cores.find((c) => c.id === g.core);
  const sysPick = (S.config.system_cores || {})[g.system];
  const dflt = cores.find((c) => c.id === sysPick) || cores[0];
  return mine ? mine.name : dflt ? `Automatic (${dflt.name})` : "No core installed";
}
function renderPopActions(focusDo) {
  const g = popGame;
  $("#pop-actions").innerHTML = [
    ["play", "▶  Play"],
    ["fav", g.favorite ? "★  Remove from favorites" : "☆  Add to favorites"],
    ["core", `Core: ${coreLabel(g)}`],
    ...(S.native ? [["art", "Set box art…"]] : []),
    ["hide", "Hide this game"],
  ].map(([d, t]) => `<button class="btn wide" data-nav data-do="pop-${d}">${esc(t)}</button>`).join("");
  if (focusDo) R.nav.focus($(`[data-do="pop-${focusDo}"]`));
}
function closePop() {
  $("#game-pop").hidden = true;
  const back = popReturn && document.body.contains(popReturn) ? popReturn : null;
  popGame = null;
  if (back) R.nav.focus(back, { scroll: false });
  hints();
}
async function cycleCore(g) {
  const s = S.sysById[g.system];
  const ids = ["", ...((s && s.cores) || []).map((c) => c.id)];
  if (ids.length < 2) return R.toast("No cores installed for this system. Get one in RetroArch's Online Updater.", true);
  const next = ids[(ids.indexOf(g.core || "") + 1) % ids.length];
  await setMeta(g, { core: next });
  R.sound("move");
  renderPopActions("core");
}

// ---------- settings ----------
const TOGGLES = [
  ["start_fullscreen", "Open Relic full screen"],
  ["launch_fullscreen", "Start games full screen"],
  ["when_playing", "Minimize Relic while you play", "minimize", "none"],
  ["restore_after_play", "Come back when the game closes"],
  ["download_art", "Download box art"],
  ["sounds", "Menu sounds"],
  ["controller_nav", "Controller navigation"],
];
function renderSettings(focusDo) {
  const ra = S.ra;
  $("#ra-status").innerHTML = ra.found
    ? `<div class="ok">● Found RetroArch</div><div class="path">${esc(ra.exe)}</div><div class="path">${ra.cores} core${ra.cores === 1 ? "" : "s"} installed${ra.playlists ? ` · playlists in ${esc(ra.playlists)}` : ""}</div>`
    : `<div class="bad">● RetroArch not found</div><div class="path">Install it from retroarch.com, or choose its folder below.</div>`;
  const folders = S.config.rom_folders || [];
  $("#rom-folders").innerHTML = folders.length
    ? folders.map((f, i) => `<button class="btn folder" data-nav data-do="rm-folder" data-i="${i}"><span>${esc(f)}</span><em>Remove</em></button>`).join("")
    : `<p class="hint dim">No extra folders.</p>`;
  $("#toggles").innerHTML = TOGGLES.map(([k, label, on, off]) => {
    const v = on ? S.config[k] === on : S.config[k] !== false;
    return `<button class="btn toggle${v ? " on" : ""}" data-nav data-do="toggle" data-k="${k}"><span>${esc(label)}</span><i></i></button>`;
  }).join("");
  $("#themes").innerHTML = S.themes.map((t) =>
    `<button class="btn theme${t.id === S.config.theme ? " on" : ""}" data-nav data-do="theme" data-id="${t.id}">
      <span class="sw">${(t.swatch || []).map((c) => `<i style="background:${esc(c)}"></i>`).join("")}</span>${esc(t.name)}</button>`).join("");
  $("#ver").textContent = S.version;
  if (focusDo) {
    const el = typeof focusDo === "string" ? $(focusDo, $("#settings")) : null;
    R.nav.focus(el || $("#settings [data-nav]"), { scroll: false });
  }
}
function openSettings() {
  settingsFrom = screen === "settings" ? settingsFrom : screen;
  lastHomeFocus = R.nav.cur && R.nav.cur.dataset.key;
  renderSettings();
  show("settings");
  R.nav.focus($("#settings [data-nav]"));
}
function closeSettings() {
  R.sound("back");
  if (settingsFrom === "shelf" && shelfSys) openShelf(shelfSys, lastHomeFocus && lastHomeFocus.split(":")[1]);
  else renderHome(lastHomeFocus);
}

async function pickFolder() {
  const api = R.native();
  if (api && api.pick_folder) return (await api.pick_folder()) || "";
  return (window.prompt("Folder path:") || "").trim();
}

async function afterConfigChange(refocus) {
  await loadState();
  await loadLibrary();
  renderSettings(refocus);
}

async function doAction(el) {
  const d = el.dataset.do;
  try {
    if (d === "settings") return openSettings();
    if (d === "pick-ra") {
      const p = await pickFolder();
      if (!p) return;
      await R.setConfig({ retroarch_path: p });
      await afterConfigChange('[data-do="pick-ra"]');
      return R.toast(S.ra.found ? "Found RetroArch" : "No retroarch.exe in that folder", !S.ra.found);
    }
    if (d === "auto-ra") {
      await R.setConfig({ retroarch_path: "" });
      await afterConfigChange('[data-do="auto-ra"]');
      return R.toast(S.ra.found ? "Found RetroArch" : "Still couldn't find RetroArch", !S.ra.found);
    }
    if (d === "add-folder") {
      const p = await pickFolder();
      if (!p) return;
      const list = [...(S.config.rom_folders || [])];
      if (!list.includes(p)) list.push(p);
      R.toast("Scanning…");
      await R.setConfig({ rom_folders: list });
      await afterConfigChange('[data-do="add-folder"]');
      return R.toast(`${S.games.length} games in your library`);
    }
    if (d === "rm-folder") {
      if (el.dataset.armed !== "1") {
        el.dataset.armed = "1"; el.classList.add("armed");
        el.querySelector("em").textContent = "Press again to remove";
        return;
      }
      const list = [...(S.config.rom_folders || [])];
      list.splice(+el.dataset.i, 1);
      await R.setConfig({ rom_folders: list });
      return afterConfigChange('[data-do="add-folder"]');
    }
    if (d === "rescan") {
      R.toast("Rescanning…");
      await loadState();
      await loadLibrary(true);
      renderSettings('[data-do="rescan"]');
      return R.toast(`${S.games.length} games in your library`);
    }
    if (d === "toggle") {
      const t = TOGGLES.find((x) => x[0] === el.dataset.k);
      const [k, , on, off] = t;
      const v = on ? (S.config[k] === on ? off : on) : S.config[k] === false;
      await R.setConfig({ [k]: v });
      return renderSettings(`[data-k="${k}"]`);
    }
    if (d === "theme") {
      await R.setConfig({ theme: el.dataset.id });
      applyTheme(el.dataset.id);
      return renderSettings(`[data-id="${el.dataset.id}"]`);
    }
    const g = popGame;
    if (d === "pop-play") { closePop(); return launch(g); }
    if (d === "pop-fav") { await toggleFav(g, popReturn); return renderPopActions("fav"); }
    if (d === "pop-core") return cycleCore(g);
    if (d === "pop-art") {
      const api = R.native();
      const p = api && (await api.pick_file("image"));
      if (!p) return;
      await R.api("/api/customart", { id: g.id, kind: "boxart", path: p });
      for (const img of $$(`[data-game="${g.id}"] img, #pop-art img`)) img.src = `${art(g)}?t=${Date.now()}`;
      return R.toast("Box art updated");
    }
    if (d === "pop-hide") {
      await setMeta(g, { hidden: true });
      closePop();
      R.toast(`Hid ${g.title}`);
      return screen === "shelf" ? (visibleGames().some((x) => x.system === shelfSys) ? openShelf(shelfSys) : renderHome()) : renderHome();
    }
  } catch (e) { R.toast(e.message, true); }
}

// ---------- buttons ----------
R.nav.on((btn) => {
  const cur = R.nav.cur;
  const g = cur && cur.dataset.game && S.byId[cur.dataset.game];
  if (!$("#launching").hidden) return true;
  if (!$("#game-pop").hidden) {
    if (btn === "b" || btn === "y") { R.sound("back"); closePop(); return true; }
    return false;  // directions and A work inside the popup
  }
  if (btn === "start") { R.sound("select"); screen === "settings" ? closeSettings() : openSettings(); return true; }
  if (screen === "settings") {
    if (btn === "b") { closeSettings(); return true; }
    return false;
  }
  if (btn === "a") {
    if (g) { launch(g); return true; }
    if (cur && cur.dataset.sys) { R.sound("select"); lastHomeFocus = cur.dataset.key; openShelf(cur.dataset.sys); return true; }
    return false;
  }
  if (btn === "x" && g) { toggleFav(g, cur); return true; }
  if (btn === "y" && g) { openPop(g); return true; }
  if (screen === "shelf") {
    if (btn === "b") { R.sound("back"); renderHome(lastHomeFocus || `sys:${shelfSys}`); return true; }
    if (btn === "lb") { shelfStep(-1); return true; }
    if (btn === "rb") { shelfStep(1); return true; }
    if (btn === "select") {
      const i = sortModes.indexOf(S.config.shelf_sort || "title");
      R.setConfig({ shelf_sort: sortModes[(i + 1) % sortModes.length] }).then(() => {
        R.sound("move");
        R.toast(`Sorted by ${SORT_LABEL[S.config.shelf_sort].toLowerCase()}`);
        openShelf(shelfSys, g && g.id);
      });
      return true;
    }
  }
  if (screen === "home" && (btn === "lb" || btn === "rb")) {
    // Jump between rows quickly.
    R.nav.move(btn === "lb" ? "up" : "down");
    return true;
  }
  return false;
});

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-do], [data-game], [data-sys], [data-win]");
  if (!el) return;
  if (el.dataset.win) return winCtl(el.dataset.win);
  if (el.dataset.do) return doAction(el);
  if (el.dataset.game) return launch(S.byId[el.dataset.game]);
  if (el.dataset.sys) { lastHomeFocus = el.dataset.key; openShelf(el.dataset.sys); }
});
document.addEventListener("contextmenu", (e) => {
  const el = e.target.closest("[data-game]");
  if (!el) return;
  e.preventDefault();
  R.nav.focus(el, { scroll: false });
  openPop(S.byId[el.dataset.game]);
});

// ---------- window ----------
A.toggleFullscreen = async () => {
  const api = R.native();
  if (api && api.fullscreen) {
    const on = !(await api.is_fullscreen());
    await api.fullscreen(on);
    document.body.classList.toggle("fullscreen", on);
  } else if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
};
function winCtl(what) {
  const api = R.native();
  if (!api) return;
  if (what === "min") api.minimize();
  else if (what === "full") A.toggleFullscreen();
  else if (what === "close") api.close();
}
$("#top").addEventListener("mousedown", (e) => {
  const api = R.native();
  if (!api || e.button !== 0 || e.target.closest("button, #now-playing") || document.body.classList.contains("fullscreen")) return;
  api.drag();
});

function tick() {
  $("#clock").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// ---------- start ----------
async function start() {
  tick(); setInterval(tick, 15000);
  try {
    await loadState();
    await loadLibrary();
  } catch (e) {
    R.toast(`Couldn't load your library: ${e.message}`, true);
  }
  if (S.native) {
    $("#win-ctl").hidden = false;
    if (S.config.start_fullscreen) document.body.classList.add("fullscreen");
  }
  renderHome();
}
window.addEventListener("pywebviewready", () => { S.native = true; $("#win-ctl").hidden = false; });
start();
})();
