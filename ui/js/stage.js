/* The 3D stage: your consoles on pedestals in a ring, the chosen one in front, lit in its color and
   slowly turning. Loaded only when the home screen uses it, so the rest of Relic stays light.
   Ideas from Cartucho (github.com/GabrielGoris/cartucho, MIT); models credited in ui/models/CREDITS.md. */
import * as THREE from "three";
import { GLTFLoader } from "/ui/vendor/jsm/loaders/GLTFLoader.js";
import { RoomEnvironment } from "/ui/vendor/jsm/environments/RoomEnvironment.js";
import { MeshoptDecoder } from "/ui/vendor/jsm/libs/meshopt_decoder.module.js";

const PI = Math.PI;
// system id -> [model file, turn, tilt, emissive, min roughness, real size in cm, parts to hide]
const N64_HIDE = /controller|cartridge|joystick|button_controller|trigger|dpad|wire|plug_in|rubber_band|zbutton|abutton|bbutton/i;
const PC = ["retro_crt_computer_1990s_desktop_pc.glb", -PI / 2, 0, undefined, undefined, 42];
const MD = ["sega_mega_drive.glb", 0, 0, undefined, undefined, 28];
const GB = ["game_boy_original.glb", 0, 0, undefined, undefined, 14.8];
const DS = ["nintendo_ds_lite.glb", 0, 0, undefined, undefined, 13.3];
const N64 = ["nintendo_64.glb", 0, 0, undefined, undefined, 26, N64_HIDE];
const NES = ["nintendo_nes_original.glb", PI, 0, undefined, undefined, 25.4];
const MODELS = {
  nes: NES, fds: NES, snes: ["super_nintendo_game_console.glb", 0, 0, undefined, undefined, 24],
  n64: N64, n64dd: N64, gamecube: ["gamecube_console.glb", 0, 0, undefined, undefined, 16],
  wii: ["wii.glb", 0, 0, undefined, undefined, 21.5], switch: ["nintendo_switch.glb", 0, 1.1, undefined, undefined, 24],
  gb: GB, gbc: GB, gba: GB, pokemini: GB, nds: DS, "3ds": DS,
  psx: ["playstation_1.glb", 0, 0, undefined, undefined, 27], ps2: ["ps2_console.glb", PI / 2, 0, undefined, undefined, 30],
  psp: ["sony_psp.glb", 0, 0, undefined, undefined, 17], ps3: ["ps3_slim.glb", PI, 0, undefined, undefined, 29],
  ps4: ["playstation_4_original.glb", PI / 2, 0, 0.3, 0.6, 30.5],
  xbox: ["xbox.glb", 0, 0, undefined, undefined, 32], xbox360: ["xbox_360_black.glb", 0, 0, undefined, undefined, 30.9],
  genesis: MD, segacd: MD, "32x": MD,
  dos: PC, scummvm: PC, c64: PC, amiga: PC, msx: PC, zx: PC, cpc: PC, x68000: PC, pc98: PC, atarist: PC, atari800: PC,
};
const HANDHELD = new Set(["gb", "gbc", "gba", "nds", "3ds", "psp", "gamegear", "lynx", "ngp", "wonderswan", "vb", "pokemini", "supervision", "gw"]);
const size = (cm, flat) => 2.3 * Math.pow(cm / 39, 0.35) * (flat ? 1.15 : 1);
const PAD_Y = 0.026, PAD_TOP = PAD_Y + 0.04;

function geometry(n) {
  const R = Math.max(7.2, (Math.max(1, n) * 3.05) / (PI * 2));
  return { R, STEP: (PI * 2) / Math.max(1, n), HOME: new THREE.Vector3(0, 3.0, R + 8.8), LOOK: new THREE.Vector3(0, 0.6, R - 1.2) };
}
const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

// ------------------------------------------------------------------ loading models: two at a time, nearest first
const loader = new GLTFLoader();
loader.setMeshoptDecoder(MeshoptDecoder);
const fileCache = new Map();
function loadFile(file) {
  if (!fileCache.has(file)) fileCache.set(file, loader.loadAsync(`/ui/models/${file}`));
  return fileCache.get(file);
}

