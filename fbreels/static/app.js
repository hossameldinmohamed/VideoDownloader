"use strict";

/* ================================================================ helpers */

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

class Raw { constructor(s) { this.s = s; } }
const raw = (s) => new Raw(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const flat = (v) => (v instanceof Raw ? v.s : Array.isArray(v) ? v.map(flat).join("") : v === false || v == null ? "" : esc(v));
/** Tagged template that escapes every interpolation unless wrapped in raw(). */
function html(strings, ...vals) {
  let out = strings[0];
  vals.forEach((v, i) => { out += flat(v) + strings[i + 1]; });
  return raw(out);
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-Fbreels": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const d = data && data.detail;
    const err = new Error((d && (d.message || (typeof d === "string" ? d : null))) || `Request failed (${res.status})`);
    err.ambiguous = !!(d && d.ambiguous);
    err.status = res.status;
    throw err;
  }
  return data;
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};

function fmtBytes(n) {
  if (!n && n !== 0) return "";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)} ${u[i]}`;
}
const fmtSpeed = (b) => (b ? `${fmtBytes(b)}/s` : "");
function fmtDur(s) {
  if (!s && s !== 0) return "";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}
const fmtEta = (s) => (s ? `${fmtDur(s)} left` : "");
function timeAgo(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString();
}
const plural = (n, w) => `${n.toLocaleString()} ${w}${n === 1 ? "" : "s"}`;

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; }, kind === "err" ? 6500 : 3500);
  setTimeout(() => el.remove(), kind === "err" ? 7000 : 4000);
}

const ICON = {
  check: '<svg viewBox="0 0 24 24"><path d="m5 12 5 5 9-10"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 8v5M12 17h0"/></svg>',
  folder: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg>',
  reveal: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  retry: '<svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.2L3 16M3 21v-5h5"/></svg>',
  stop: '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  list: '<svg viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13M3 6h0M3 12h0M3 18h0"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>',
  yt: '<svg viewBox="0 0 24 24" style="stroke:none;fill:currentColor"><path d="M21.6 7.2a2.5 2.5 0 0 0-1.8-1.8C18.2 5 12 5 12 5s-6.2 0-7.8.4A2.5 2.5 0 0 0 2.4 7.2 26 26 0 0 0 2 12a26 26 0 0 0 .4 4.8 2.5 2.5 0 0 0 1.8 1.8c1.6.4 7.8.4 7.8.4s6.2 0 7.8-.4a2.5 2.5 0 0 0 1.8-1.8A26 26 0 0 0 22 12a26 26 0 0 0-.4-4.8ZM10 15V9l5.2 3Z"/></svg>',
  fb: '<svg viewBox="0 0 24 24" style="stroke:none;fill:currentColor"><path d="M14 8h3V4h-3a4 4 0 0 0-4 4v2H8v4h2v8h4v-8h3l1-4h-4V8Z"/></svg>',
};

/* ================================================================ state */

const state = {
  settings: null,
  options: null,
  platform: "auto",
  jobs: [],
  expanded: new Set(store.get("expanded", [])),
  details: new Map(),   // job id -> {items, filter, limit}
  cardCache: new Map(), // job id -> last rendered html
  prevStatus: new Map(),
  preview: null,
  pendingAction: null,
  system: null,
  mode: "local", // local | remote | preview — see applyMode()
};

const PLATFORM_NAME = { youtube: "YouTube", facebook: "Facebook" };
const KIND_NAME = { channel: "channel", playlist: "playlist", video: "video", page: "page" };
const STATUS_LABEL = {
  queued: "Queued", scanning: "Scanning", downloading: "Downloading", done: "Done", partial: "Finished with errors",
  failed: "Failed", cancelled: "Cancelled", interrupted: "Interrupted",
};
const ACTIVE = new Set(["queued", "scanning", "downloading"]);

/* ================================================================ tabs & theme */

function showView(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  $$(".view").forEach((v) => { v.hidden = v.id !== `view-${name}`; });
  store.set("view", name);
  if (name === "library") loadLibrary();
  if (name === "settings") loadSystem();
}
$$(".tab").forEach((t) => t.addEventListener("click", () => showView(t.dataset.view)));

$("#theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch { /* ignore */ }
});

/* ================================================================ segmented controls */

function segmented(el, value, onChange) {
  const btns = $$("button", el);
  const set = (v) => btns.forEach((b) => b.classList.toggle("on", b.dataset.value === String(v)));
  set(value);
  btns.forEach((b) => b.addEventListener("click", (e) => {
    e.preventDefault();
    set(b.dataset.value);
    onChange(b.dataset.value);
  }));
  return set;
}

/* ================================================================ options */

const optionControls = {};

function renderOptionChips() {
  const o = state.options;
  const q = o.quality === "best" ? "Best quality" : o.quality === "2160" ? "Up to 4K" : `Up to ${o.quality}p`;
  const f = { mp4: "MP4", original: "MP4 (original codec)", mp3: "MP3", m4a: "M4A" }[o.format];
  const n = { number_title: "001 - Title", number: "001", title: "Title" }[o.naming];
  const chips = [q, f, n];
  if (o.subtitles) chips.push("Subtitles");
  if (o.cookies_browser) chips.push(`Cookies: ${o.cookies_browser}`);
  chips.push(`${o.workers}× parallel`);
  $("#option-chips").innerHTML = chips.map((c) => `<span>${esc(c)}</span>`).join("");
}

const saveOptions = debounce(async () => {
  try {
    const s = await api("PUT", "/api/settings", { options: state.options });
    state.settings = s;
  } catch (e) { toast(e.message, "err"); }
}, 500);

function setOption(k, v) {
  state.options[k] = v;
  renderOptionChips();
  // Sizes depend on quality and format: show (and fetch) the new ones.
  if (state.picker && (k === "format" || k === "quality")) rerenderKeepingPlace();
  else if (state.picker) renderFooter();
  saveOptions();
}

function applyOptionsToControls() {
  const o = state.options;
  optionControls.quality(o.quality);
  optionControls.format(o.format);
  optionControls.naming(o.naming);
  $("#opt-workers").value = o.workers;
  $("#opt-workers-out").textContent = o.workers;
  $("#opt-subtitles").checked = !!o.subtitles;
  $("#opt-sub-langs").value = o.sub_langs || "en.*";
  $("#opt-auto-subs").checked = !!o.auto_subs;
  $$(".sub-opts input").forEach((i) => { i.disabled = !o.subtitles; });
  $("#opt-thumb").checked = !!o.embed_thumbnail;
  $("#opt-meta").checked = !!o.embed_metadata;
  $("#opt-cookies").value = o.cookies_browser || "";
  $("#opt-rate").value = o.rate_limit || "";
  renderOptionChips();
}

function bindOptions() {
  optionControls.quality = segmented($("#opt-quality"), "best", (v) => setOption("quality", v));
  optionControls.format = segmented($("#opt-format"), "mp4", (v) => {
    const audioBefore = ["mp3", "m4a"].includes(state.options.format);
    setOption("format", v);
    // video and audio downloads are tracked separately — re-check what's "downloaded"
    if (audioBefore !== ["mp3", "m4a"].includes(v)) setTimeout(refreshPickerFlags, 600);
  });
  optionControls.naming = segmented($("#opt-naming"), "number_title", (v) => setOption("naming", v));
  $("#opt-workers").addEventListener("input", (e) => {
    $("#opt-workers-out").textContent = e.target.value;
    setOption("workers", parseInt(e.target.value, 10));
  });
  $("#opt-subtitles").addEventListener("change", (e) => {
    $$(".sub-opts input").forEach((i) => { i.disabled = !e.target.checked; });
    setOption("subtitles", e.target.checked);
  });
  $("#opt-sub-langs").addEventListener("input", (e) => setOption("sub_langs", e.target.value));
  $("#opt-auto-subs").addEventListener("change", (e) => setOption("auto_subs", e.target.checked));
  $("#opt-thumb").addEventListener("change", (e) => setOption("embed_thumbnail", e.target.checked));
  $("#opt-meta").addEventListener("change", (e) => setOption("embed_metadata", e.target.checked));
  $("#opt-cookies").addEventListener("change", (e) => setOption("cookies_browser", e.target.value));
  $("#opt-rate").addEventListener("input", (e) => setOption("rate_limit", e.target.value.trim()));
  $("#opt-output").addEventListener("change", (e) => setOutputDir(e.target.value.trim()));
  $("#btn-pick-folder").addEventListener("click", chooseFolder);
  $("#btn-open-output").addEventListener("click", () => openPath($("#opt-output").value.trim()));
  $("#btn-reset-options").addEventListener("click", async () => {
    state.options = {
      quality: "best", format: "mp4", tabs: ["videos"], naming: "number_title", limit: null, subtitles: false,
      sub_langs: "en.*", auto_subs: false, embed_thumbnail: true, embed_metadata: true, workers: 3,
      cookies_browser: "", rate_limit: "",
    };
    applyOptionsToControls();
    saveOptions();
    toast("Options reset.");
  });
  const panel = $("#options-panel");
  panel.open = store.get("optionsOpen", false);
  panel.addEventListener("toggle", () => store.set("optionsOpen", panel.open));
}

/** Where the current picker's videos will land: <save folder>/<channel>/… */
function pickerFolder() {
  const p = state.picker;
  if (!p) return "";
  const root = $("#opt-output").value.trim().replace(/\/+$/, "");
  const parts = p.lk.folder_parts;
  if (!parts || !parts.length) return root;
  // A channel's tabs go into sub-folders of the channel folder; a pasted
  // playlist or video goes exactly where its own path says.
  return `${root}/${(p.lk.kind === "channel" || p.lk.kind === "page" ? parts.slice(0, 1) : parts).join("/")}`;
}

function renderPickerFolder() {
  const el = $("#pk-folder-path");
  const path = pickerFolder();
  // bidi-isolate so the RTL ellipsis trick keeps the end of the path visible
  el.textContent = `\u2066${path}\u2069`;
  el.title = path;
}

async function setOutputDir(path) {
  if (!path) return;
  try {
    const s = await api("PUT", "/api/settings", { output_dir: path });
    state.settings = s;
    $("#opt-output").value = s.output_dir;
    toast(`Saving downloads to ${s.output_dir}`, "ok");
    if (state.picker) { renderPickerFolder(); refreshPickerFlags(); }
  } catch (e) {
    $("#opt-output").value = state.settings ? state.settings.output_dir : $("#opt-output").value;
    toast(e.message, "err");
  }
}

async function chooseFolder() {
  let path = null;
  try {
    path = (await api("POST", "/api/pick-folder")).path;
  } catch (e) {
    // No native picker (not macOS): let them type it.
    path = window.prompt("Folder to save downloads in:", $("#opt-output").value.trim());
  }
  if (path) await setOutputDir(path.trim());
}

async function openPath(path, reveal = false) {
  try { await api("POST", "/api/open", { path, reveal }); } catch (e) { toast(e.message, "err"); }
}

/* ================================================================ input & detection */

const inputEl = $("#input");

function inputLines() {
  return inputEl.value.split(/\n+/).map((s) => s.trim()).filter(Boolean);
}

function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 200)}px`;
}

