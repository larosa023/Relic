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
  R.nav.applyMaps(S.config);
  document.body.classList.toggle("framed", S.config.frameless === false);
  if (st.update) setUpdate(st.update);
}
async function loadLibrary(refresh = false) {
  const r = refresh ? await R.api("/api/rescan", {}) : await R.api("/api/library");
  S.games = r.games; S.systems = r.systems; S.rev = r.rev;
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
    + `<div class="sys sys-settings" data-nav data-do="settings" data-key="settings"><div class="sys-name">Settings</div><div class="sys-count">${S.update && (S.update.available || S.update.ready) ? '<span class="badge">Update ready</span>' : "RetroArch, folders, look"}</div></div>`;
  const rows = [];
  const recent = games.filter((g) => g.last).sort((a, b) => b.last - a.last).slice(0, 14);
  if (recent.length) rows.push(["Continue playing", "recent", recent]);
  const newest = games.filter((g) => g.added).sort((a, b) => b.added - a.added);
  // Only worth a row when games arrived at different times (not one big import).
  if (newest.length > 6 && newest[0].added - newest[Math.min(13, newest.length - 1)].added > 3600) rows.push(["Recently added", "new", newest.slice(0, 14)]);
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

function openShelf(sid, focusId, keepScroll = false) {
  const s = S.sysById[sid];
  if (!s) return renderHome();
  const scroll = keepScroll && shelfSys === sid ? $("#shelf").scrollTop : 0;
  shelfSys = sid;
  const games = sortGames(visibleGames().filter((g) => g.system === sid));
  $("#shelf-maker").textContent = `${s.maker}${s.year ? ` · ${s.year}` : ""}`;
  $("#shelf-name").textContent = s.name;
  $("#shelf-count").textContent = `${games.length} game${games.length === 1 ? "" : "s"}`;
  $("#shelf-sort").textContent = SORT_LABEL[S.config.shelf_sort] || "A–Z";
  $("#shelf").style.setProperty("--sys", R.sysColor(sid));
  // Big shelves: show the first screenfuls now and the rest a frame later, so opening feels instant.
  const at = focusId ? games.findIndex((g) => g.id === focusId) : 0;
  const first = Math.max(150, at + 60);
  const grid = $("#grid");
  const token = (grid.dataset.token = String(Math.random()));
  grid.innerHTML = games.slice(0, first).map((g) => card(g, `shelf:${g.id}`)).join("");
  if (games.length > first) requestAnimationFrame(() => setTimeout(() => {
    if (grid.dataset.token !== token) return;  // you've already moved on
    grid.insertAdjacentHTML("beforeend", games.slice(first).map((g) => card(g, `shelf:${g.id}`)).join(""));
  }, 0));
  show("shelf");
  $("#shelf").scrollTop = scroll;
  R.nav.focus((focusId && $(`[data-game="${focusId}"]`, $("#grid"))) || $("#grid [data-nav]"), { scroll: !keepScroll });
}

/** LT/RT on a shelf: jump to the next or previous starting letter (or ten games, when not sorted A–Z). */
const firstLetter = (g) => g.favorite ? "★" : (/[a-z]/.test(g.sort[0] || "") ? g.sort[0].toUpperCase() : "#");
function letterJump(d) {
  const cards = $$("#grid .card");
  const i = cards.indexOf(R.nav.cur);
  if (i < 0) return;
  const byTitle = (S.config.shelf_sort || "title") === "title";
  let j = i;
  if (byTitle) {
    const L = (k) => firstLetter(S.byId[cards[k].dataset.game]);
    const cur = L(i);
    if (d > 0) { while (j < cards.length && L(j) === cur) j++; }
    else {
      while (j > 0 && L(j - 1) === cur) j--;          // start of this letter
      if (j === i && j > 0) { j--; const prev = L(j); while (j > 0 && L(j - 1) === prev) j--; }
    }
  } else j = i + d * 10;
  j = Math.max(0, Math.min(cards.length - 1, j));
  if (j === i) return R.sound("bump");
  R.sound("move");
  R.nav.focus(cards[j]);
  if (byTitle) showLetter(firstLetter(S.byId[cards[j].dataset.game]));
}

let letterTimer = 0;
function showLetter(ch) {
  const el = $("#letter");
  el.textContent = ch;
  el.classList.remove("on"); void el.offsetWidth; el.classList.add("on");
  clearTimeout(letterTimer);
  letterTimer = setTimeout(() => el.classList.remove("on"), 700);
}

function shelfStep(d) {
  const ids = visibleSystems();
  if (ids.length < 2) return R.sound("bump");
  const i = ids.indexOf(shelfSys);
  R.sound("move");
  openShelf(ids[(i + d + ids.length) % ids.length]);
}
const visibleSystems = () => S.systems.filter((s) => visibleGames().some((g) => g.system === s.id)).map((s) => s.id);

/** The Back button in the top bar: shown anywhere except the home screen. */
function updateBack() {
  $("#back-btn").hidden = screen === "home";
}
$("#back-btn").addEventListener("click", () => R.nav.press("b"));
// Clicking outside the game options box closes it.
$("#game-pop").addEventListener("mousedown", (e) => { if (e.target.id === "game-pop") { R.sound("back"); closePop(); } });

function renderCrumb() {
  updateBack();
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
function hints() {
  const pad = R.nav.usingPad || document.body.classList.contains("has-pad");
  // Hints show your own layout: the button or key each action is on right now.
  const cap = (bs) => bs.split("+").map((b) => pad
    ? `<b class="g g-${R.nav.pad[b]}">${esc(R.nav.padName(b))}</b>`
    : `<b class="k">${esc(R.nav.keyName(b))}</b>`).join("");
  const cur = R.nav.cur;
  const onGame = cur && cur.dataset.game && !$("#game-pop:not([hidden])");
  let list = [];
  if (!$("#game-pop").hidden) list = [["a", "Select"], ["b", "Close"]];
  else if (screen === "settings") list = [["a", "Select"], ["b", "Back"]];
  else {
    list.push(["a", onGame ? "Play" : "Open"]);
    if (onGame) list.push(["x", "Favorite"], ["y", "Options"]);
    if (screen === "shelf") list.push(["lb+rb", "System"], ["lt+rt", "Jump"], ["select", "Sort"], ["b", "Back"]);
    if (screen === "home" && S.games.length) list.push(["select", "Surprise me"]);
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

/** Select at home: a random game, nudged toward ones you haven't played much. */
function surprise() {
  const pool = visibleGames();
  if (!pool.length) return R.sound("bump");
  const weights = pool.map((g) => (g.favorite ? 2 : 1) * (g.played ? 1 / (1 + g.played / 3600) : 3));
  let r = Math.random() * weights.reduce((a, b) => a + b, 0), g = pool[0];
  for (let i = 0; i < pool.length; i++) { r -= weights[i]; if (r <= 0) { g = pool[i]; break; } }
  openPop(g, true);
}

// ---------- game options (Y) ----------
let popGame = null, popReturn = null, popSurprise = false;
function openPop(g, surprised = false) {
  popGame = g; popReturn = popReturn && !$("#game-pop").hidden ? popReturn : R.nav.cur; popSurprise = surprised;
  const s = S.sysById[g.system];
  $("#pop-art").style.cssText = `--sys:${R.sysColor(g.system)};aspect-ratio:${R.boxRatio(g.system)}`;
  $("#pop-art").innerHTML = `${placeholder(g)}<img alt="" src="${art(g)}?t=${Date.now()}" onload="this.parentNode.classList.add('has-art')" onerror="this.remove()">`;
  $("#pop-sys").textContent = (surprised ? "Surprise · " : "") + (s ? s.name : "");
  $("#pop-title").textContent = g.title;
  const meta = [g.region, R.playtime(g.played), g.plays ? `${g.plays} session${g.plays === 1 ? "" : "s"}` : "", g.last ? `last played ${R.ago(g.last)}` : ""].filter(Boolean);
  $("#pop-meta").innerHTML = meta.map(esc).join(" · ") + `<div class="pop-file">${esc(g.label)}</div>`;
  renderPopActions();
  $("#game-pop").hidden = false;
  updateBack();
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
    ...(g.core && g.core !== (S.config.system_cores || {})[g.system] ? [["core-all", `Use this core for every ${(S.sysById[g.system] || {}).name || ""} game`]] : []),
    ...(popSurprise ? [["again", "↻  Surprise me again"]] : []),
    ...(S.native ? [["art", "Set box art…"]] : []),
    ["hide", "Hide this game"],
  ].map(([d, t]) => `<button class="btn wide" data-nav data-do="pop-${d}">${esc(t)}</button>`).join("");
  if (focusDo) R.nav.focus($(`[data-do="pop-${focusDo}"]`));
}
function closePop() {
  $("#game-pop").hidden = true;
  updateBack();
  if (pendingRefresh) setTimeout(refreshView, 0);
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

// ---------- updates ----------
let updPoll = 0, updToasted = false;
function setUpdate(u) {
  const was = S.update;
  S.update = u;
  if (!u) return;
  if (u.available && !updToasted && !u.busy) {
    updToasted = true;
    R.toast(`Relic ${u.latest} is out. Open Settings to update.`);
  }
  if (was && was.busy && !u.busy) {
    if (u.ready) R.toast("Update downloaded. Restart Relic to finish.");
    else if (u.error) R.toast(u.error, true);
  }
  clearTimeout(updPoll);
  if (u.busy) updPoll = setTimeout(async () => { try { setUpdate(await R.api("/api/update")); } catch (e) {} }, 700);
  if (screen === "settings") renderUpdate();
}
function renderUpdate() {
  const u = S.update || {};
  const box = $("#upd-status"), acts = $("#upd-actions");
  if (!box) return;
  const how = { dir: "installed", single: "single file", git: "from git", source: "from source" }[u.mode] || "";
  let line, cls = "";
  if (u.ready) { line = `Relic ${u.latest} is ready. Restart to finish.`; cls = "ok"; }
  else if (u.busy) line = `${u.phase || "Working"}…${u.progress != null ? ` ${Math.round(u.progress * 100)}%` : ""}`;
  else if (u.available && u.migrate) { line = "Install Relic so it starts faster and gets a Start menu shortcut."; cls = "ok"; }
  else if (u.available) { line = `Relic ${u.latest} is available.`; cls = "ok"; }
  else if (u.error) { line = u.error; cls = "bad"; }
  else if (u.checked_at) line = `You're up to date${u.latest ? ` (${u.latest})` : ""}.`;
  else line = "Not checked yet.";
  box.innerHTML = `<div class="${cls}">${esc(line)}</div><div class="path">Version ${esc(u.current || S.version)}${how ? ` · ${how}` : ""}</div>`
    + (u.busy && u.progress != null ? `<div class="bar"><i style="width:${Math.round(u.progress * 100)}%"></i></div>` : "")
    + (u.available && u.notes ? `<div class="notes">${esc(u.notes.slice(0, 600))}</div>` : "");
  // Keep focus on the update button as it changes (Check → Update → Restart).
  const cur = R.nav.cur;
  const focused = cur && (acts.contains(cur) || (!document.body.contains(cur) && /^upd-/.test(cur.dataset.do || "")));
  let btn;
  if (u.ready) btn = ["upd-restart", "Restart Relic now"];
  else if (u.busy) btn = null;
  else if (u.available) btn = ["upd-apply", u.migrate ? "Install Relic" : `Update to ${u.latest}`];
  else btn = ["upd-check", "Check for updates"];
  acts.innerHTML = btn ? `<button class="btn" data-nav data-do="${btn[0]}">${esc(btn[1])}</button>` : "";
  if (focused && $("[data-do]", acts)) R.nav.focus($("[data-do]", acts), { scroll: false });
}

// ---------- controller layout ----------
const ACTION_LABEL = { a: "Select / Play", b: "Back", x: "Favorite", y: "Game options", lb: "Previous system",
  rb: "Next system", lt: "Back a letter", rt: "Ahead a letter", select: "Sort / Surprise me", start: "Settings" };
let capturingAct = null;
function renderControls() {
  const N = R.nav;
  $("#controls").innerHTML = N.ACTIONS.map((act) => {
    const wait = capturingAct === act;
    return `<button class="btn bind${wait ? " waiting" : ""}" data-nav data-do="remap" data-act="${act}">
      <span>${esc(ACTION_LABEL[act])}</span>
      ${wait ? `<em>Press a button or key…</em>`
        : `<b class="g g-${N.pad[act]}">${esc(N.padName(act))}</b><b class="k">${esc(N.keyName(act))}</b>`}
    </button>`;
  }).join("");
  const nintendo = N.ACTIONS.every((a) => N.pad[a] === N.NINTENDO_PAD[a]);
  const xbox = N.ACTIONS.every((a) => N.pad[a] === N.DEFAULT_PAD[a]);
  $("#control-presets").innerHTML = `
    <button class="btn theme${xbox ? " on" : ""}" data-nav data-do="pad-preset" data-p="xbox">Xbox layout</button>
    <button class="btn theme${nintendo ? " on" : ""}" data-nav data-do="pad-preset" data-p="nintendo">Nintendo layout</button>
    <button class="btn theme" data-nav data-do="pad-preset" data-p="reset">Reset everything</button>`;
}
async function saveMaps(pad, keys, focusSel) {
  await R.setConfig({ pad_map: pad, key_map: keys });
  R.nav.applyMaps(S.config);
  renderControls();
  hints();
  if (focusSel) R.nav.focus($(focusSel, $("#settings")), { scroll: false });
}
function remap(act) {
  const N = R.nav;
  capturingAct = act;
  renderControls();
  R.nav.focus($(`[data-act="${act}"]`), { scroll: false });
  N.capture(async (r) => {
    capturingAct = null;
    const pad = { ...N.pad }, keys = Object.fromEntries(Object.entries(N.keys).map(([k, v]) => [k, [...v]]));
    if (!r) { renderControls(); R.nav.focus($(`[data-act="${act}"]`), { scroll: false }); return R.toast("Nothing pressed, so nothing changed"); }
    if ("pad" in r) {
      // The action that had this button takes this action's old one: every action keeps a button.
      const other = N.ACTIONS.find((a) => a !== act && pad[a] === r.pad);
      if (other) pad[other] = pad[act];
      pad[act] = r.pad;
      R.toast(`${ACTION_LABEL[act]} is now ${N.PAD_NAMES[r.pad] || `button ${r.pad}`}${other ? ` · ${ACTION_LABEL[other]} moved to ${N.PAD_NAMES[pad[other]] || `button ${pad[other]}`}` : ""}`);
    } else {
      for (const a of N.ACTIONS) if (a !== act) keys[a] = (keys[a] || []).filter((k) => k !== r.key);
      keys[act] = [r.key];
      R.toast(`${ACTION_LABEL[act]} is now the ${r.key === " " ? "Space" : r.key.length === 1 ? r.key.toUpperCase() : r.key} key`);
    }
    R.sound("select");
    await saveMaps(pad, keys, `[data-act="${act}"]`);
  });
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
  ["check_updates", "Check for updates when Relic starts"],
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
  renderControls();
  $("#ver").textContent = S.version;
  const hidden = S.games.filter((g) => g.hidden).length;
  $("#set-extra").innerHTML = (hidden ? `<button class="btn" data-nav data-do="unhide">Show ${hidden} hidden game${hidden === 1 ? "" : "s"} again</button>` : "")
    + (S.native ? `<button class="btn" data-nav data-do="quit">Quit Relic</button>` : "");
  renderUpdate();
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
    if (d === "remap") return remap(el.dataset.act);
    if (d === "pad-preset") {
      const N = R.nav, p = el.dataset.p;
      if (p === "reset") { await saveMaps({}, {}, '[data-p="reset"]'); return R.toast("Buttons and keys are back to normal"); }
      await saveMaps(p === "nintendo" ? { ...N.NINTENDO_PAD } : { ...N.DEFAULT_PAD }, { ...N.keys }, `[data-p="${p}"]`);
      return R.toast(p === "nintendo" ? "Nintendo layout: A and B, X and Y swapped" : "Xbox layout");
    }
    if (d === "unhide") {
      for (const g of S.games.filter((x) => x.hidden)) await setMeta(g, { hidden: false });
      R.toast("Hidden games are back");
      return renderSettings('[data-do="rescan"]');
    }
    if (d === "quit") { const api = R.native(); return api && api.close(); }
    if (d === "upd-check") {
      setUpdate({ ...(S.update || {}), busy: true, phase: "Checking", progress: null });
      const r = await R.api("/api/update", { action: "check" });
      setUpdate(r);
      if (!r.available && !r.error) R.toast("Relic is up to date");
      return;
    }
    if (d === "upd-apply") return setUpdate(await R.api("/api/update", { action: "apply" }));
    if (d === "upd-restart") {
      await R.api("/api/update", { action: "restart" });
      $("#launching-text").textContent = "Restarting Relic…";
      $("#launching").hidden = false;
      return;
    }
    const g = popGame;
    if (d === "pop-play") { closePop(); return launch(g); }
    if (d === "pop-fav") { await toggleFav(g, popReturn); return renderPopActions("fav"); }
    if (d === "pop-core") return cycleCore(g);
    if (d === "pop-core-all") {
      await R.setConfig({ system_cores: { ...(S.config.system_cores || {}), [g.system]: g.core } });
      await setMeta(g, { core: "" });
      R.toast(`Every ${(S.sysById[g.system] || {}).name} game now uses ${coreLabel(g).replace(/^Automatic \((.*)\)$/, "$1")}`);
      return renderPopActions("core");
    }
    if (d === "pop-again") return surprise();
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
  if (!$("#launching").hidden || R.nav.capturing) return true;
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
    if (btn === "lt" || btn === "rt") { letterJump(btn === "lt" ? -1 : 1); return true; }
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
  if (screen === "home" && btn === "select") { surprise(); return true; }
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
    if (!on) api.state().then(winState).catch(() => {});
  } else if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
};
function winCtl(what) {
  const api = R.native();
  if (!api) return;
  if (what === "min") api.minimize();
  else if (what === "full") A.toggleFullscreen();
  else if (what === "max") api.toggle_maximize().then(winState);
  else if (what === "close") api.close();
}
function winState(state) {
  document.body.classList.toggle("win-max", !!state && state !== "normal");
  const b = $('[data-win="max"]');
  if (b) { b.title = state === "normal" ? "Maximize" : "Restore"; b.innerHTML = state === "normal" ? "&#x25A1;" : "&#x2750;"; }
}
A.winState = winState;
$("#top").addEventListener("mousedown", async (e) => {
  const api = R.native();
  if (!api || e.button !== 0 || e.target.closest("button, #now-playing") || document.body.classList.contains("fullscreen")) return;
  if (e.detail === 2) return winState(await api.toggle_maximize());   // double-click the bar
  winState(await api.drag());
});
// Window edges and corners: click and drag to resize (Windows' own resize, so snapping works too).
for (const el of $$(".rz")) el.addEventListener("mousedown", async (e) => {
  const api = R.native();
  if (!api || e.button !== 0) return;
  e.preventDefault();
  try { winState(await api.resize(el.dataset.edge)); } catch (err) {}
});

function tick() {
  $("#clock").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// ---------- live library: rescans happen in the background; show what changed ----------
let pendingRefresh = false;
async function watchLibrary() {
  for (;;) {
    try {
      const r = await R.api(`/api/library?rev=${S.rev || 0}`);
      if (!r.unchanged) {
        S.games = r.games; S.systems = r.systems; S.rev = r.rev;
        S.byId = Object.fromEntries(S.games.map((g) => [g.id, g]));
        S.sysById = Object.fromEntries(S.systems.map((s) => [s.id, s]));
        refreshView();
      }
    } catch (e) { await new Promise((ok) => setTimeout(ok, 5000)); }
  }
}
function refreshView() {
  if (!$("#game-pop").hidden || !$("#launching").hidden) { pendingRefresh = true; return; }
  pendingRefresh = false;
  const cur = R.nav.cur;
  if (screen === "home") renderHome(cur && cur.dataset.key);
  else if (screen === "shelf") openShelf(shelfSys, cur && cur.dataset.game, true);
  else if (screen === "settings") renderSettings();
}

// ---------- start ----------
async function start() {
  tick(); setInterval(tick, 15000);
  try {
    await Promise.all([loadState(), loadLibrary()]);
  } catch (e) {
    R.toast(`Couldn't load your library: ${e.message}`, true);
  }
  if (S.native) nativeReady();
  renderHome();
  watchLibrary();
  // Relic checks GitHub in the background as it starts; pick up the answer.
  setTimeout(async () => {
    try {
      setUpdate(await R.api("/api/update"));
      if (screen === "home" && S.update && S.update.available) renderHome(R.nav.cur && R.nav.cur.dataset.key);
    } catch (e) {}
  }, 5000);
}
function nativeReady() {
  if (document.body.classList.contains("native")) return;
  S.native = true;
  document.body.classList.add("native");
  $("#win-ctl").hidden = false;
  const api = R.native();
  if (!api) return;
  api.is_fullscreen().then((on) => document.body.classList.toggle("fullscreen", !!on)).catch(() => {});
  api.state().then(winState).catch(() => {});
}
window.addEventListener("pywebviewready", nativeReady);
start();
})();