function prepare(gltf, spec) {
  const [, rotY, tiltX, emissive, minRough, cm, hide] = spec;
  const o = gltf.scene.clone(true);
  o.updateMatrixWorld(true);
  const tmp = new THREE.Vector3();
  const drop = [];
  o.traverse((x) => {
    if (!x.isMesh) return;
    const mt = x.material;
    // floors and shadow planes that come with some models; loose parts we don't want
    if (/ground|floor|shadow|backdrop/i.test(x.name) || (mt && mt.transparent && new THREE.Box3().setFromObject(x).getSize(tmp).y < 1e-4)) drop.push(x);
    else if (hide && (hide.test(x.name) || hide.test((mt && mt.name) || ""))) drop.push(x);
  });
  drop.forEach((x) => x.removeFromParent());
  o.traverse((x) => {
    if (!x.isMesh) return;
    const ms = Array.isArray(x.material) ? x.material : [x.material];
    if (ms.some((m) => /invisible/i.test(m.name))) { x.visible = false; return; }
    for (const m of ms) {
      if (emissive !== undefined && m.emissiveMap) m.emissiveIntensity = emissive;
      if (minRough !== undefined && "roughness" in m) { m.roughnessMap = null; m.roughness = Math.max(m.roughness, minRough); m.metalness = Math.min(m.metalness, 0.3); }
      // some exports mark everything see-through, which shows the insides through the case
      if (m.transparent && !/glass|clear|lens/i.test(m.name)) { m.transparent = false; m.depthWrite = true; m.alphaTest = 0.5; }
      m.needsUpdate = true;
    }
  });
  o.rotation.set(tiltX, rotY, 0);
  const inner = new THREE.Group();
  inner.add(o);
  let b = new THREE.Box3().setFromObject(inner);
  const s = b.getSize(tmp);
  const flat = s.y / Math.max(s.x, s.z) < 0.3;
  inner.scale.setScalar(size(cm, flat) / Math.max(s.x, s.y, s.z));
  b = new THREE.Box3().setFromObject(inner);
  const c = b.getCenter(new THREE.Vector3());
  inner.position.set(-c.x, -b.min.y, -c.z);
  return inner;
}

/** A console without a model: a plain box in the system's color, its name on top. */
function generic(sys) {
  const handheld = HANDHELD.has(sys.id);
  const w = handheld ? 1.15 : 2.0, h = handheld ? 1.7 : 0.42, d = handheld ? 0.28 : 1.45;
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshStandardMaterial({ color: 0x1d1d23, roughness: 0.42, metalness: 0.15 }));
  body.position.y = h / 2;
  g.add(body);
  const col = new THREE.Color(sys.color);
  const strip = new THREE.Mesh(new THREE.PlaneGeometry(w * 0.86, Math.max(0.035, h * 0.07)),
    new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 1.4 }));
  strip.position.set(0, handheld ? h * 0.14 : h * 0.55, d / 2 + 0.002);
  g.add(strip);
  // the name, on top (or on the front of a handheld)
  const cv = document.createElement("canvas");
  cv.width = 512; cv.height = 128;
  const x = cv.getContext("2d");
  x.fillStyle = "#26262e"; x.fillRect(0, 0, 512, 128);
  x.fillStyle = "#e8e8ee"; x.font = "800 64px Segoe UI, system-ui, sans-serif"; x.textAlign = "center"; x.textBaseline = "middle";
  x.fillText(sys.name.toUpperCase(), 256, 66, 480);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  const label = new THREE.Mesh(new THREE.PlaneGeometry(handheld ? w * 0.84 : w * 0.8, handheld ? w * 0.21 : w * 0.2), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.6 }));
  if (handheld) label.position.set(0, h * 0.62, d / 2 + 0.003);
  else { label.rotation.x = -PI / 2; label.position.set(0, h + 0.003, 0); }
  g.add(label);
  return g;
}