function setChip(el, text, cls) {
  el.hidden = !text;
  el.className = `platform-chip ${cls || ""}`;
  el.innerHTML = text;
}

function updateFindButton() {
  const n = inputLines().length;
  $("#btn-find-label").textContent = n > 1 ? `Download all ${n}` : "Find videos";
  $("#multi-hint").hidden = n < 2;
}

const detect = debounce(async () => {
  const chip = $("#detect-chip");
  const lines = inputLines();
  $("#ambiguous").hidden = true;
  updateFindButton();
  if (!lines.length) return setChip(chip, "");
  if (lines.length > 1) return setChip(chip, esc(`${lines.length} links`));
  try {
    const t = await api("POST", "/api/resolve", { input: lines[0], platform: state.platform });
    const icon = t.platform === "youtube" ? ICON.yt : ICON.fb;
    setChip(chip, `${icon}${esc(`${PLATFORM_NAME[t.platform]} ${KIND_NAME[t.kind]}`)}`, t.platform);
  } catch (e) {
    setChip(chip, esc(e.ambiguous ? "Which platform?" : "Not recognized"), e.ambiguous ? "" : "error");
  }
}, 250);

inputEl.addEventListener("input", () => { autoGrow(); updateFindButton(); detect(); });
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); onFind(); }
});
$("#find-form").addEventListener("submit", (e) => { e.preventDefault(); onFind(); });

const setPlatform = segmented($("#platform"), "auto", (v) => { state.platform = v; detect(); });

$$("[data-example]").forEach((b) => b.addEventListener("click", () => {
  inputEl.value = b.dataset.example;
  autoGrow(); detect(); onFind();
}));

function showAmbiguous(message, action) {
  state.pendingAction = action;
  $("#ambiguous-text").textContent = message;
  $("#ambiguous").hidden = false;
}
$$("#ambiguous [data-pick]").forEach((b) => b.addEventListener("click", () => {
  state.platform = b.dataset.pick;
  setPlatform(state.platform);
  $("#ambiguous").hidden = true;
  detect();
  const act = state.pendingAction;
  state.pendingAction = null;
  if (act) act();
}));

function maybeAskNotify() {
  if (store.get("notify", true) && "Notification" in window && Notification.permission === "default") {
    Notification.requestPermission().catch(() => {});
  }
}

function onFind() {
  const lines = inputLines();
  if (!lines.length) { inputEl.focus(); return toast("Paste a link, @handle or page name first."); }
  if (lines.length > 1) return downloadMany(lines);
  return openLookup(lines[0]);
}

async function downloadMany(inputs) {
  const btn = $("#btn-find");
  btn.disabled = true;
  try {
    if (!(await prepareDevice())) return; // no folder on this device: don't start
    const r = await api("POST", "/api/jobs", {
      inputs, platform: state.platform, options: { ...state.options, limit: null, tabs: ["videos"] },
      output_dir: $("#opt-output").value.trim(),
    });
    trackDevice(r.jobs);
    toast(`Queued ${r.jobs.length} downloads.`, "ok");
    inputEl.value = "";
    autoGrow(); detect();
    maybeAskNotify();
    pollNow();
  } catch (e) {
    if (e.ambiguous) showAmbiguous(e.message, () => downloadMany(inputs));
    else toast(e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

/* ================================================================ picker */

const PAGE = 120;
const COLLECTION_NOUN = { playlists: "playlist", podcasts: "podcast", releases: "release", courses: "course" };
const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

async function openLookup(input) {
  // Keep the current picker on screen until the new one is ready — if the
  // lookup fails you haven't lost what you were looking at.
  $("#find-loading").hidden = false;
  $("#btn-find").disabled = true;
  try {
    const lk = await api("POST", "/api/lookup", { input, platform: state.platform, options: state.options });
    state.picker = {
      input, lk, groups: new Map(), sel: new Map(), queued: new Set(), errors: new Map(),
      view: null, search: "", sort: "newest", list: [], shown: 0, autoPicked: false, loading: new Set(),
      info: new Map(), extra: new Map(), detailQueue: [], detailBusy: 0,
    };
    renderPickerHead();
    $("#picker").hidden = false;
    renderFooter();
    openView(lk.default_tab);
    $("#picker").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    if (e.ambiguous) showAmbiguous(e.message, () => openLookup(input));
    else toast(e.message, "err");
  } finally {
    $("#find-loading").hidden = true;
    $("#btn-find").disabled = false;
  }
}

const tabOf = (key) => (key.startsWith("pl:") ? key.split(":")[1] : key);
const selSize = (pred) => [...state.picker.sel].reduce((a, [k, set]) => a + (pred(k) ? set.size : 0), 0);
const selFor = (key) => {
  const p = state.picker;
  if (!p.sel.has(key)) p.sel.set(key, new Set());
  return p.sel.get(key);
};

function renderPickerHead() {
  const { lk } = state.picker;
  $("#pk-title").textContent = lk.title;
  setChip($("#pk-platform"), `${lk.platform === "youtube" ? ICON.yt : ICON.fb}${esc(PLATFORM_NAME[lk.platform])}`, lk.platform);
  const sub = [];
  if (lk.subscribers) sub.push(`${compact.format(lk.subscribers)} subscribers`);
  if (lk.subtitle) sub.push(lk.subtitle);
  if (lk.count) sub.push(plural(lk.count, "video"));
  $("#pk-sub").textContent = sub.join(" · ");
  renderPickerFolder();
  $("#pk-notice").hidden = !(lk.kind === "video" && lk.playlist);
  if (lk.avatar) {
    $("#pk-avatar").src = lk.avatar; $("#pk-avatar").hidden = false; $("#pk-avatar-ph").hidden = true;
  } else {
    $("#pk-avatar").hidden = true; $("#pk-avatar-ph").hidden = false;
    $("#pk-avatar-ph").textContent = (lk.title || "?").trim().charAt(0).toUpperCase();
  }
}

function renderTabs() {
  const p = state.picker;
  const tabs = p.lk.tabs;
  const bar = $("#pk-tabs");
  bar.hidden = tabs.length < 2;
  bar.innerHTML = flat(tabs.map((t) => {
    const g = p.groups.get(t.key);
    const picked = selSize((k) => tabOf(k) === t.key);
    const on = tabOf(p.view || "") === t.key;
    return html`<button class="pk-tab ${on ? "on" : ""}" data-tab="${t.key}" role="tab">
      ${t.label}${g ? html` <span class="count">${g.items.length.toLocaleString()}</span>` : ""}
      ${p.loading.has(t.key) ? raw('<span class="spinner sm"></span>') : ""}
      ${picked ? html`<span class="picked">${picked} ✓</span>` : ""}
    </button>`;
  }));
}
$("#pk-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]");
  if (b) openView(b.dataset.tab);
});

async function loadGroup(key) {
  const p = state.picker;
  const r = await api("POST", `/api/lookup/${p.lk.lookup_id}/group`, { key, options: state.options });
  if (state.picker !== p) return null; // picker was closed/replaced meanwhile
  Object.assign(p.lk, r.lookup);
  p.groups.set(key, r.group);
  return r.group;
}

async function openView(key) {
  const p = state.picker;
  p.view = key;
  p.search = "";
  $("#pk-search").value = "";
  renderTabs();
  renderView();
  if (p.groups.has(key) || p.loading.has(key)) return;
  p.loading.add(key);
  p.errors.delete(key);
  renderTabs();
  renderView();
  try {
    const g = await loadGroup(key);
    if (!g) return;
    renderPickerHead();
    // First list you open: pre-tick everything you don't have yet.
    if (!p.autoPicked && g.type !== "collections") {
      const s = selFor(key);
      g.items.forEach((i) => { if (!i.downloaded && !i.unavailable) s.add(i.key); });
      p.autoPicked = true;
    }
  } catch (e) {
    p.errors.set(key, e.message);
  } finally {
    p.loading.delete(key);
  }
  if (state.picker === p) { renderTabs(); if (p.view === key) renderView(); renderFooter(); }
}

function orderedItems(g) {
  const p = state.picker;
  let items = g.items;
  if (g.chrono === "oldest_first" && p.sort === "newest") items = [...items].reverse();
  if (g.chrono === "newest_first" && p.sort === "oldest") items = [...items].reverse();
  const q = p.search.trim().toLowerCase();
  return q ? items.filter((i) => String(i.title).toLowerCase().includes(q)) : items;
}

function loadingMessage(key) {
  const { lk } = state.picker;
  if (lk.platform === "facebook") {
    return "Scrolling through the page's reels — big pages take a few minutes. If a Facebook login window opens, sign in there.";
  }
  const tab = lk.tabs.find((t) => t.key === key);
  return `Loading ${tab ? tab.label.toLowerCase() : "videos"}… big channels take a moment.`;
}

function renderView() {
  const p = state.picker;
  const key = p.view;
  const g = p.groups.get(key);
  const grid = $("#pk-grid");
  const stateEl = $("#pk-state");

  // breadcrumb inside Playlists / Podcasts…
  const inCollection = key.startsWith("pl:");
  $("#pk-crumb").hidden = !inCollection;
  if (inCollection) {
    const parent = p.lk.tabs.find((t) => t.key === tabOf(key));
    $("#pk-back-label").textContent = `All ${parent ? parent.label.toLowerCase() : "playlists"}`;
    $("#pk-crumb-title").textContent = g ? g.label : "…";
  }

  const err = p.errors.get(key);
  const busy = p.loading.has(key);
  const isColl = g && g.type === "collections";
  $("#pk-toolbar").hidden = !g;
  $("#pk-sort").hidden = !g || isColl || !g.chrono;
  $("#pk-selectbar").hidden = !g;
  $("#pk-sel-new").hidden = $("#pk-sel-all").hidden = !!isColl;
  $("#pk-sel-lists").hidden = !isColl;
  $("#pk-search").placeholder = isColl ? `Filter ${g.label.toLowerCase()}…` : "Filter by title…";

  cardObserver.disconnect();
  grid.innerHTML = "";
  p.list = [];
  p.shown = 0;
  stateEl.hidden = !(busy || err || (g && !g.items.length));
  if (busy) {
    stateEl.innerHTML = flat(html`<div class="spinner"></div><div>${loadingMessage(key)}</div>`);
    return;
  }
  if (err) {
    stateEl.innerHTML = flat(html`<div>${err}<br><button class="btn small" data-retry="${key}" style="margin-top:10px">Try again</button></div>`);
    return;
  }
  if (!g) return;
  if (!g.items.length) {
    stateEl.innerHTML = flat(html`<div>Nothing here yet.</div>`);
    return;
  }

  grid.classList.toggle("portrait", g.type === "shorts");
  p.list = orderedItems(g);
  appendCards();
  renderStats();
}

function renderStats() {
  const p = state.picker;
  const g = p.groups.get(p.view);
  if (!g) return;
  if (g.type === "collections") {
    const noun = COLLECTION_NOUN[p.view] || "playlist";
    const picked = selSize((k) => tabOf(k) === p.view);
    $("#pk-stats").textContent = p.bulkLoading
      ? `Loading ${noun}s… ${p.bulkLoading}`
      : `${plural(g.items.length, noun)} · tick one to grab all its new videos, or open it to choose${picked ? ` · ${picked.toLocaleString()} videos ticked` : ""}`;
    return;
  }
  const total = g.items.length;
  const got = g.items.filter((i) => i.downloaded).length;
  const off = g.items.filter((i) => i.unavailable).length;
  const fresh = total - got - off;
  const parts = [plural(total, "video")];
  if (got) parts.push(`${got.toLocaleString()} already downloaded`);
  parts.push(`${fresh.toLocaleString()} new`);
  if (off) parts.push(`${off} live/upcoming (can't download yet)`);
  if (p.search) parts.push(`${p.list.length.toLocaleString()} match`);
  $("#pk-stats").textContent = parts.join(" · ");
}

function videoCard(i, key) {
  const p = state.picker;
  const sel = selFor(key).has(i.key);
  const queued = p.queued.has(`${key}|${i.key}`);
  const thumb = i.thumbnail
    ? html`<img loading="lazy" src="${i.thumbnail}" alt="" referrerpolicy="no-referrer">`
    : html`<div class="ph">${i.number != null ? `#${i.number}` : "▶"}</div>`;
  let badge = "";
  if (i.unavailable) badge = html`<span class="badge off">${i.unavailable}</span>`;
  else if (queued) badge = html`<span class="badge queued">In queue</span>`;
  else if (i.downloaded) badge = html`<span class="badge got">${raw(ICON.check)} Downloaded</span>`;
  const { duration, title, size } = cardDetails(i);
  const meta = [i.views ? `${compact.format(i.views)} views` : "", size].filter(Boolean).join(" · ");
  return html`<div class="vcard ${sel ? "sel" : ""} ${i.downloaded ? "got" : ""} ${i.unavailable ? "off" : ""} ${badge ? "has-badge" : ""}"
      data-key="${i.key}" title="${title}" role="checkbox" aria-checked="${sel}">
    <div class="thumb">${thumb}
      ${i.number != null && i.thumbnail ? html`<span class="badge num">#${i.number}</span>` : ""}
      ${duration ? html`<span class="badge dur">${fmtDur(duration)}</span>` : ""}
      ${badge}
    </div>
    <span class="tick">${raw(ICON.check)}</span>
    <div class="vtitle">${title}</div>
    ${meta ? html`<div class="vmeta">${meta}</div>` : ""}
  </div>`;
}

/* ---- length & download size: one request per video, so they're fetched in
   the background for the cards on screen and for what's ticked. */

const DETAIL_WORKERS = 3;
const MAX_SIZED_SELECTION = 300;
const optsSig = () => `${state.options.format}|${state.options.quality}`;
const sizeOf = (key) => {
  const d = state.picker.info.get(`${optsSig()}|${key}`);
  return d && typeof d === "object" ? d : null;
};

function cardDetails(i) {
  const p = state.picker;
  const x = p.extra.get(i.key);
  const d = sizeOf(i.key);
  return {
    duration: i.duration || x?.duration,
    // Facebook's Reels tab has no captions; the video page has the real title.
    title: (x?.title && /^Reel \d+$/.test(i.title)) ? x.title : i.title,
    size: d?.size ? `${d.size_exact ? "" : "≈"}${fmtBytes(d.size)}` : "",
  };
}

function wantDetails(keys, front = false) {
  const p = state.picker;
  const sig = optsSig();
  const queued = new Set(p.detailQueue);
  const fresh = keys.filter((k) => !p.info.has(`${sig}|${k}`) && !queued.has(k));
  if (!fresh.length) return;
  p.detailQueue = front ? [...fresh, ...p.detailQueue] : [...p.detailQueue, ...fresh];
  pumpDetails();
}

function pumpDetails() {
  const p = state.picker;
  while (p && p.detailBusy < DETAIL_WORKERS && p.detailQueue.length) {
    const key = p.detailQueue.shift();
    const id = `${optsSig()}|${key}`;
    if (p.info.has(id)) continue;
    p.info.set(id, "busy");
    p.detailBusy++;
    api("POST", `/api/lookup/${p.lk.lookup_id}/details`, { key, options: state.options })
      .then((d) => { p.info.set(id, d); p.extra.set(key, d); })
      .catch(() => p.info.set(id, "err"))
      .finally(() => {
        p.detailBusy--;
        if (state.picker !== p) return;
        updateCard(key);
        renderFooter();
        pumpDetails();
      });
  }
}

function updateCard(key) {
  const p = state.picker;
  const card = $(`#pk-grid .vcard[data-key="${CSS.escape(key)}"]`);
  const item = card && p.list.find((i) => i.key === key);
  if (!item) return;
  const tmp = document.createElement("div");
  tmp.innerHTML = flat(videoCard(item, p.view));
  const fresh = tmp.firstElementChild;
  card.replaceWith(fresh);
  cardObserver.observe(fresh);
}

const cardObserver = new IntersectionObserver((entries) => {
  const p = state.picker;
  if (!p) return;
  const sel = selFor(p.view);
  const show = [];
  const hide = new Set();
  entries.forEach((e) => {
    const c = e.target;
    if (c.classList.contains("off") || c.classList.contains("got")) return;
    if (e.isIntersecting) show.push(c.dataset.key);
    else if (!sel.has(c.dataset.key)) hide.add(c.dataset.key);
  });
  // Scrolled past before its turn came: don't spend a request on it.
  if (hide.size) p.detailQueue = p.detailQueue.filter((k) => !hide.has(k));
  wantDetails(show, true);
}, { rootMargin: "200px" });

/** Total length and size of what's ticked: {secs, bytes, approx, unsized, measuring, tooMany}. */
function selectionDetails() {
  const p = state.picker;
  const t = { secs: 0, bytes: 0, approx: false, unsized: 0, measuring: 0, tooMany: false };
  const keys = [];
  for (const [k, s] of p.sel) {
    if (!s.size) continue;
    const g = p.groups.get(k);
    const byKey = new Map((g?.items || []).map((i) => [i.key, i]));
    for (const key of s) {
      keys.push(key);
      t.secs += byKey.get(key)?.duration || p.extra.get(key)?.duration || 0;
      const d = sizeOf(key);
      if (d?.size) { t.bytes += d.size; t.approx ||= !d.size_exact; } else t.unsized++;
      if (p.info.get(`${optsSig()}|${key}`) === "busy" || p.detailQueue.includes(key)) t.measuring++;
    }
  }
  if (keys.length > MAX_SIZED_SELECTION) t.tooMany = true;
  else wantDetails(keys);
  return t;
}

function collectionCard(c, tab) {
  const p = state.picker;
  const key = `pl:${tab}:${c.key}`;
  const picked = selSize((k) => k === key);
  const got = p.groups.get(key);
  const info = got
    ? `${plural(got.items.length, "video")}${got.items.some((i) => i.downloaded) ? ` · ${got.items.filter((i) => i.downloaded).length} downloaded` : ""}`
    : `Open ${COLLECTION_NOUN[tab] || "playlist"}`;
  const busy = p.loading.has(key);
  return html`<button class="pcard ${picked ? "sel" : ""}" data-open="${key}" title="${c.title}">
    <span class="ptick" data-whole="${key}" title="${picked ? "Untick this playlist" : "Tick every new video in it"}">
      ${busy ? raw('<span class="spinner sm"></span>') : raw(ICON.check)}
    </span>
    <div class="thumb">
      ${c.thumbnail ? html`<img loading="lazy" src="${c.thumbnail}" alt="" referrerpolicy="no-referrer">` : html`<div class="ph">▶</div>`}
      ${picked ? html`<span class="picked">${picked} ✓</span>` : ""}
    </div>
    <div class="vtitle">${c.title}</div>
    <div class="vmeta">${info}</div>
  </button>`;
}

function appendCards() {
  const p = state.picker;
  if (!p || p.shown >= p.list.length) return;
  const g = p.groups.get(p.view);
  const next = p.list.slice(p.shown, p.shown + PAGE);
  p.shown += next.length;
  const cards = g.type === "collections" ? next.map((c) => collectionCard(c, p.view)) : next.map((i) => videoCard(i, p.view));
  const grid = $("#pk-grid");
  grid.insertAdjacentHTML("beforeend", flat(cards));
  if (g.type !== "collections") [...grid.children].slice(-next.length).forEach((c) => cardObserver.observe(c));
}

new IntersectionObserver((entries) => {
  if (entries.some((e) => e.isIntersecting)) appendCards();
}, { rootMargin: "900px" }).observe($("#pk-sentinel"));

function refreshCard(card) {
  const p = state.picker;
  const on = selFor(p.view).has(card.dataset.key);
  card.classList.toggle("sel", on);
  card.setAttribute("aria-checked", on);
}

$("#pk-grid").addEventListener("click", (e) => {
  const p = state.picker;
  const whole = e.target.closest("[data-whole]");
  if (whole) { e.stopPropagation(); return toggleWholePlaylist(whole.dataset.whole); }
  const open = e.target.closest("[data-open]");
  if (open) return openView(open.dataset.open);
  const card = e.target.closest(".vcard");
  if (!card || card.classList.contains("off")) return;
  const s = selFor(p.view);
  if (s.has(card.dataset.key)) s.delete(card.dataset.key); else s.add(card.dataset.key);
  refreshCard(card);
  renderTabs();
  renderFooter();
});
$("#pk-state").addEventListener("click", (e) => {
  const b = e.target.closest("[data-retry]");
  if (b) { state.picker.errors.delete(b.dataset.retry); openView(b.dataset.retry); }
});

function bulkSelect(fn) {
  const p = state.picker;
  const s = selFor(p.view);
  const g = p.groups.get(p.view);
  // Search narrows what the buttons act on.
  const scope = p.search ? p.list : g.items;
  scope.forEach((i) => {
    if (i.unavailable) return;
    if (fn(i)) s.add(i.key); else s.delete(i.key);
  });
  $$(".vcard", $("#pk-grid")).forEach(refreshCard);
  renderTabs();
  renderFooter();
}
$("#pk-sel-new").addEventListener("click", () => bulkSelect((i) => !i.downloaded && !state.picker.queued.has(`${state.picker.view}|${i.key}`)));
$("#pk-sel-all").addEventListener("click", () => bulkSelect(() => true));
$("#pk-sel-none").addEventListener("click", () => {
  const p = state.picker;
  if (p.groups.get(p.view)?.type === "collections") {
    [...p.sel.keys()].filter((k) => k.startsWith(`pl:${p.view}:`)).forEach((k) => p.sel.delete(k));
    return rerenderKeepingPlace();
  }
  bulkSelect(() => false);
});

$("#pk-search").addEventListener("input", debounce((e) => { state.picker.search = e.target.value; renderView(); }, 150));
segmented($("#pk-sort"), "newest", (v) => { state.picker.sort = v; renderView(); });
$("#pk-back").addEventListener("click", () => openView(tabOf(state.picker.view)));
$("#pk-close").addEventListener("click", () => { $("#picker").hidden = true; state.picker = null; });

function groupLabel(key) {
  const p = state.picker;
  const g = p.groups.get(key);
  if (g) return g.label;
  const t = p.lk.tabs.find((x) => x.key === key);
  return t ? t.label : key;
}

function renderFooter() {
  const p = state.picker;
  if (!p) return;
  const total = selSize(() => true);
  const parts = [...p.sel].filter(([, s]) => s.size).map(([k, s]) => `${groupLabel(k)} ${s.size.toLocaleString()}`);
  let summary = "";
  if (total) {
    const t = selectionDetails();
    const known = total - t.unsized;
    if (t.secs) parts.push(`${fmtDur(t.secs)} total`);
    if (t.tooMany) parts.push(`size: tick ${MAX_SIZED_SELECTION} or fewer to measure it`);
    else if (t.measuring) parts.push(`measuring size… ${known} of ${total}`);
    else if (t.unsized) parts.push(`size unknown for ${t.unsized}`);
    if (t.bytes) summary = ` · ${t.approx || t.unsized ? "≈" : ""}${fmtBytes(t.bytes)}${t.unsized ? "+" : ""}`;
  }
  $("#pk-count").textContent = total ? `${plural(total, "video")} selected${summary}` : "Nothing selected";
  $("#pk-breakdown").textContent = total ? parts.join(" · ") : "Tick the videos you want.";
  $("#pk-download").disabled = total === 0 || state.mode === "preview";
  $("#pk-download-label").textContent = state.mode === "preview" ? "Can't download in the preview"
    : total ? `Download ${total.toLocaleString()}` : "Download";
  const o = state.options;
  const q = o.quality === "best" ? "Best quality" : o.quality === "2160" ? "Up to 4K" : `Up to ${o.quality}p`;
  const f = { mp4: "MP4", original: "MP4 (original)", mp3: "MP3", m4a: "M4A" }[o.format];
  $("#pk-opts").textContent = `${q} · ${f} · change`;
}
$("#pk-opts").addEventListener("click", () => {
  const panel = $("#options-panel");
  panel.open = true;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
});

$("#pk-download").addEventListener("click", async () => {
  const p = state.picker;
  const selections = Object.fromEntries([...p.sel].filter(([, s]) => s.size).map(([k, s]) => [k, [...s]]));
  const btn = $("#pk-download");
  btn.disabled = true;
  try {
    if (!(await prepareDevice())) return; // no folder on this device: don't start
    const r = await api("POST", "/api/jobs", {
      lookup_id: p.lk.lookup_id, selections, inputs: [p.input],
      options: { ...state.options, limit: null }, output_dir: $("#opt-output").value.trim(),
    });
    trackDevice(r.jobs);
    const n = selSize(() => true);
    for (const [k, s] of p.sel) s.forEach((v) => p.queued.add(`${k}|${v}`));
    p.sel.clear();
    toast(`Queued ${plural(n, "video")} — progress is below.`, "ok");
    rerenderKeepingPlace();
    maybeAskNotify();
    pollNow();
  } catch (e) {
    toast(e.message, "err");
  } finally {
    renderFooter();
  }
});

/** Tick (or untick) every new video in a playlist without opening it. */
async function toggleWholePlaylist(key, force) {
  const p = state.picker;
  const on = force ?? !selSize((k) => k === key);
  if (!on) { p.sel.delete(key); rerenderKeepingPlace(); return; }
  if (!p.groups.has(key)) {
    if (p.loading.has(key)) return;
    p.loading.add(key);
    rerenderKeepingPlace();
    try { await loadGroup(key); } catch (e) { toast(e.message, "err"); } finally { p.loading.delete(key); }
    if (state.picker !== p || !p.groups.has(key)) return rerenderKeepingPlace();
  }
  const s = selFor(key);
  p.groups.get(key).items.forEach((i) => { if (!i.downloaded && !i.unavailable) s.add(i.key); });
  if (!s.size) {
    const items = p.groups.get(key).items;
    const why = items.length && items.every((i) => i.unavailable)
      ? "only has live or upcoming streams, which can't be downloaded yet"
      : items.length ? "is already downloaded" : "is empty";
    toast(`“${p.groups.get(key).label}” ${why}.`);
  }
  rerenderKeepingPlace();
}

$("#pk-sel-lists").addEventListener("click", async () => {
  const p = state.picker;
  const tab = p.view;
  const g = p.groups.get(tab);
  if (!g || p.bulkLoading) return;
  const scope = p.search ? p.list : g.items;
  const keys = scope.map((c) => `pl:${tab}:${c.key}`);
  let done = 0;
  const next = [...keys];
  const worker = async () => {
    while (next.length && state.picker === p) {
      const key = next.shift();
      await toggleWholePlaylist(key, true);
      done++;
      p.bulkLoading = `${done}/${keys.length}`;
      renderStats();
    }
  };
  p.bulkLoading = `0/${keys.length}`;
  renderStats();
  await Promise.all([worker(), worker(), worker()]); // three playlists at a time
  p.bulkLoading = null;
  if (state.picker === p) rerenderKeepingPlace();
});

$("#pk-folder-change").addEventListener("click", chooseFolder);
$("#pk-folder-open").addEventListener("click", () => openPath(pickerFolder()));

$("#pk-open-playlist").addEventListener("click", () => {
  const { lk } = state.picker;
  if (lk.playlist) openLookup(`https://www.youtube.com/playlist?list=${lk.playlist}`);
});

/** After a download finishes (or the format changes), re-check which videos are on disk. */
async function refreshPickerFlags() {
  const p = state.picker;
  if (!p) return;
  const keys = [...p.groups.keys()].filter((k) => p.groups.get(k).type !== "collections");
  for (const k of keys) {
    try { await loadGroup(k); } catch { /* keep the old flags */ }
  }
  if (state.picker !== p) return;
  for (const q of [...p.queued]) {
    const [k, v] = q.split("|");
    const item = p.groups.get(k)?.items.find((i) => i.key === v);
    if (item && item.downloaded) p.queued.delete(q);
  }
  rerenderKeepingPlace();
}

/** Re-render the grid but keep as many cards loaded as before, and the scroll position. */
function rerenderKeepingPlace() {
  const p = state.picker;
  if (!p) return;
  const y = window.scrollY;
  const shown = p.shown;
  renderTabs();
  renderView();
  while (p.shown < shown && p.shown < p.list.length) appendCards();
  renderFooter();
  window.scrollTo(0, y);
}

/* ================================================================ jobs */

function jobIcon(j) {
  if (j.avatar) return html`<img class="avatar" src="${j.avatar}" alt="" referrerpolicy="no-referrer">`;
  return html`<div class="job-icon ${j.platform}">${raw(j.platform === "youtube" ? ICON.yt : ICON.fb)}</div>`;
}

function itemStatus(i) {
  switch (i.status) {
    case "done": return html`<span class="st done">${raw(ICON.check)} ${i.size ? fmtBytes(i.size) : "Done"}</span>`;
    case "skipped": return html`<span class="st skipped">Already there</span>`;
    case "failed": return html`<span class="st failed">Failed</span>`;
    case "cancelled": return html`<span class="st">Cancelled</span>`;
    case "queued": return html`<span class="st">Queued</span>`;
    default: {
      const pct = Math.round((i.progress || 0) * 100);
      const extra = [i.phase || "Working", i.status === "downloading" ? `${pct}%` : i.phase?.startsWith("Converting") ? `${pct}%` : "", fmtSpeed(i.speed), fmtEta(i.eta)]
        .filter(Boolean).join(" · ");
      return html`<span class="st ${i.status}">${extra}</span><div class="bar"><i style="width:${pct}%"></i></div>`;
    }
  }
}

function itemRow(i, withReveal = true) {
  const num = i.index != null ? `#${i.index}` : "";
  const reveal = withReveal && i.file && state.mode === "local"
    ? html`<button class="icon-btn" title="Show in Finder" data-reveal="${i.out_dir}/${i.file}">${raw(ICON.reveal)}</button>`
    : html`<span></span>`;
  return html`<div class="item">
    <span class="n">${num}</span>
    <span class="t" title="${i.title}">${i.title}</span>
    <div class="s">${itemStatus(i)}</div>
    ${reveal}
    ${i.error ? html`<div class="e">${i.error}</div>` : ""}
  </div>`;
}

function detailsHtml(j) {
  const d = state.details.get(j.id);
  if (!d || !d.items) return html`<div class="items"><div class="muted small">Loading…</div></div>`;
  const filters = { all: () => true, active: (i) => ["downloading", "processing", "queued"].includes(i.status), failed: (i) => i.status === "failed" || i.status === "cancelled", done: (i) => i.status === "done", skipped: (i) => i.status === "skipped" };
  const list = d.items.filter(filters[d.filter] || filters.all);
  const counts = Object.fromEntries(Object.keys(filters).map((k) => [k, d.items.filter(filters[k]).length]));
  const shown = list.slice(0, d.limit);
  const names = { all: "All", active: "In progress", failed: "Failed", done: "Downloaded", skipped: "Already there" };
  return html`<div class="items">
    <div class="segmented items-filter" data-job="${j.id}">
      ${Object.keys(filters).map((k) => html`<button data-filter="${k}" class="${d.filter === k ? "on" : ""}">${names[k]} <span class="count">${counts[k]}</span></button>`)}
    </div>
    ${shown.length ? shown.map((i) => itemRow(i)) : html`<div class="muted small" style="padding:6px 4px">Nothing here.</div>`}
    ${list.length > shown.length ? html`<div class="more"><button class="link" data-more="${j.id}">Show ${Math.min(300, list.length - shown.length)} more of ${list.length - shown.length}</button></div>` : ""}
  </div>`;
}

function jobHtml(j) {
  const c = j.counts;
  const active = ACTIVE.has(j.status);
  const pct = Math.round((j.progress || 0) * 100);
  const barCls = j.status === "scanning" || (j.status === "queued") ? "indeterminate" : j.status;
  const doneCount = c.done + c.skipped;
  const stats = [];
  if (c.total) stats.push(html`<span><b>${doneCount.toLocaleString()}</b> / ${c.total.toLocaleString()} ready</span>`);
  if (c.done && c.skipped) stats.push(html`<span>${c.skipped.toLocaleString()} already there</span>`);
  if (c.failed) stats.push(html`<span class="err"><b>${c.failed}</b> failed</span>`);
  if (j.speed) stats.push(html`<span>${fmtSpeed(j.speed)}</span>`);
  if (device.jobs.has(j.id)) stats.push(deviceStat(j));
  if (c.total && active) stats.push(html`<span>${pct}%</span>`);
  stats.push(html`<span class="muted">${timeAgo(j.created)}</span>`);

  const canRetry = ["failed", "partial", "cancelled", "interrupted"].includes(j.status);
  const retryLabel = j.status === "failed" || j.status === "partial" ? "Retry" : "Resume";
  const expanded = state.expanded.has(j.id);
  const msgErr = j.status === "failed" || j.status === "partial";
  const activeItems = !expanded && j.items && j.items.length
    ? html`<div class="items">${j.items.slice(0, 4).map((i) => itemRow(i, false))}${j.items.length > 4 ? html`<div class="muted small" style="padding:0 4px">+ ${j.items.length - 4} more in progress</div>` : ""}</div>`
    : "";

  return html`
    <div class="job-top">
      ${jobIcon(j)}
      <div class="grow">
        <div class="job-title" title="${j.input}">${j.title || j.input}</div>
        <div class="job-msg ${msgErr ? "err" : ""}">${j.message}</div>
      </div>
      <span class="pill ${j.status}">${active && j.status !== "queued" ? raw('<span class="spinner sm"></span>') : ""}${STATUS_LABEL[j.status] || j.status}</span>
    </div>
    <div class="bar ${barCls}"><i style="width:${pct}%"></i></div>
    <div class="job-stats">
      ${stats}
      <div class="job-actions">
        ${j.folder && state.mode === "local" ? html`<button class="btn small ghost" data-act="open" data-path="${j.folder}">${raw(ICON.folder)} Open folder</button>` : ""}
        ${c.total ? html`<button class="btn small ghost" data-act="details">${raw(ICON.list)} ${expanded ? "Hide" : "Details"}</button>` : ""}
        ${canRetry ? html`<button class="btn small" data-act="retry">${raw(ICON.retry)} ${retryLabel}</button>` : ""}
        ${active ? html`<button class="btn small ghost danger" data-act="cancel">${raw(ICON.stop)} Cancel</button>` : ""}
        ${!active ? html`<button class="btn small ghost" data-act="remove" title="Remove from list">${raw(ICON.trash)}</button>` : ""}
      </div>
    </div>
    ${activeItems}
    ${expanded ? detailsHtml(j) : ""}`;
}

function renderJobs() {
  const wrap = $("#jobs");
  const ids = new Set(state.jobs.map((j) => j.id));
  $$(".job", wrap).forEach((el) => { if (!ids.has(el.dataset.id)) { el.remove(); state.cardCache.delete(el.dataset.id); } });
  let prev = null;
  for (const j of state.jobs) {
    let el = wrap.querySelector(`.job[data-id="${CSS.escape(j.id)}"]`);
    if (!el) {
      el = document.createElement("div");
      el.className = "card job";
      el.dataset.id = j.id;
    }
    const markup = flat(jobHtml(j));
    if (state.cardCache.get(j.id) !== markup) {
      el.innerHTML = markup;
      state.cardCache.set(j.id, markup);
    }
    const want = prev ? prev.nextSibling : wrap.firstChild;
    if (want !== el) wrap.insertBefore(el, want);
    prev = el;
  }
  $("#jobs-empty").hidden = state.jobs.length > 0;

  const active = state.jobs.filter((j) => ACTIVE.has(j.status) && j.counts.total);
  if (active.length) {
    const pct = Math.round((active.reduce((a, j) => a + j.progress, 0) / active.length) * 100);
    document.title = `(${pct}%) Vidstash`;
  } else {
    document.title = "Vidstash";
  }
}

$("#jobs").addEventListener("click", async (e) => {
  const reveal = e.target.closest("[data-reveal]");
  if (reveal) return openPath(reveal.dataset.reveal, true);
  const filterBtn = e.target.closest("[data-filter]");
  if (filterBtn) {
    const id = filterBtn.parentElement.dataset.job;
    const d = state.details.get(id);
    if (d) { d.filter = filterBtn.dataset.filter; d.limit = 300; renderJobs(); }
    return;
  }
  const more = e.target.closest("[data-more]");
  if (more) {
    const d = state.details.get(more.dataset.more);
    if (d) { d.limit += 300; renderJobs(); }
    return;
  }
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const id = btn.closest(".job").dataset.id;
  const act = btn.dataset.act;
  try {
    if (act === "open") await openPath(btn.dataset.path);
    else if (act === "device-resume") await resumeDevice();
    else if (act === "details") {
      if (state.expanded.has(id)) { state.expanded.delete(id); state.details.delete(id); }
      else { state.expanded.add(id); state.details.set(id, { items: null, filter: "all", limit: 300 }); loadDetails(id); }
      store.set("expanded", [...state.expanded]);
      renderJobs();
    } else if (act === "retry") { await api("POST", `/api/jobs/${id}/retry`); pollNow(); }
    else if (act === "cancel") { await api("POST", `/api/jobs/${id}/cancel`); toast("Cancelling…"); pollNow(); }
    else if (act === "remove") { await api("DELETE", `/api/jobs/${id}`); pollNow(); }
  } catch (err) { toast(err.message, "err"); }
});

$("#btn-clear-jobs").addEventListener("click", async () => {
  try { await api("POST", "/api/jobs/clear"); pollNow(); } catch (e) { toast(e.message, "err"); }
});

async function loadDetails(id) {
  try {
    const j = await api("GET", `/api/jobs/${id}`);
    const d = state.details.get(id) || { filter: "all", limit: 300 };
    d.items = j.items;
    state.details.set(id, d);
  } catch (e) {
    if (e.status === 404) { state.expanded.delete(id); state.details.delete(id); }
  }
}

function notifyFinished(j) {
  if (!store.get("notify", true) || !("Notification" in window) || Notification.permission !== "granted") return;
  const c = j.counts;
  const body = j.status === "done" ? `${c.done} downloaded, ${c.skipped} already there.` : j.message;
  try { new Notification(`${j.title} — ${STATUS_LABEL[j.status]}`, { body, silent: false }); } catch { /* ignore */ }
}

let pollTimer = null;
async function poll() {
  clearTimeout(pollTimer);
  let delay = 4000;
  try {
    const r = await api("GET", "/api/jobs");
    state.jobs = r.jobs;
    for (const j of state.jobs) {
      const before = state.prevStatus.get(j.id);
      if (before && ACTIVE.has(before) && !ACTIVE.has(j.status)) {
        if (["done", "partial", "failed"].includes(j.status)) notifyFinished(j);
        refreshPickerFlags();
      }
      state.prevStatus.set(j.id, j.status);
    }
    await Promise.all([...state.expanded].filter((id) => state.jobs.some((j) => j.id === id)).map(loadDetails));
    renderJobs();
    if (device.jobs.size) syncDevice();
    if (state.jobs.some((j) => ACTIVE.has(j.status))) delay = 1000;
  } catch {
    delay = 3000;
  }
  pollTimer = setTimeout(poll, delay);
}
const pollNow = () => setTimeout(poll, 150);

/* ================================================================ where it runs & save to this device */

// "local":   the browser is on the computer running Vidstash — videos save straight into the Save to folder.
// "remote":  Vidstash runs on another computer (e.g. at home, over Tailscale). Videos save there, and with
//            "Copy to this device" each finished one is also copied here: into a folder you pick
//            (Chrome/Edge over HTTPS) or into the browser's Downloads folder.
// "preview": the read-only online deployment (Vercel), which can't download at all.
const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);
const canPickFolder = "showDirectoryPicker" in window;