// ------------------------------------------------------------------ the stage
export function createStage(canvas, { onSelect, onEnter }) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  } catch (e) {
    return null;  // no WebGL here: Relic uses the rows instead
  }
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 80);
  const pm = new THREE.PMREMGenerator(renderer);
  scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.55;

  scene.add(new THREE.HemisphereLight(0x9a8cff, 0x140a24, 1.1));
  const sun = new THREE.DirectionalLight(0xffe2b8, 2.2);
  sun.position.set(3, 6, 9);
  scene.add(sun);
  const spotTarget = new THREE.Object3D();
  scene.add(spotTarget);
  const spot = new THREE.SpotLight(0xffffff, 34, 16, PI / 8, 0.5, 1.2);
  spot.target = spotTarget;
  scene.add(spot);
  const rim = new THREE.PointLight(0xffffff, 14, 8, 1.4);
  scene.add(rim);

  const floor = new THREE.Group();
  scene.add(floor);
  const ring = new THREE.Group();
  scene.add(ring);

  let list = [], G = geometry(1), sel = 0, slots = [];
  const a = { rotNow: 0, rotTarget: 0 };
  const clock = new THREE.Clock();
  let running = false, focusId = "";

  function buildFloor() {
    floor.clear();
    const accent = css("--accent", "#e0a84a"), line = css("--border", "#2e271d"), panel = css("--surface", "#17140f");
    const disc = new THREE.Mesh(new THREE.CylinderGeometry(G.R + 1.3, G.R + 1.4, 0.2, 64),
      new THREE.MeshStandardMaterial({ color: panel, roughness: 0.9, transparent: true, opacity: 0.85 }));
    disc.position.y = -0.12;
    floor.add(disc);
    const edge = new THREE.Mesh(new THREE.RingGeometry(G.R + 1.28, G.R + 1.37, 160), new THREE.MeshBasicMaterial({ color: accent }));
    edge.rotation.x = -PI / 2; edge.position.y = -0.017;
    floor.add(edge);
    const grid = new THREE.GridHelper(60, 60, accent, line);
    grid.position.y = -0.22;
    grid.material.transparent = true; grid.material.opacity = 0.35;
    floor.add(grid);
  }

  function setList(systems, selectId) {
    list = systems;
    G = geometry(list.length);
    ring.clear();
    buildFloor();
    spotTarget.position.set(0, 0, G.R);
    spot.position.set(0, 7, G.R + 0.8);
    rim.position.set(0, 1.6, G.R - 1.6);
    const padColor = css("--surface-2", "#211c15");
    slots = list.map((sys, i) => {
      const ang = i * G.STEP;
      const slot = new THREE.Group();
      slot.position.set(Math.sin(ang) * G.R, 0, Math.cos(ang) * G.R);
      slot.rotation.y = ang;
      const pad = new THREE.Mesh(new THREE.CylinderGeometry(1.4, 1.5, 0.08, 6), new THREE.MeshStandardMaterial({ color: padColor, roughness: 0.55, metalness: 0.08, flatShading: true }));
      pad.position.y = PAD_Y;
      slot.add(pad);
      const wrap = new THREE.Group();
      wrap.position.y = PAD_TOP;
      wrap.userData.index = i;
      slot.add(wrap);
      ring.add(slot);
      return { sys, wrap, loaded: false, pad };
    });
    const i = Math.max(0, list.findIndex((s) => s.id === selectId));
    sel = i;
    a.rotNow = a.rotTarget = -sel * G.STEP;
    light();
    queue();
    resize();
  }

  // Models load in the background, the ones nearest the front first.
  let active = 0;
  function queue() {
    const n = slots.length;
    const order = slots.map((s, i) => [i, Math.min((i - sel + n) % n, (sel - i + n) % n)]).sort((x, y) => x[1] - y[1]);
    for (const [i] of order) {
      if (active >= 2) return;
      const s = slots[i];
      if (s.loaded) continue;
      s.loaded = true;
      const spec = MODELS[s.sys.id];
      if (!spec) { s.wrap.add(generic(s.sys)); continue; }
      active++;
      loadFile(spec[0]).then((gltf) => s.wrap.add(prepare(gltf, spec)))
        .catch(() => s.wrap.add(generic(s.sys)))
        .finally(() => { active--; queue(); });
    }
  }

  function light() {
    const col = new THREE.Color((list[sel] || {}).color || "#ffffff");
    spot.color.copy(col).lerp(new THREE.Color(0xffffff), 0.55);
    rim.color.copy(col);
  }

  function select(i, quiet = false) {
    if (!list.length) return;
    const n = list.length;
    i = ((i % n) + n) % n;
    const base = -i * G.STEP, TAU = PI * 2;
    // turn the short way round (past the last console comes the first again)
    a.rotTarget = base + Math.round((a.rotTarget - base) / TAU) * TAU;
    sel = i;
    light();
    queue();
    if (!quiet) onSelect(list[sel], sel);
  }
  const step = (d) => select(sel + d);

  function resize() {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.fov = w / h < 1.2 ? 50 : 36;
    camera.setViewOffset(w, h, 0, h * 0.08, w, h);
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);

  const tmp = new THREE.Vector3();
  function frame() {
    const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
    a.rotNow += (a.rotTarget - a.rotNow) * Math.min(1, dt * 6);
    ring.rotation.y = a.rotNow;
    slots.forEach((s, i) => {
      const m = s.wrap, on = i === sel;
      if (on) m.rotation.y += dt * 0.6;
      else m.rotation.y += (Math.round(m.rotation.y / (PI * 2)) * PI * 2 - m.rotation.y) * Math.min(1, dt * 3);
      const k = on ? 1 : 0.82;
      m.scale.lerp(tmp.set(k, k, k), Math.min(1, dt * 6));
      const y = on ? PAD_TOP + 0.15 + Math.sin(t * 2) * 0.05 : PAD_TOP;
      m.position.y += (y - m.position.y) * Math.min(1, dt * 6);
    });
    camera.position.copy(G.HOME);
    camera.lookAt(G.LOOK);
    renderer.render(scene, camera);
  }
  function play(on) {
    if (on === running) return;
    running = on;
    if (on) clock.getDelta();
    renderer.setAnimationLoop(on ? frame : null);
  }

  // ---------- mouse: drag or wheel to turn, click to choose or open
  const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
  const drag = { on: false, x0: 0, rot0: 0, moved: false, id: -1 };
  const idxOf = (rot) => { const n = list.length; return ((Math.round(-rot / G.STEP) % n) + n) % n; };
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    Object.assign(drag, { on: true, x0: e.clientX, rot0: a.rotTarget, moved: false, id: e.pointerId });
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag.on || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x0;
    if (!drag.moved && Math.abs(dx) < 6) return;
    if (!drag.moved) { drag.moved = true; try { canvas.setPointerCapture(e.pointerId); } catch (err) {} }
    a.rotTarget = drag.rot0 + (dx / 190) * G.STEP;
    const i = idxOf(a.rotTarget);
    if (i !== sel) { sel = i; light(); queue(); onSelect(list[sel], sel); }
  });
  const up = (e) => {
    if (!drag.on || e.pointerId !== drag.id) return;
    drag.on = false;
    try { canvas.releasePointerCapture(e.pointerId); } catch (err) {}
    if (drag.moved) { a.rotTarget = Math.round(a.rotTarget / G.STEP) * G.STEP; select(idxOf(a.rotTarget)); return; }
    // a click: which console?
    const r = canvas.getBoundingClientRect();
    ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ptr, camera);
    const hit = ray.intersectObjects(slots.map((s) => s.wrap.parent), true)[0];
    if (!hit) return;
    let o = hit.object;
    while (o && !slots.some((s) => s.wrap.parent === o)) o = o.parent;
    const i = slots.findIndex((s) => s.wrap.parent === o);
    if (i < 0) return;
    if (i === sel) onEnter(list[sel], sel); else select(i);
  };
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
  let wheelAt = 0;
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const now = performance.now();
    if (now - wheelAt < 140) return;
    wheelAt = now;
    step(e.deltaY > 0 || e.deltaX > 0 ? 1 : -1);
  }, { passive: false });

  return {
    setList, select, step, play, resize,
    get index() { return sel; },
    get current() { return list[sel]; },
    retheme() { buildFloor(); slots.forEach((s) => s.pad.material.color.set(css("--surface-2", "#211c15"))); },
    destroy() { play(false); ro.disconnect(); renderer.dispose(); },
    onLost(fn) { canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); fn(); }); },
  };
}