function applyMode(preview) {
  state.mode = preview ? "preview" : LOCAL_HOSTS.has(location.hostname) ? "local" : "remote";
  const show = { "local-only": state.mode === "local", "remote-only": state.mode === "remote",
    "preview-only": state.mode === "preview", "not-preview": state.mode !== "preview" };
  for (const [cls, on] of Object.entries(show)) $$(`.${cls}`).forEach((el) => { el.hidden = !on; });
}

// the picked folder is kept in IndexedDB so you don't pick it again every visit
const idb = {
  open() {
    return new Promise((ok, fail) => {
      const req = indexedDB.open("vidstash", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("kv");
      req.onsuccess = () => ok(req.result);
      req.onerror = () => fail(req.error);
    });
  },
  async run(mode, fn) {
    const db = await this.open();
    return new Promise((ok, fail) => {
      const req = fn(db.transaction("kv", mode).objectStore("kv"));
      req.onsuccess = () => ok(req.result);
      req.onerror = () => fail(req.error);
    });
  },
  get(k) { return this.run("readonly", (s) => s.get(k)).catch(() => undefined); },
  set(k, v) { return this.run("readwrite", (s) => s.put(v, k)).catch(() => undefined); },
};

// jobs: id -> {seen, queued: Set (this page), done: Set (persisted), saved, failed}
const device = { dir: null, paused: false, jobs: new Map(), queue: [], busy: false };

const deviceOn = () => state.mode === "remote" && store.get("device", false);

function saveDeviceJobs() {
  store.set("deviceJobs", Object.fromEntries([...device.jobs].map(([id, t]) =>
    [id, { done: [...t.done], saved: t.saved, failed: t.failed }])));
}

function renderDevice() {
  const on = store.get("device", false);
  $$(".device-toggle").forEach((el) => { el.checked = on; });
  $$(".device-pick").forEach((el) => { el.hidden = !on || !canPickFolder; el.textContent = device.dir ? "Change folder…" : "Choose folder…"; });
  const where = !on ? "Videos stay only on the computer running Vidstash."
    : !canPickFolder ? "Each finished video goes to this browser's Downloads folder. Keep this tab open. (To pick a folder, use Chrome or Edge over HTTPS.)"
    : device.dir ? `Each finished video is copied into “${device.dir.name}” on this device. Keep this tab open.`
    : "You'll pick a folder on this device when you press Download. Keep this tab open.";
  $$(".device-where").forEach((el) => { el.textContent = where; });
}

async function pickDeviceFolder() {
  try {
    device.dir = await window.showDirectoryPicker({ id: "vidstash", mode: "readwrite", startIn: "downloads" });
  } catch (e) {
    if (e.name === "AbortError") {
      toast("No folder chosen. Tip: make a new folder (e.g. “Vidstash”) inside Downloads and pick that — browsers won't let websites use Downloads, Desktop or your home folder itself.", "err");
      return false;
    }
    throw e;
  }
  idb.set("deviceDir", device.dir);
  device.paused = false;
  renderDevice();
  return true;
}

/** Get ready to copy this download to the device. Call straight from the click: browsers only show pickers then. */
async function prepareDevice() {
  if (!deviceOn() || !canPickFolder) return true;
  if (!device.dir) return pickDeviceFolder();
  if ((await device.dir.requestPermission({ mode: "readwrite" })) === "granted") { device.paused = false; return true; }
  toast("This device's folder wasn't allowed — choose it again.", "err");
  return pickDeviceFolder();
}

function trackDevice(jobs) {
  if (!deviceOn()) return;
  for (const j of jobs) device.jobs.set(j.id, { seen: 0, queued: new Set(), done: new Set(), saved: 0, failed: 0 });
  saveDeviceJobs();
}

async function syncDevice() {
  let changed = false;
  for (const id of device.jobs.keys()) {
    if (!state.jobs.some((j) => j.id === id)) { device.jobs.delete(id); changed = true; }
  }
  if (changed) saveDeviceJobs();
  for (const j of state.jobs) {
    const t = device.jobs.get(j.id);
    if (!t || j.counts.done <= t.seen) continue;
    t.seen = j.counts.done;
    try {
      const full = await api("GET", `/api/jobs/${j.id}`);
      for (const i of full.items) {
        if (i.status !== "done" || !i.file || t.done.has(i.key) || t.queued.has(i.key)) continue;
        t.queued.add(i.key);
        device.queue.push({ job: full, item: i, t });
      }
    } catch { t.seen = 0; }
  }
  pumpDevice();
}

async function pumpDevice() {
  if (device.busy || device.paused) return;
  device.busy = true;
  while (device.queue.length) {
    const next = device.queue[0];
    if (canPickFolder && (!device.dir || (await device.dir.queryPermission({ mode: "readwrite" })) !== "granted")) {
      device.paused = true; // after a reload the browser wants a click before we can write again
      renderJobs();
      break;
    }
    device.queue.shift();
    const { job, item, t } = next;
    try {
      await saveToDevice(job, item);
      t.done.add(item.key);
      t.saved++;
    } catch (e) {
      t.failed++;
      toast(`Couldn't copy “${item.title}” to this device: ${e.message}`, "err");
    }
    t.queued.delete(item.key);
    saveDeviceJobs();
    renderJobs();
  }
  device.busy = false;
}

async function resumeDevice() {
  if (await prepareDevice()) { device.paused = false; renderJobs(); pumpDevice(); }
}

const safeName = (s) => s.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").replace(/[. ]+$/, "") || "_";

async function saveToDevice(job, item) {
  const url = `/api/jobs/${job.id}/file?key=${encodeURIComponent(item.key)}`;
  if (!canPickFolder) {
    const a = document.createElement("a");
    a.href = url;
    a.download = item.file;
    document.body.append(a);
    a.click();
    a.remove();
    await new Promise((r) => setTimeout(r, 1000)); // browsers drop downloads fired back to back
    return;
  }
  // keep the same <channel>/<tab>/ layout as on the host
  let dir = device.dir;
  const sub = item.out_dir.startsWith(job.output_dir) ? item.out_dir.slice(job.output_dir.length) : "";
  for (const part of sub.split(/[\\/]/).filter(Boolean)) dir = await dir.getDirectoryHandle(safeName(part), { create: true });
  const res = await fetch(url);
  if (!res.ok) throw new Error(`download failed (${res.status})`);
  const fh = await dir.getFileHandle(safeName(item.file), { create: true });
  await res.body.pipeTo(await fh.createWritable());
}

function deviceStat(j) {
  const t = device.jobs.get(j.id);
  if (!t) return "";
  if (device.paused && (t.queued.size || device.queue.some((q) => q.t === t))) {
    return html`<span class="err">Copying to this device is paused <button class="link" data-act="device-resume">Continue</button></span>`;
  }
  return html`<span><b>${t.saved.toLocaleString()}</b> copied to this device${t.failed ? html` · <span class="err">${t.failed} failed</span>` : ""}</span>`;
}

$$(".device-toggle").forEach((el) => el.addEventListener("change", (e) => {
  store.set("device", e.target.checked);
  renderDevice();
  toast(e.target.checked ? "Saved — new downloads will also be copied to this device." : "Saved — videos will stay on the host only.", "ok");
}));
$$(".device-pick").forEach((el) => el.addEventListener("click", () => pickDeviceFolder().catch((e) => toast(e.message, "err"))));

async function restoreDevice() {
  if (state.mode !== "remote") return;
  if (canPickFolder) device.dir = (await idb.get("deviceDir")) || null;
  for (const [id, t] of Object.entries(store.get("deviceJobs", {}))) {
    device.jobs.set(id, { seen: 0, queued: new Set(), done: new Set(t.done || []), saved: t.saved || 0, failed: t.failed || 0 });
  }
  renderDevice();
}

/* ================================================================ library */

async function loadLibrary() {
  try {
    const r = await api("GET", "/api/library");
    $("#lib-root").textContent = r.root;
    $("#lib-empty").hidden = r.folders.length > 0;
    $("#library").innerHTML = flat(r.folders.map((f) => html`
      <div class="card folder" data-path="${f.path}">
        <div class="folder-top">
          <div class="folder-icon ${f.platform || ""}">${raw(f.platform === "youtube" ? ICON.yt : f.platform === "facebook" ? ICON.fb : ICON.folder)}</div>
          <div class="grow">
            <div class="folder-name" title="${f.name}">${f.name}</div>
            <div class="muted small">${plural(f.count, "file")} · ${fmtBytes(f.size)} · ${timeAgo(f.updated)}${f.subfolders.length ? ` · ${f.subfolders.join(", ")}` : ""}</div>
          </div>
        </div>
        <div class="inline">
          ${state.mode === "local" ? html`<button class="btn small" data-lib="open">${raw(ICON.folder)} Open</button>` : ""}
          <button class="btn small ghost" data-lib="files">${raw(ICON.list)} Files</button>
        </div>
        <div class="files" hidden></div>
      </div>`));
  } catch (e) { toast(e.message, "err"); }
}

$("#library").addEventListener("click", async (e) => {
  const reveal = e.target.closest("[data-reveal]");
  if (reveal) return openPath(reveal.dataset.reveal, true);
  const btn = e.target.closest("[data-lib]");
  if (!btn) return;
  const card = btn.closest(".folder");
  if (btn.dataset.lib === "open") return openPath(card.dataset.path);
  const box = $(".files", card);
  if (!box.hidden) { box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = '<div class="muted small">Loading…</div>';
  try {
    const r = await api("GET", `/api/library/files?path=${encodeURIComponent(card.dataset.path)}`);
    box.innerHTML = r.files.length
      ? flat(r.files.map((f) => html`<div class="file"><span title="${f.name}">${f.name}</span><span class="muted small">${fmtBytes(f.size)}</span>${state.mode === "local" ? html`<button class="icon-btn" title="Show in Finder" data-reveal="${f.path}">${raw(ICON.reveal)}</button>` : ""}</div>`))
      : '<div class="muted small">No video files yet.</div>';
  } catch (err) { box.innerHTML = ""; toast(err.message, "err"); }
});
$("#lib-refresh").addEventListener("click", loadLibrary);
$("#lib-open-root").addEventListener("click", () => openPath($("#lib-root").textContent));

/* ================================================================ settings / system */

function hcell(level, title, detail) {
  const ic = level === "ok" ? ICON.check : level === "warn" ? ICON.warn : ICON.x;
  return html`<div class="hcell ${level}"><span class="ic">${raw(ic)}</span><div><b>${title}</b><span>${detail}</span></div></div>`;
}

let systemTimer = null;
async function loadSystem() {
  clearTimeout(systemTimer);
  try {
    const s = await api("GET", "/api/system");
    state.system = s;
    const y = s.ytdlp;
    $("#health").innerHTML = flat([
      hcell(y.outdated ? "warn" : "ok", `yt-dlp ${y.version}`, y.outdated ? `Update available: ${y.latest}` : y.latest ? "Up to date" : "Couldn't check for updates (offline?)"),
      hcell(s.ffmpeg ? "ok" : "bad", s.ffmpeg ? `ffmpeg ${s.ffmpeg}` : "ffmpeg missing", s.ffmpeg ? "Merges & converts video" : "Required — run: brew install ffmpeg"),
      hcell(s.encoder ? "ok" : "warn", "H.264 encoder", s.encoder === "h264_videotoolbox" ? "Apple hardware encoder (fast)" : s.encoder ? "Software x264 (slower for 4K)" : "Needs ffmpeg"),
      hcell(s.js_runtimes.length ? "ok" : "warn", "JavaScript runtime", s.js_runtimes.length ? `${s.js_runtimes.join(", ")} — unlocks all YouTube formats` : "Install deno or node for all YouTube formats"),
      hcell(s.chromium ? "ok" : "warn", "Browser for Facebook", s.chromium ? "Chromium installed" : "Run ./setup.sh to install it"),
      hcell("ok", `Python ${s.python}`, s.os),
    ]);
    $("#settings-dot").hidden = !(y.outdated || !s.ffmpeg);
    $("#about").textContent = `Vidstash ${s.app_version} · yt-dlp ${y.version} · Python ${s.python} · ${s.os}`;

    const fb = s.facebook;
    $("#fb-status").textContent = fb.logged_in ? "Connected" : "Not connected";
    if (fb.message) $("#fb-message").textContent = fb.message;
    $("#btn-fb-login").hidden = fb.logged_in && !fb.running;
    $("#btn-fb-login").disabled = fb.running;
    $("#btn-fb-login").textContent = fb.running ? "Waiting for login…" : "Connect Facebook";
    $("#btn-fb-logout").hidden = !fb.logged_in;

    const u = s.update;
    $("#btn-update-ytdlp").disabled = $("#btn-update-all").disabled = u.running;
    $("#btn-update-ytdlp").textContent = u.running ? "Updating…" : y.outdated ? `Update to ${y.latest}` : "Update yt-dlp";
    $("#update-log").hidden = !u.log;
    if (u.log) { $("#update-log").textContent = u.log; $("#update-log").scrollTop = 1e9; }
    $("#restart-row").hidden = !u.needs_restart;
    if (u.ok === false && !u.running) $("#restart-row").hidden = true;

    if (u.running || fb.running) systemTimer = setTimeout(loadSystem, 1000);
  } catch (e) { toast(e.message, "err"); }
}

async function runUpdate(everything) {
  try {
    await api("POST", "/api/update", { everything });
    toast(everything ? "Updating all packages…" : "Updating yt-dlp…");
    setTimeout(loadSystem, 300);
  } catch (e) { toast(e.message, "err"); }
}
$("#btn-update-ytdlp").addEventListener("click", () => runUpdate(false));
$("#btn-update-all").addEventListener("click", () => runUpdate(true));

$("#btn-restart").addEventListener("click", async () => {
  try {
    await api("POST", "/api/restart");
    toast("Restarting…");
    const started = Date.now();
    const wait = async () => {
      try { await api("GET", "/api/system"); location.reload(); }
      catch { if (Date.now() - started < 60000) setTimeout(wait, 800); else toast("The app didn't come back — start it again with ./app.sh", "err"); }
    };
    setTimeout(wait, 1500);
  } catch (e) { toast(e.message, "err"); }
});

$("#btn-fb-login").addEventListener("click", async () => {
  try { await api("POST", "/api/facebook/login"); setTimeout(loadSystem, 300); } catch (e) { toast(e.message, "err"); }
});
$("#btn-fb-logout").addEventListener("click", async () => {
  try { await api("POST", "/api/facebook/logout"); loadSystem(); } catch (e) { toast(e.message, "err"); }
});

$("#set-open-browser").addEventListener("change", async (e) => {
  try { await api("PUT", "/api/settings", { open_browser: e.target.checked }); } catch (err) { toast(err.message, "err"); }
});
$("#set-notify").addEventListener("change", (e) => {
  store.set("notify", e.target.checked);
  if (e.target.checked) maybeAskNotify();
});

/* ================================================================ boot */

(async function boot() {
  bindOptions();
  try {
    const s = await api("GET", "/api/settings");
    state.settings = s;
    state.options = s.options;
    $("#opt-output").value = s.output_dir;
    $("#set-open-browser").checked = s.open_browser !== false;
    applyMode(s.preview);
  } catch (e) {
    applyMode(false);
    toast(`Couldn't load settings: ${e.message}`, "err");
    state.options = { quality: "best", format: "mp4", tabs: ["videos"], naming: "number_title", limit: null, workers: 3, embed_thumbnail: true, embed_metadata: true };
  }
  $("#set-notify").checked = store.get("notify", true);
  await restoreDevice();
  applyOptionsToControls();
  autoGrow();
  showView(store.get("view", "download"));
  poll();
  // Check health quietly so the Settings dot can flag an outdated yt-dlp.
  api("GET", "/api/system").then((s) => { $("#settings-dot").hidden = !(s.ytdlp.outdated || !s.ffmpeg); }).catch(() => {});
  inputEl.focus();
})();
