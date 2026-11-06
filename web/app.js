/* ComfySweep — single-page admin UI. Vanilla JS, no build step, no CDN. */
"use strict";

/* ======================================================================
   Utilities
   ====================================================================== */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ESC[c]);
const clone = (o) => JSON.parse(JSON.stringify(o));
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const APP = { user: null, tz: null, version: "", status: null, cfg: null, saved: null,
              meta: null, timers: [], zones: null };

const ICON = {
  folder: '<svg viewBox="0 0 24 24"><path d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8z"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="M11 20V7.83l-5.59 5.59L4 12l8-8 8 8-1.41 1.41L13 7.83V20z"/></svg>',
  broom: '<svg viewBox="0 0 24 24"><path d="M19.36 2.72l1.42 1.42-5.72 5.71c1.07 1.54 1.22 3.39.32 4.59L9.06 8.12c1.2-.9 3.05-.75 4.59.32zM5.93 17.57c-2.01-2.01-3.24-4.41-3.58-6.65l4.88-2.09 7.44 7.44-2.09 4.88c-2.24-.34-4.64-1.57-6.65-3.58z"/></svg>',
  eye: '<svg viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-8a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M17.65 6.35A7.96 7.96 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z"/></svg>',
  download: '<svg viewBox="0 0 24 24"><path d="M5 20h14v-2H5zM19 9h-4V3H9v6H5l7 7z"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M1 21h22L12 2zm12-3h-2v-2h2zm0-4h-2v-4h2z"/></svg>',
  err: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-2h2zm0-4h-2V7h2z"/></svg>',
  info: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-6h2zm0-8h-2V7h2z"/></svg>',
  empty: '<svg viewBox="0 0 24 24"><path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 16H5v-3h3.56A3.97 3.97 0 0 0 12 18a3.97 3.97 0 0 0 3.44-2H19zm0-5h-5a2 2 0 1 1-4 0H5V5h14z"/></svg>',
  key: '<svg viewBox="0 0 24 24"><path d="M12.65 10A6 6 0 1 0 12.65 14H17v4h4v-4h2v-4zM7 14a2 2 0 1 1 0-4 2 2 0 0 1 0 4z"/></svg>',
};

function fmtBytes(n) {
  n = Number(n || 0);
  const u = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  while (Math.abs(n) >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n.toFixed(0) : n.toFixed(n >= 100 ? 0 : 1)) + " " + u[i];
}
const fmtNum = (n) => Number(n || 0).toLocaleString();
function fmtTs(ts, withYear) {
  if (!ts) return "—";
  const o = { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false };
  if (withYear) o.year = "numeric";
  try { return new Intl.DateTimeFormat(undefined, Object.assign({ timeZone: APP.tz || undefined }, o)).format(new Date(ts * 1000)); }
  catch (e) { return new Date(ts * 1000).toLocaleString(); }
}
function fmtAgo(ts) {
  if (!ts) return "";
  const d = ts - Date.now() / 1000, a = Math.abs(d);
  let s;
  if (a < 60) s = "moments";
  else if (a < 3600) s = Math.round(a / 60) + " min";
  else if (a < 86400) s = (a / 3600).toFixed(a < 36000 ? 1 : 0) + " h";
  else s = Math.round(a / 86400) + " d";
  return d > 0 ? "in " + s : s + " ago";
}
function fmtDur(ms) {
  ms = Number(ms || 0);
  if (ms < 1000) return Math.round(ms) + " ms";
  if (ms < 60000) return (ms / 1000).toFixed(1) + " s";
  return Math.floor(ms / 60000) + "m " + Math.round((ms % 60000) / 1000) + "s";
}
function getPath(o, p) { return p.split(".").reduce((a, k) => (a == null ? a : a[k]), o); }
function setPath(o, p, v) {
  const ks = p.split("."); let cur = o;
  for (let i = 0; i < ks.length - 1; i++) cur = cur[ks[i]];
  cur[ks[ks.length - 1]] = v;
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

/* ---------- API ---------- */
class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
async function api(method, path, body) {
  const opt = { method, headers: { "X-Requested-With": "ComfySweep" }, credentials: "same-origin" };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(path, opt); }
  catch (e) { throw new ApiError(0, "Cannot reach ComfySweep — is the container running?"); }
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  if (!r.ok) {
    if (r.status === 401 && !/^\/api\/(auth\/login|auth\/me|setup)/.test(path)) {
      showLogin("Your session has ended — please sign in again.");
    }
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    throw new ApiError(r.status, msg || r.statusText || "Request failed");
  }
  return data;
}

/* ---------- toasts / modals ---------- */
function toast(msg, kind) {
  const el = document.createElement("div");
  el.className = "toast " + (kind || "");
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 7000 : 4000);
}
function modal(html, opts) {
  opts = opts || {};
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = '<div class="modal ' + (opts.wide ? "wide" : "") + '" role="dialog" aria-modal="true">' + html + "</div>";
  $("#modal-root").appendChild(back);
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey); opts.onClose && opts.onClose(); };
  const onKey = (e) => { if (e.key === "Escape" && !opts.sticky) close(); };
  document.addEventListener("keydown", onKey);
  back.addEventListener("mousedown", (e) => { if (e.target === back && !opts.sticky) close(); });
  $$("[data-close]", back).forEach((b) => b.addEventListener("click", close));
  return { el: back.firstElementChild, close };
}
function confirmBox(title, text, okLabel, danger) {
  return new Promise((res) => {
    const m = modal('<h2>' + esc(title) + '</h2><p class="muted">' + text + '</p><div class="modal-foot">' +
      '<button class="btn ghost" data-close>Cancel</button><button class="btn ' + (danger ? "danger" : "primary") +
      '" id="cb-ok">' + esc(okLabel || "OK") + "</button></div>", { onClose: () => res(false) });
    $("#cb-ok", m.el).addEventListener("click", () => { res(true); m.close(); });
  });
}
function alertsHtml(list) {
  if (!list || !list.length) return "";
  return '<div class="alerts">' + list.map((w) => {
    const k = w.level === "error" ? "error" : w.level === "warn" ? "warn" : "info";
    const ic = k === "error" ? ICON.err : k === "warn" ? ICON.warn : ICON.info;
    return '<div class="alert ' + k + '">' + ic + '<div class="txt">' + esc(w.text) + "</div></div>";
  }).join("") + "</div>";
}
function outcomePill(r) {
  const o = r.outcome;
  if (o === "ok" && r.dry_run) return '<span class="pill info">Preview</span>';
  const map = { ok: ["ok", "Completed"], skipped: ["warn", "Skipped"], missed: ["warn", "Missed"],
    wrong_mount: ["err", "Wrong folder"], error: ["err", "Error"], not_configured: ["", "Not configured"],
    skipped_busy: ["warn", "Busy"] };
  const m = map[o] || ["", o];
  return '<span class="pill ' + m[0] + '">' + esc(m[1]) + "</span>";
}
const TRIGGERS = { manual: "Manual", schedule: "Scheduled", catchup: "Catch-up" };

/* ======================================================================
   Charts (inline SVG)
   ====================================================================== */
function barChart(data, opts) {
  // data: [{label, parts:[{v, cls}], title}]
  opts = opts || {};
  const W = opts.w || 600, H = opts.h || 190, padL = 52, padB = 22, padT = 8;
  if (!data.length) return '<div class="empty">' + ICON.empty + (opts.emptyText || "No data yet") + "</div>";
  const max = Math.max(1, ...data.map((d) => d.parts.reduce((a, p) => a + p.v, 0)));
  const n = data.length, slot = (W - padL) / n, bw = Math.max(2, Math.min(28, slot * 0.7));
  let s = '<svg class="chart" viewBox="0 0 ' + W + " " + H + '" role="img">';
  for (let i = 0; i <= 3; i++) {
    const y = padT + (H - padB - padT) * (i / 3);
    s += '<line class="grid-line" x1="' + padL + '" x2="' + W + '" y1="' + y + '" y2="' + y + '"/>';
    s += '<text class="axis" x="' + (padL - 6) + '" y="' + (y + 3) + '" text-anchor="end">' +
      esc(opts.fmt ? opts.fmt(max * (1 - i / 3)) : Math.round(max * (1 - i / 3))) + "</text>";
  }
  data.forEach((d, i) => {
    const x = padL + slot * i + (slot - bw) / 2;
    let y = H - padB;
    d.parts.forEach((p) => {
      const h = (p.v / max) * (H - padB - padT);
      if (h <= 0) return;
      y -= h;
      s += '<rect class="' + p.cls + '" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) +
        '" height="' + Math.max(1, h).toFixed(1) + '" rx="2"><title>' + esc(d.title || d.label) + "</title></rect>";
    });
    const every = Math.ceil(n / 8);
    if ((i % every === 0 && n - 1 - i >= every) || i === n - 1) {
      const last = i === n - 1;
      s += '<text class="axis" x="' + (last ? x + bw : x + bw / 2).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + (last ? "end" : "middle") + '">' + esc(d.label) + "</text>";
    }
  });
  return s + "</svg>";
}

/* ======================================================================
   Boot, gate (setup / login) and shell
   ====================================================================== */
async function boot() {
  $("#theme-btn").addEventListener("click", toggleTheme);
  $("#logout-btn").addEventListener("click", logout);
  window.addEventListener("hashchange", route);
  try {
    const st = await api("GET", "/api/setup");
    if (st.needed) return showSetup(0);
  } catch (e) {
    $("#gate").hidden = false;
    $("#gate-body").innerHTML = alertsHtml([{ level: "error", text: e.message }]);
    return;
  }
  try {
    APP.user = await api("GET", "/api/auth/me");
    enterShell();
  } catch (e) {
    if (e.status === 401) showLogin();
  }
}

function toggleTheme() {
  const cur = document.documentElement.dataset.theme ||
    (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("cs-theme", next); } catch (e) {}
}

async function logout() {
  try { await api("POST", "/api/auth/logout"); } catch (e) {}
  APP.user = null;
  showLogin("You have been signed out.");
}

function clearTimers() { APP.timers.forEach((t) => clearInterval(t)); APP.timers = []; }

function showLogin(msg) {
  clearTimers();
  $("#shell").hidden = true;
  $("#gate").hidden = false;
  $$(".modal-back").forEach((m) => m.remove());
  $("#gate-body").innerHTML =
    (msg ? alertsHtml([{ level: "info", text: msg }]) : "") +
    '<h2>Sign in</h2><form id="login-form">' +
    '<div class="field"><label for="lu">Username</label><input type="text" id="lu" autocomplete="username" required></div>' +
    '<div class="field"><label for="lp">Password</label><input type="password" id="lp" autocomplete="current-password" required></div>' +
    '<div id="login-err"></div><button class="btn primary" style="width:100%" type="submit">Sign in</button></form>' +
    '<p class="muted" style="font-size:12.5px;margin-top:16px">Forgot the password? Run <code>docker exec -it comfysweep python -m app.cli reset-password &lt;user&gt;</code> on the server.</p>';
  $("#lu").focus();
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("POST", "/api/auth/login", { username: $("#lu").value, password: $("#lp").value });
      APP.user = await api("GET", "/api/auth/me");
      enterShell();
    } catch (err) {
      $("#login-err").innerHTML = alertsHtml([{ level: "error", text: err.message }]);
    }
  });
}

/* ---------- first-run setup wizard ---------- */
const WIZ_STEPS = ["Account", "ComfyUI", "Folders", "Schedule"];
async function showSetup(step) {
  $("#shell").hidden = true;
  $("#gate").hidden = false;
  const body = $("#gate-body");
  const bar = '<div class="steps">' + WIZ_STEPS.map((_, i) => '<span class="' + (i <= step ? "on" : "") + '"></span>').join("") + "</div>";
  if (step === 0) {
    body.innerHTML = bar + "<h2>Welcome! Let's set up ComfySweep</h2>" +
      '<p class="muted">First, create the administrator account. You will use it to sign in to this dashboard.</p>' +
      '<form id="setup-form"><div class="field"><label>Admin username</label><input type="text" id="su" value="admin" autocomplete="username" required></div>' +
      '<div class="field"><label>Password</label><input type="password" id="sp" autocomplete="new-password" required minlength="8"><span class="help">At least 8 characters.</span></div>' +
      '<div class="field"><label>Confirm password</label><input type="password" id="sp2" autocomplete="new-password" required></div>' +
      '<div id="setup-err"></div><button class="btn primary" style="width:100%" type="submit">Create account &amp; continue</button></form>';
    $("#setup-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if ($("#sp").value !== $("#sp2").value) {
        $("#setup-err").innerHTML = alertsHtml([{ level: "error", text: "The passwords do not match." }]);
        return;
      }
      try {
        await api("POST", "/api/setup", { username: $("#su").value, password: $("#sp").value });
        APP.user = await api("GET", "/api/auth/me");
        await loadSettings();
        showSetup(1);
      } catch (err) { $("#setup-err").innerHTML = alertsHtml([{ level: "error", text: err.message }]); }
    });
    return;
  }
  if (!APP.cfg) await loadSettings();
  const titles = {
    1: ["Connect to ComfyUI", "ComfySweep reads ComfyUI's queue (so it never cleans inputs while a job runs) and verifies it is cleaning the right folder. It only ever uses read-only endpoints."],
    2: ["Choose folders to clean", "Pick ComfyUI's folders inside the mounted host directory. Only enabled folders are cleaned."],
    3: ["Schedule & safety", "Run the cleanup automatically. Dry-run-only mode stays on until you've checked a preview — recommended."],
  };
  body.innerHTML = bar + "<h2>" + titles[step][0] + '</h2><p class="muted">' + titles[step][1] + '</p><div id="wiz"></div>' +
    '<div id="wiz-err"></div><div class="modal-foot"><button class="btn ghost" id="wiz-skip">Skip setup</button><span class="spacer"></span>' +
    (step > 1 ? '<button class="btn" id="wiz-back">Back</button>' : "") +
    '<button class="btn primary" id="wiz-next">' + (step === 3 ? "Finish" : "Next") + "</button></div>";
  const wiz = $("#wiz");
  if (step === 1) renderComfyTab(wiz, true);
  if (step === 2) renderFoldersTab(wiz, true);
  if (step === 3) { renderScheduleTab(wiz, true); renderDryRunToggle(wiz); }
  $("#wiz-skip").addEventListener("click", () => enterShell());
  if ($("#wiz-back")) $("#wiz-back").addEventListener("click", () => showSetup(step - 1));
  $("#wiz-next").addEventListener("click", async () => {
    try {
      const r = await api("PUT", "/api/settings", APP.cfg);
      APP.saved = clone(r.settings); APP.cfg = clone(r.settings); APP.meta = r;
      if (step < 3) showSetup(step + 1);
      else { toast("All set — ComfySweep is ready.", "ok"); enterShell(); }
    } catch (err) { $("#wiz-err").innerHTML = alertsHtml([{ level: "error", text: err.message }]); }
  });
}

function enterShell() {
  $("#gate").hidden = true;
  $("#shell").hidden = false;
  $("#who").textContent = APP.user ? APP.user.username : "";
  if (!location.hash || location.hash === "#/") location.hash = "#/dashboard";
  else route();
  refreshSide();
  if (!APP.sideTimer) APP.sideTimer = setInterval(refreshSide, 30000);
}

async function refreshSide() {
  if ($("#shell").hidden) return;
  try {
    const s = await api("GET", "/api/status?probe=false");
    APP.tz = s.timezone; APP.version = s.version;
    $("#version").textContent = "ComfySweep v" + s.version;
    const sc = s.scheduler;
    $("#side-status").innerHTML =
      '<div><span class="dot ' + (sc.alive ? "ok" : "err") + '"></span>&nbsp; Scheduler ' + (sc.alive ? "running" : "stopped") + "</div>" +
      "<div>" + (sc.enabled && sc.next_fire ? "Next run " + esc(fmtAgo(sc.next_fire)) : "Schedule off") + "</div>" +
      (s.safety.dry_run_only ? '<div><span class="pill info">Dry-run mode</span></div>' : "");
  } catch (e) {}
}

/* ---------- router ---------- */
async function route() {
  if ($("#shell").hidden) return;
  clearTimers();
  const parts = (location.hash.replace(/^#\/?/, "") || "dashboard").split("/");
  const page = parts[0];
  $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === page));
  const view = $("#view");
  view.innerHTML = '<div class="empty"><span class="spin"></span></div>';
  try {
    if (page === "history") await pageHistory(view);
    else if (page === "logs") await pageLogs(view);
    else if (page === "settings") await pageSettings(view, parts[1] || "comfyui");
    else await pageDashboard(view);
  } catch (e) {
    if (e.status !== 401) view.innerHTML = alertsHtml([{ level: "error", text: e.message }]);
  }
  window.scrollTo(0, 0);
}

/* ======================================================================
   Dashboard
   ====================================================================== */
async function pageDashboard(view) {
  const s = await api("GET", "/api/status");
  APP.status = s; APP.tz = s.timezone;
  const t = s.totals, sc = s.scheduler, lr = s.last_run, c = s.comfy;
  const enabled = Object.keys(s.folders).filter((k) => s.folders[k].enabled);
  const mv = s.mount_verified;
  view.innerHTML =
    '<div class="page-head"><div><h1>Dashboard</h1><div class="sub">Server time ' + esc(s.now_local) + " · " + esc(s.timezone) + "</div></div>" +
    '<div class="actions"><button class="btn ghost" id="d-refresh">' + ICON.refresh + 'Refresh</button>' +
    '<button class="btn" id="d-preview">' + ICON.eye + 'Preview</button>' +
    '<button class="btn primary" id="d-clean">' + ICON.broom + "Clean now</button></div></div>" +
    alertsHtml(s.warnings) +
    '<div class="grid g4">' +
    '<div class="card stat hero"><div class="label">Space freed · 30 days</div><div class="value">' + fmtBytes(t.freed_30d) + '</div><div class="hint">' + fmtNum(t.removed_30d) + " files removed</div></div>" +
    '<div class="card stat"><div class="label">Freed all time</div><div class="value">' + fmtBytes(t.freed_all) + '</div><div class="hint">' + fmtNum(t.removed_all) + " files · " + fmtNum(t.real_runs) + " cleanups</div></div>" +
    '<div class="card stat"><div class="label">Next scheduled run</div><div class="value">' + (sc.enabled && sc.next_fire ? esc(fmtAgo(sc.next_fire)) : "Off") +
    '</div><div class="hint">' + (sc.enabled && sc.next_fire ? esc(sc.next_fire_local) : '<a href="#/settings/schedule">Set up a schedule →</a>') + "</div></div>" +
    '<div class="card stat"><div class="label">Last run</div><div class="value">' + (lr ? esc(fmtAgo(lr.started)) : "Never") +
    '</div><div class="hint">' + (lr ? outcomePill(lr) + " " + (lr.dry_run ? fmtNum(lr.candidates) + " files found" : fmtBytes(lr.bytes_freed) + " freed") : "Run a preview to get started") + "</div></div>" +
    "</div>" +
    '<div class="grid g3 mt">' +
    '<div class="card"><div class="card-head"><h2>ComfyUI</h2><span class="right pill ' + (c.reachable ? "ok" : "err") + '">' + (c.reachable ? "Connected" : "Unreachable") + "</span></div>" +
    '<dl class="kv"><dt>URL</dt><dd class="mono">' + esc(c.url) + "</dd>" +
    (c.reachable ? "<dt>Queue</dt><dd>" + c.queue_running + " running · " + c.queue_pending + " pending</dd><dt>Latency</dt><dd>" + c.ms + " ms</dd>"
      : '<dt>Error</dt><dd style="font-weight:400;white-space:normal">' + esc(c.error) + "</dd>") + "</dl></div>" +
    '<div class="card"><div class="card-head"><h2>Folder check</h2><span class="right pill ' + (mv === true ? "ok" : mv === false ? "err" : "") + '">' +
    (mv === true ? "Verified" : mv === false ? "Wrong folder" : "Unknown") + "</span></div>" +
    '<p class="muted" style="margin:0;font-size:13px">' + (mv === true ? "ComfySweep can see ComfyUI's most recent output (<code>" + esc(s.mount_detail) + "</code>), so it is cleaning the right folder."
      : mv === false ? "ComfyUI's latest output is not in the configured output folder. Real cleanups are refused until this is fixed."
        : esc(s.mount_detail || "Not checked") + ". This never blocks a cleanup.") + "</p></div>" +
    '<div class="card"><div class="card-head"><h2>Scheduler</h2><span class="right pill ' + (sc.running ? "brand" : sc.alive ? "ok" : "err") + '">' +
    (sc.running ? "Cleaning…" : sc.alive ? "Idle" : "Stopped") + "</span></div>" +
    '<dl class="kv"><dt>Schedule</dt><dd>' + (sc.enabled ? esc(scheduleText(sc)) : "Off") + "</dd><dt>Last fired</dt><dd>" + esc(sc.last_fire_local || "—") +
    '</dd><dt>Mode</dt><dd>' + (s.safety.dry_run_only ? '<span class="pill info">Dry run only</span>' : '<span class="pill ok">Deleting</span>') + "</dd></dl></div>" +
    "</div>" +
    '<div class="card-head mt2"><h2>Folders</h2><span class="right"><a href="#/settings/folders">Manage folders →</a></span></div>' +
    '<div id="d-folders" class="grid ' + (enabled.length > 1 ? "g" + Math.min(3, enabled.length) : "") + '">' +
    (enabled.length ? enabled.map((k) => '<div class="card folder-card" id="fc-' + k + '"><div class="card-head"><h2>' + esc(s.folders[k].label) +
      '</h2><span class="right spin"></span></div><div class="path">' + esc(s.folders[k].path) + "</div></div>").join("")
      : '<div class="card empty">' + ICON.folder.replace("<svg", '<svg style="fill:var(--bar-keep)"') + 'No folders enabled. <a href="#/settings/folders">Choose folders to clean</a>.</div>') +
    "</div>" +
    '<div class="card mt2"><div class="card-head"><h2>Recent activity</h2><span class="right"><a href="#/history">Full history →</a></span></div><div id="d-recent"></div></div>';

  $("#d-refresh").addEventListener("click", route);
  $("#d-preview").addEventListener("click", () => cleanFlow(false));
  $("#d-clean").addEventListener("click", () => cleanFlow(true));
  loadRecent($("#d-recent"), 6);
  if (enabled.length) loadUsage(s);
  APP.timers.push(setInterval(async () => {
    try {
      const x = await api("GET", "/api/status?probe=false");
      if (x.scheduler.running !== APP.status.scheduler.running || (x.last_run && (!APP.status.last_run || x.last_run.id !== APP.status.last_run.id))) route();
    } catch (e) {}
  }, 15000));
}

function scheduleText(sc) {
  if (sc.mode === "interval") return "Every " + sc.interval_hours + " h from " + sc.time;
  if (sc.mode === "weekly") return (sc.weekdays || []).map((d) => WEEKDAYS[d]).join(", ") + " at " + sc.time;
  return "Daily at " + sc.time;
}

async function loadUsage(s) {
  try {
    const u = await api("GET", "/api/usage?days=60");
    Object.keys(u.folders).forEach((k) => {
      const f = u.folders[k], card = $("#fc-" + k);
      if (!card) return;
      const st = s.folders[k];
      const pct = f.total_bytes ? Math.round((f.deletable_bytes / f.total_bytes) * 100) : 0;
      const days = f.days.slice(0, 30).reverse();
      const pill = !f.present ? '<span class="right pill err">Not found</span>' : !st.writable ? '<span class="right pill err">Read-only</span>'
        : '<span class="right pill ok">Healthy</span>';
      card.innerHTML = '<div class="card-head"><h2>' + esc(f.label) + "</h2>" + pill + '</div><div class="path">' + esc(f.dir) + "</div>" +
        (f.present ? '<div class="meter" title="' + pct + '% can be cleaned"><span style="width:' + pct + '%"></span></div>' +
          '<div class="legend"><span>' + pct + "% cleanable now</span></div>" +
          '<dl class="kv mt"><dt>Total</dt><dd>' + fmtBytes(f.total_bytes) + " · " + fmtNum(f.total_files) + " files</dd>" +
          "<dt>Cleanable now</dt><dd>" + fmtBytes(f.deletable_bytes) + " · " + fmtNum(f.deletable_files) + " files</dd>" +
          "<dt>Keeps</dt><dd>last " + f.keep_days + " day" + (f.keep_days > 1 ? "s" : "") + " (since " + esc(st.cutoff_local.slice(0, 10)) + ")</dd>" +
          (f.truncated ? '<dt></dt><dd><span class="pill warn">Scan budget reached — numbers are partial</span></dd>' : "") + "</dl>" +
          '<div class="mt">' + barChart(days.map((d) => ({
            label: d.date.slice(5), title: d.date + ": " + fmtBytes(d.bytes) + " in " + d.files + " files" + (d.protected ? " (protected: today)" : d.del_files ? ", " + fmtBytes(d.del_bytes) + " cleanable" : " (kept)"),
            parts: d.protected ? [{ v: d.bytes, cls: "bar-today" }] : [{ v: d.del_bytes, cls: "bar-del" }, { v: d.bytes - d.del_bytes, cls: "bar-keep" }],
          })), { fmt: fmtBytes, emptyText: "Folder is empty", w: 560, h: 200 }) + "</div>" +
          '<div class="legend"><span><i style="background:var(--bar-del)"></i>Will be cleaned</span><span><i style="background:var(--bar-keep)"></i>Kept</span><span><i style="background:var(--bar-today)"></i>Today (always kept)</span></div>'
          : '<p class="muted">This folder does not exist inside the container. Check the host volume in <code>docker-compose.yml</code>.</p>');
    });
  } catch (e) {
    $$(".folder-card .spin").forEach((x) => x.remove());
    toast("Could not scan folders: " + e.message, "err");
  }
}

async function loadRecent(el, n) {
  const r = await api("GET", "/api/runs?limit=" + n);
  if (!r.runs.length) { el.innerHTML = '<div class="empty">' + ICON.empty + "No cleanups yet. Click <b>Preview</b> to see what would be removed.</div>"; return; }
  el.innerHTML = runsTable(r.runs, true);
  bindRunRows(el, r.runs);
}

function runsTable(runs, compact) {
  return '<div class="table-wrap"><table><thead><tr><th>When</th><th>Trigger</th>' + (compact ? "" : "<th>By</th>") +
    '<th>Result</th><th>Folders</th><th class="num">Files</th><th class="num">Space</th>' + (compact ? "" : '<th class="num">Duration</th><th>Note</th>') +
    "</tr></thead><tbody>" + runs.map((r, i) => {
      const files = r.dry_run ? r.candidates : r.removed, bytes = r.dry_run ? r.cand_bytes : r.bytes_freed;
      return '<tr data-i="' + i + '"><td title="' + esc(fmtTs(r.started, true)) + '">' + esc(fmtTs(r.started)) + '<br><small>' + esc(fmtAgo(r.started)) + "</small></td>" +
        "<td>" + esc(TRIGGERS[r.trigger] || r.trigger) + "</td>" + (compact ? "" : "<td>" + esc(r.by_user || "scheduler") + "</td>") +
        "<td>" + outcomePill(r) + "</td><td>" + esc((r.folders || "—").replace(/,/g, ", ")) + "</td>" +
        '<td class="num">' + fmtNum(files) + (r.dry_run ? " <small>found</small>" : "") + '</td><td class="num">' + fmtBytes(bytes) + (r.dry_run ? " <small>found</small>" : "") + "</td>" +
        (compact ? "" : '<td class="num">' + fmtDur(((r.finished || r.started) - r.started) * 1000) + '</td><td class="note">' + esc(r.note || "") + "</td>") + "</tr>";
    }).join("") + "</tbody></table></div>";
}
function bindRunRows(el, runs) {
  $$("tbody tr", el).forEach((tr) => tr.addEventListener("click", () => runDetail(runs[+tr.dataset.i])));
}

function runDetail(r) {
  const d = r.details || {}, pf = d.per_folder || {};
  const rows = Object.keys(pf).map((k) => "<tr><td>" + esc(k) + '</td><td class="mono" style="white-space:normal">' + esc(pf[k].path) + "</td><td>" + pf[k].keep_days + ' d</td><td class="num">' +
    fmtNum(pf[k].candidates) + " / " + fmtBytes(pf[k].cand_bytes) + '</td><td class="num">' + fmtNum(pf[k].removed) + " / " + fmtBytes(pf[k].bytes_freed) + "</td></tr>").join("");
  modal("<h2>Run #" + r.id + " " + outcomePill(r) + "</h2>" +
    '<dl class="kv"><dt>Started</dt><dd>' + esc(fmtTs(r.started, true)) + "</dd><dt>Trigger</dt><dd>" + esc(TRIGGERS[r.trigger] || r.trigger) + (r.by_user ? " by " + esc(r.by_user) : "") +
    "</dd><dt>Mode</dt><dd>" + (r.dry_run ? "Preview (dry run)" + (d.forced_dry ? " — forced by dry-run-only mode" : "") : "Real cleanup") +
    "</dd><dt>Duration</dt><dd>" + fmtDur(((r.finished || r.started) - r.started) * 1000) + "</dd>" +
    "<dt>Found</dt><dd>" + fmtNum(r.candidates) + " files · " + fmtBytes(r.cand_bytes) + "</dd>" +
    "<dt>Removed</dt><dd>" + fmtNum(r.removed) + " files · " + fmtBytes(r.bytes_freed) + "</dd>" +
    (r.dirs_pruned ? "<dt>Empty folders</dt><dd>" + r.dirs_pruned + " removed</dd>" : "") +
    (r.errors || r.refused || r.vanished ? "<dt>Other</dt><dd>" + r.errors + " errors · " + r.refused + " refused by safety re-check · " + r.vanished + " already gone</dd>" : "") +
    (d.mount_verified !== undefined && d.mount_verified !== null ? "<dt>Folder check</dt><dd>" + (d.mount_verified ? "verified" : "WRONG FOLDER") + " — " + esc(d.mount_detail) + "</dd>" : "") +
    (r.truncated ? '<dt></dt><dd><span class="pill warn">Hit a time/file budget — the next run continues</span></dd>' : "") +
    "</dl>" +
    (rows ? '<h3 class="mt">Per folder</h3><div class="table-wrap"><table><thead><tr><th>Folder</th><th>Path</th><th>Keep</th><th class="num">Found</th><th class="num">Removed</th></tr></thead><tbody>' + rows + "</tbody></table></div>" : "") +
    ((d.skipped || []).length ? '<h3 class="mt">Notes</h3><ul>' + d.skipped.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "") +
    ((d.error_samples || []).length ? '<h3 class="mt">Errors</h3><ul>' + d.error_samples.map((x) => '<li class="mono">' + esc(x) + "</li>").join("") + "</ul>" : "") +
    (r.note && !(d.skipped || []).length ? '<p class="muted mt">' + esc(r.note) + "</p>" : "") +
    '<div class="modal-foot"><button class="btn" data-close>Close</button></div>', { wide: true });
}

/* ---------- the clean flow: always preview first ---------- */
async function cleanFlow(allowDelete) {
  const m = modal('<h2>' + (allowDelete ? "Clean now" : "Preview") + '</h2><div class="empty"><span class="spin"></span><p>Scanning folders…</p></div>', { sticky: true });
  let p;
  try { p = await api("POST", "/api/clean", { dry_run: true }); }
  catch (e) { m.close(); toast(e.message, "err"); return; }
  const pf = p.per_folder || {};
  const dryOnly = APP.status && APP.status.safety.dry_run_only;
  const rows = Object.keys(pf).map((k) => "<tr><td>" + esc(k) + '</td><td class="num">' + fmtNum(pf[k].candidates) + '</td><td class="num">' + fmtBytes(pf[k].cand_bytes) +
    "</td><td>older than " + esc(pf[k].cutoff.slice(0, 10)) + "</td></tr>").join("");
  const canDelete = allowDelete && !dryOnly && p.candidates > 0 && p.ok;
  m.el.innerHTML = "<h2>" + (allowDelete ? "Clean now" : "Preview") + "</h2>" +
    '<div class="row"><div><div class="big-num">' + fmtBytes(p.cand_bytes) + '</div><div class="muted">' + fmtNum(p.candidates) + " file" + (p.candidates === 1 ? "" : "s") +
    " can be removed</div></div></div>" +
    (rows ? '<div class="table-wrap mt"><table><thead><tr><th>Folder</th><th class="num">Files</th><th class="num">Size</th><th>Range</th></tr></thead><tbody>' + rows + "</tbody></table></div>" : "") +
    (p.skipped.length ? '<div class="mt">' + alertsHtml(p.skipped.map((x) => ({ level: "warn", text: x }))) + "</div>" : "") +
    (allowDelete && dryOnly ? alertsHtml([{ level: "info", text: "Dry-run-only mode is on, so nothing will be deleted. Turn it off in Settings → Safety when this preview looks right." }]) : "") +
    '<p class="muted" style="font-size:12.5px">Files from today are always kept, and every file is re-checked right before it is deleted. This preview was saved to History.</p>' +
    '<div class="modal-foot"><button class="btn ghost" data-close>Close</button>' +
    (allowDelete && dryOnly ? '<a class="btn" href="#/settings/safety" data-close>Open safety settings</a>' : "") +
    (canDelete ? '<button class="btn danger" id="cf-go">' + ICON.broom + "Delete " + fmtNum(p.candidates) + " files</button>" : "") + "</div>";
  $$("[data-close]", m.el).forEach((b) => b.addEventListener("click", m.close));
  if (!canDelete) return;
  $("#cf-go", m.el).addEventListener("click", async () => {
    m.el.innerHTML = '<h2>Cleaning…</h2><div class="empty"><span class="spin"></span><p>Deleting files — this can take a while for large folders.</p></div>';
    try {
      const r = await api("POST", "/api/clean", { dry_run: false });
      m.close();
      if (r.outcome === "ok") toast("Freed " + fmtBytes(r.bytes_freed) + " (" + fmtNum(r.removed) + " files).", "ok");
      else toast("Cleanup " + r.outcome + ": " + (r.note || ""), "err");
    } catch (e) { m.close(); toast(e.message, "err"); }
    route();
  });
}

/* ======================================================================
   History
   ====================================================================== */
const HIST = { offset: 0, limit: 25, mode: "", trigger: "", outcome: "" };
async function pageHistory(view) {
  const [ser, st] = await Promise.all([api("GET", "/api/runs/series?days=30"), api("GET", "/api/status?probe=false")]);
  APP.tz = st.timezone;
  const t = st.totals;
  view.innerHTML = '<div class="page-head"><div><h1>History</h1><div class="sub">Every cleanup, preview and missed schedule is recorded here.</div></div>' +
    '<div class="actions"><a class="btn" href="/api/runs/export.csv">' + ICON.download + "Export CSV</a></div></div>" +
    '<div class="grid g4">' +
    '<div class="card stat hero"><div class="label">Freed · 30 days</div><div class="value">' + fmtBytes(t.freed_30d) + "</div></div>" +
    '<div class="card stat"><div class="label">Files removed · 30 days</div><div class="value">' + fmtNum(t.removed_30d) + "</div></div>" +
    '<div class="card stat"><div class="label">Freed all time</div><div class="value">' + fmtBytes(t.freed_all) + "</div></div>" +
    '<div class="card stat"><div class="label">Real cleanups</div><div class="value">' + fmtNum(t.real_runs) + "</div></div></div>" +
    '<div class="card mt"><div class="card-head"><h2>Space freed per day</h2><span class="right muted">last 30 days</span></div>' +
    barChart(ser.series.map((d) => ({ label: d.date.slice(5), title: d.date + ": " + fmtBytes(d.freed) + ", " + d.removed + " files, " + d.runs + " runs", parts: [{ v: d.freed, cls: "bar-del" }] })), { fmt: fmtBytes, w: 1100, h: 220 }) + "</div>" +
    '<div class="card mt"><div class="row" style="margin-bottom:12px">' +
    '<select id="h-mode" style="width:auto"><option value="">All runs</option><option value="real">Real cleanups</option><option value="dry">Previews</option></select>' +
    '<select id="h-trigger" style="width:auto"><option value="">Any trigger</option><option value="schedule">Scheduled</option><option value="manual">Manual</option><option value="catchup">Catch-up</option></select>' +
    '<select id="h-outcome" style="width:auto"><option value="">Any result</option><option value="ok">Completed</option><option value="skipped">Skipped</option><option value="missed">Missed</option><option value="wrong_mount">Wrong folder</option><option value="error">Error</option></select>' +
    '</div><div id="h-table"></div><div class="pager"><button class="btn sm" id="h-prev">← Newer</button><span id="h-page" class="muted"></span><button class="btn sm" id="h-next">Older →</button></div></div>';
  ["mode", "trigger", "outcome"].forEach((k) => {
    const el = $("#h-" + k);
    el.value = HIST[k];
    el.addEventListener("change", () => { HIST[k] = el.value; HIST.offset = 0; loadHist(); });
  });
  $("#h-prev").addEventListener("click", () => { HIST.offset = Math.max(0, HIST.offset - HIST.limit); loadHist(); });
  $("#h-next").addEventListener("click", () => { HIST.offset += HIST.limit; loadHist(); });
  await loadHist();
}
async function loadHist() {
  const q = "?limit=" + HIST.limit + "&offset=" + HIST.offset + "&mode=" + HIST.mode + "&trigger=" + HIST.trigger + "&outcome=" + HIST.outcome;
  const r = await api("GET", "/api/runs" + q);
  const el = $("#h-table");
  if (!el) return;
  el.innerHTML = r.runs.length ? runsTable(r.runs, false) : '<div class="empty">' + ICON.empty + "No runs match.</div>";
  bindRunRows(el, r.runs);
  const from = r.total ? HIST.offset + 1 : 0, to = Math.min(r.total, HIST.offset + HIST.limit);
  $("#h-page").textContent = from + "–" + to + " of " + r.total;
  $("#h-prev").disabled = HIST.offset === 0;
  $("#h-next").disabled = to >= r.total;
}

/* ======================================================================
   Logs
   ====================================================================== */
async function pageLogs(view) {
  const L = { last: 0, level: "", q: "", follow: true, paused: false };
  view.innerHTML = '<div class="page-head"><div><h1>Logs</h1><div class="sub">Live activity from ComfySweep — sign-ins, setting changes, cleanups and warnings.</div></div>' +
    '<div class="actions"><a class="btn" href="/api/logs/export.txt">' + ICON.download + "Download</a></div></div>" +
    '<div class="row" style="margin-bottom:12px"><select id="l-level" style="width:auto"><option value="">All levels</option><option value="INFO">Info and above</option><option value="WARNING">Warnings and errors</option><option value="ERROR">Errors only</option></select>' +
    '<input type="text" id="l-q" placeholder="Search…" style="max-width:280px">' +
    '<label class="switch"><input type="checkbox" id="l-follow" checked><span class="track"></span>Auto-scroll</label><span class="spacer"></span>' +
    '<button class="btn sm" id="l-pause">Pause</button></div><div class="logbox" id="l-box"></div>';
  const box = $("#l-box");
  const line = (r) => '<div class="logline"><span class="ts">' + esc(fmtTs(r.ts)) + ":" + String(new Date(r.ts * 1000).getSeconds()).padStart(2, "0") +
    '</span><span class="lv-' + esc(r.level) + '">' + esc(r.level) + '</span><span class="src">' + esc(r.source) + '</span><span class="msg">' + esc(r.msg) + "</span></div>";
  async function load(reset) {
    if (reset) { L.last = 0; box.innerHTML = ""; }
    const r = await api("GET", "/api/logs?after=" + L.last + "&limit=500&level=" + L.level + "&q=" + encodeURIComponent(L.q));
    if (!r.logs.length) { if (reset) box.innerHTML = '<div class="empty">No log lines match.</div>'; return; }
    if (reset) box.innerHTML = "";
    box.insertAdjacentHTML("beforeend", r.logs.map(line).join(""));
    L.last = r.logs[r.logs.length - 1].id;
    while (box.children.length > 3000) box.firstElementChild.remove();
    if (L.follow) box.scrollTop = box.scrollHeight;
  }
  $("#l-level").addEventListener("change", (e) => { L.level = e.target.value; load(true); });
  $("#l-q").addEventListener("input", debounce((e) => { L.q = e.target.value; load(true); }, 300));
  $("#l-follow").addEventListener("change", (e) => { L.follow = e.target.checked; });
  $("#l-pause").addEventListener("click", (e) => { L.paused = !L.paused; e.target.textContent = L.paused ? "Resume" : "Pause"; });
  await load(true);
  APP.timers.push(setInterval(() => { if (!L.paused) load(false).catch(() => {}); }, 3000));
}

/* ======================================================================
   Settings
   ====================================================================== */
const TABS = [["comfyui", "ComfyUI"], ["folders", "Folders"], ["schedule", "Schedule"], ["safety", "Safety"], ["security", "Security"]];

async function loadSettings() {
  const r = await api("GET", "/api/settings");
  APP.meta = r; APP.saved = clone(r.settings); APP.cfg = clone(r.settings);
  APP.tz = r.settings.timezone;
}
const dirty = () => JSON.stringify(APP.cfg) !== JSON.stringify(APP.saved);

async function pageSettings(view, tab) {
  if (!APP.cfg || !dirty()) await loadSettings();
  view.innerHTML = '<div id="settings-root"><div class="page-head"><div><h1>Settings</h1><div class="sub">Everything ComfySweep does is configured here and stored in its database.</div></div></div>' +
    '<div class="tabs">' + TABS.map((t) => '<a href="#/settings/' + t[0] + '" class="' + (t[0] === tab ? "on" : "") + '">' + t[1] + "</a>").join("") + "</div>" +
    '<div id="tab"></div>' +
    (tab !== "security" ? '<div class="savebar"><span id="dirty" class="muted"></span><span class="spacer"></span><button class="btn ghost" id="s-discard">Discard</button><button class="btn primary" id="s-save">Save changes</button></div>' : "") + "</div>";
  const el = $("#tab");
  if (tab === "folders") renderFoldersTab(el);
  else if (tab === "schedule") renderScheduleTab(el);
  else if (tab === "safety") renderSafetyTab(el);
  else if (tab === "security") await renderSecurityTab(el);
  else renderComfyTab(el);
  if (tab === "security") return;
  const upd = () => { $("#dirty").textContent = dirty() ? "You have unsaved changes" : "All changes saved"; $("#s-save").disabled = !dirty(); };
  upd();
  const root = $("#settings-root");
  root.addEventListener("input", upd);
  root.addEventListener("click", () => setTimeout(upd, 0));
  $("#s-discard").addEventListener("click", () => { APP.cfg = clone(APP.saved); route(); });
  $("#s-save").addEventListener("click", async () => {
    const b = $("#s-save"); b.disabled = true;
    try {
      const r = await api("PUT", "/api/settings", APP.cfg);
      APP.meta = r; APP.saved = clone(r.settings); APP.cfg = clone(r.settings); APP.tz = r.settings.timezone;
      toast("Settings saved.", "ok");
      refreshSide();
      route();
    } catch (e) { toast(e.message, "err"); b.disabled = false; }
  });
}

function bind(root, after) {
  // Re-rendering a tab into the same element must not stack listeners.
  root._after = after;
  if (root._bound) return;
  root._bound = true;
  const h = (e) => {
    const el = e.target, p = el.dataset && el.dataset.bind;
    if (!p) return;
    let v;
    if (el.type === "checkbox") v = el.checked;
    else if (el.type === "number") v = el.value === "" ? 0 : Number(el.value);
    else if (el.dataset.kind === "list") v = el.value.split(",").map((x) => x.trim()).filter(Boolean);
    else v = el.value;
    setPath(APP.cfg, p, v);
    root._after && root._after(p, v);
  };
  root.addEventListener("input", h);
  root.addEventListener("change", h);
}
const sw = (path, label) => '<label class="switch"><input type="checkbox" data-bind="' + path + '"' + (getPath(APP.cfg, path) ? " checked" : "") + '><span class="track"></span>' + label + "</label>";
const num = (path, min, max, step) => '<input type="number" data-bind="' + path + '" value="' + esc(getPath(APP.cfg, path)) + '" min="' + min + '" max="' + max + '" step="' + (step || 1) + '">';

/* ---------- ComfyUI ---------- */
function renderComfyTab(el, wizard) {
  const c = APP.cfg;
  el.innerHTML = '<div class="' + (wizard ? "" : "card") + '"><div class="field"><label>ComfyUI URL</label><div class="input-group"><input type="url" data-bind="comfy_url" value="' + esc(c.comfy_url) + '" placeholder="http://host.docker.internal:8188">' +
    '<button class="btn" id="t-test">Test connection</button></div><span class="help">How ComfySweep reaches ComfyUI from inside its container. On the same server use <code>http://host.docker.internal:8188</code> (or <code>http://127.0.0.1:8188</code> with host networking).</span><div id="t-res"></div></div>' +
    '<div class="grid g2"><div class="field"><label>Timezone</label><input type="text" list="tzlist" data-bind="timezone" value="' + esc(c.timezone) + '"><datalist id="tzlist"></datalist>' +
    '<span class="help">Decides when "today" starts (today\'s files are never deleted) and when schedules fire.</span></div>' +
    '<div class="field"><label>Request timeout (seconds)</label>' + num("probe_timeout", 1, 60) + '<span class="help">For ComfyUI status checks.</span></div></div></div>';
  bind(el);
  $("#t-test", el).addEventListener("click", async (e) => {
    e.preventDefault();
    const res = $("#t-res", el);
    res.innerHTML = '<span class="spin"></span>';
    try {
      const p = await api("POST", "/api/settings/test-comfy", { url: APP.cfg.comfy_url, timeout: APP.cfg.probe_timeout });
      res.innerHTML = p.reachable ? alertsHtml([{ level: "info", text: "Connected in " + p.ms + " ms — queue: " + p.queue_running + " running, " + p.queue_pending + " pending." }])
        : alertsHtml([{ level: "error", text: "Not reachable: " + p.error }]);
    } catch (err) { res.innerHTML = alertsHtml([{ level: "error", text: err.message }]); }
  });
  loadZones().then((z) => { const dl = $("#tzlist", el); if (dl) dl.innerHTML = z.map((x) => '<option value="' + esc(x) + '">').join(""); });
  if (!APP.cfg.timezone || (wizard && APP.cfg.timezone === "UTC")) {
    try { const guess = Intl.DateTimeFormat().resolvedOptions().timeZone; if (guess) { APP.cfg.timezone = guess; $("[data-bind=timezone]", el).value = guess; } } catch (e) {}
  }
}
async function loadZones() {
  if (APP.zones) return APP.zones;
  try { APP.zones = (await api("GET", "/api/meta/timezones")).zones; } catch (e) { APP.zones = []; }
  return APP.zones;
}

/* ---------- Folders ---------- */
const FOLDER_HELP = {
  output: "Images, videos and 3D files ComfyUI generates (its <code>output/</code> folder). Cleaned even while jobs run — a running job only writes new files, which are always kept.",
  input: "Files uploaded to ComfyUI (its <code>input/</code> folder). Skipped whenever the queue is busy or unreadable, because a queued job may still need them.",
  temp: "Preview images (ComfyUI's <code>temp/</code> folder). Skipped while the queue is busy.",
};
function renderFoldersTab(el, wizard) {
  const labels = (APP.meta && APP.meta.folder_labels) || { output: "Generated outputs", input: "Uploaded inputs", temp: "Temporary previews" };
  const host = (APP.meta && APP.meta.host_root) || "/host";
  el.innerHTML = (wizard ? "" : alertsHtml([{ level: "info", text: "Folders are picked inside " + host + ", the host directory mounted in docker-compose.yml. If ComfyUI's folders are not listed, change that volume and recreate the container." }])) +
    '<div class="grid">' + ["output", "input", "temp"].map((k) => {
      const p = "folders." + k + ".";
      return '<div class="card"><div class="card-head"><h2>' + esc(labels[k]) + '</h2><span class="right">' + sw(p + "enabled", "Clean this folder") + "</span></div>" +
        '<p class="muted" style="margin-top:0;font-size:13px">' + FOLDER_HELP[k] + "</p>" +
        '<div class="field"><label>Folder</label><div class="input-group"><input type="text" data-bind="' + p + 'path" value="' + esc(APP.cfg.folders[k].path) + '" placeholder="' + host + '/ComfyUI/' + k + '">' +
        '<button class="btn" data-browse="' + k + '">' + ICON.folder + "Browse</button></div></div>" +
        '<div class="grid g2"><div class="field"><label>Keep files for (days)</label>' + num(p + "keep_days", 1, 3650) + '<span class="help">1 = keep only today. 7 = keep today plus the previous 6 days.</span></div>' +
        '<div class="field"><label>Minimum age (minutes)</label>' + num(p + "min_age_min", 5, 1440) + '<span class="help">Extra protection just after midnight. 60 is a good default.</span></div></div></div>';
    }).join("") + "</div>";
  bind(el);
  $$("[data-browse]", el).forEach((b) => b.addEventListener("click", async (e) => {
    e.preventDefault();
    const k = b.dataset.browse;
    const chosen = await browseFolder(APP.cfg.folders[k].path || host, k);
    if (chosen) {
      APP.cfg.folders[k].path = chosen;
      APP.cfg.folders[k].enabled = true;
      $('[data-bind="folders.' + k + '.path"]', el).value = chosen;
      $('[data-bind="folders.' + k + '.enabled"]', el).checked = true;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }));
}

function browseFolder(start, kind) {
  return new Promise((resolve) => {
    let current = null, done = false;
    const m = modal('<h2>Choose the ' + esc(kind) + ' folder</h2><div class="crumbs" id="b-path"></div><div class="browser-list" id="b-list"></div><div id="b-info"></div>' +
      '<div class="modal-foot"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="b-ok">Use this folder</button></div>',
      { wide: true, onClose: () => { if (!done) resolve(null); } });
    async function go(path) {
      $("#b-list", m.el).innerHTML = '<div class="empty"><span class="spin"></span></div>';
      try {
        const r = await api("GET", "/api/fs/browse?path=" + encodeURIComponent(path));
        current = r;
        $("#b-path", m.el).textContent = r.path;
        let html = r.parent ? '<button data-go="' + esc(r.parent) + '">' + ICON.up + "<b>..</b>&nbsp;<span class='muted'>up one level</span></button>" : "";
        html += r.dirs.map((d) => '<button data-go="' + esc(r.path + "/" + d) + '">' + ICON.folder + esc(d) + (d === kind ? ' <span class="pill brand">looks right</span>' : "") + "</button>").join("");
        $("#b-list", m.el).innerHTML = html || '<div class="empty">No sub-folders here.</div>';
        $$("[data-go]", m.el).forEach((b) => b.addEventListener("click", () => go(b.dataset.go)));
        $("#b-ok", m.el).disabled = r.is_host_root;
        $("#b-info", m.el).innerHTML = r.is_host_root ? '<p class="muted">Open a sub-folder — the mount root itself cannot be cleaned.</p>'
          : r.writable ? "" : alertsHtml([{ level: "warn", text: "ComfySweep cannot write here (" + r.writable_probe + "), so it could count files but not delete them." }]);
      } catch (e) {
        if (path !== (APP.meta && APP.meta.host_root)) return go((APP.meta && APP.meta.host_root) || "");
        $("#b-list", m.el).innerHTML = alertsHtml([{ level: "error", text: e.message }]);
      }
    }
    $("#b-ok", m.el).addEventListener("click", () => { done = true; resolve(current && current.path); m.close(); });
    go(start);
  });
}

/* ---------- Schedule ---------- */
function renderScheduleTab(el, wizard) {
  const s = APP.cfg.schedule;
  el.innerHTML = '<div class="' + (wizard ? "" : "card") + '"><div class="field">' + sw("schedule.enabled", "Run cleanups automatically") + "</div>" +
    '<div class="field"><span class="lbl">How often</span><div class="seg" id="s-mode">' +
    [["daily", "Every day"], ["weekly", "Selected days"], ["interval", "Every N hours"]].map((m) => '<button data-mode="' + m[0] + '" class="' + (s.mode === m[0] ? "on" : "") + '">' + m[1] + "</button>").join("") + "</div></div>" +
    '<div class="grid g2"><div class="field"><label>' + (s.mode === "interval" ? "Starting at" : "At") + '</label><input type="time" data-bind="schedule.time" value="' + esc(s.time) + '"><span class="help">In ' + esc(APP.cfg.timezone) + ". Pick a quiet hour.</span></div>" +
    (s.mode === "interval" ? '<div class="field"><label>Every (hours)</label>' + num("schedule.interval_hours", 1, 168) + "</div>" : "<div></div>") + "</div>" +
    (s.mode === "weekly" ? '<div class="field"><span class="lbl">On these days</span><div class="chips">' + WEEKDAYS.map((d, i) => '<button class="chip ' + (s.weekdays.includes(i) ? "on" : "") + '" data-wd="' + i + '">' + d + "</button>").join("") + "</div></div>" : "") +
    (wizard ? "" : '<div class="field" style="max-width:320px"><label>Catch-up window (hours)</label>' + num("schedule.catchup_hours", 0, 72, 0.5) +
      '<span class="help">If ComfySweep was down when a run was due, it still runs if it comes back within this window; otherwise the run is logged as missed.</span></div>') +
    '<div class="field"><span class="lbl">Upcoming runs</span><div id="s-up" class="muted"></div></div></div>';
  bind(el, (p) => { if (p.startsWith("schedule.") || p === "timezone") preview(); });
  $$("[data-mode]", el).forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); APP.cfg.schedule.mode = b.dataset.mode; renderScheduleTab(el, wizard); if (wizard) renderDryRunToggle(el); }));
  $$("[data-wd]", el).forEach((b) => b.addEventListener("click", (e) => {
    e.preventDefault();
    const i = +b.dataset.wd, w = APP.cfg.schedule.weekdays;
    APP.cfg.schedule.weekdays = w.includes(i) ? w.filter((x) => x !== i) : w.concat([i]).sort();
    b.classList.toggle("on");
    preview();
  }));
  const preview = debounce(async () => {
    const up = $("#s-up", el);
    if (!up) return;
    if (!APP.cfg.schedule.enabled) { up.textContent = "Automatic cleanups are off."; return; }
    try {
      const r = await api("POST", "/api/settings/preview-schedule", APP.cfg);
      up.innerHTML = r.upcoming.length ? r.upcoming.map((u) => '<span class="pill brand" style="margin:0 6px 6px 0">' + esc(u.local.slice(0, 16)) + "</span>").join("") : "Never — pick at least one day.";
    } catch (e) { up.textContent = e.message; }
  }, 250);
  preview();
}
function renderDryRunToggle(el) {
  el.insertAdjacentHTML("beforeend", '<div class="card mt" style="box-shadow:none">' + sw("safety.dry_run_only", "Dry-run-only mode (recommended for the first run)") +
    '<p class="muted" style="margin:8px 0 0;font-size:13px">While on, every run — scheduled or manual — only counts what it would delete. Check the result in History, then switch it off in Settings → Safety.</p></div>');
}

/* ---------- Safety ---------- */
function renderSafetyTab(el) {
  const sf = APP.cfg.safety;
  el.innerHTML = '<div class="card"><div class="card-head"><h2>Deleting</h2></div>' +
    '<div class="field">' + sw("safety.dry_run_only", "Dry-run-only mode") + '<span class="help">Every run only counts files; nothing is deleted. Turn off once a preview looks right.</span></div>' +
    '<div class="field">' + sw("safety.refuse_on_wrong_mount", "Refuse to delete when ComfyUI says the output folder is wrong") + '<span class="help">ComfySweep asks ComfyUI for its latest outputs and checks they are in your output folder. Strongly recommended.</span></div>' +
    '<div class="field">' + sw("safety.prune_empty_dirs", "Remove sub-folders left empty after a cleanup") + '<span class="help">The selected folder itself is never removed.</span></div>' +
    '<div class="field"><label>Only these file types (optional)</label><input type="text" data-kind="list" data-bind="safety.extensions" value="' + esc(sf.extensions.join(", ")) + '" placeholder="e.g. .png, .jpg, .webp, .mp4">' +
    '<span class="help">Comma-separated. Leave empty to clean every file type.</span></div></div>' +
    '<div class="card mt"><div class="card-head"><h2>Per-run limits</h2></div><div class="grid g2">' +
    '<div class="field"><label>Max files per run</label>' + num("safety.max_files_per_run", 0, 100000000) + '<span class="help">0 = no limit. A folder over the limit is skipped and noted in History.</span></div>' +
    '<div class="field"><label>Max GB per run</label>' + num("safety.max_gb_per_run", 0, 1000000, 0.1) + '<span class="help">0 = no limit.</span></div></div></div>' +
    '<div class="card mt"><div class="card-head"><h2>Retention &amp; budgets</h2></div><div class="grid g2">' +
    '<div class="field"><label>History entries to keep</label>' + num("safety.history_keep", 10, 100000) + "</div>" +
    '<div class="field"><label>Log lines to keep</label>' + num("safety.log_keep", 100, 200000) + "</div>" +
    '<div class="field"><label>Scan time budget (seconds)</label>' + num("safety.scan_seconds", 5, 3600) + '<span class="help">Very large folders are scanned in parts; the next run continues.</span></div>' +
    '<div class="field"><label>Delete time budget (seconds)</label>' + num("safety.run_seconds", 30, 86400) + "</div>" +
    '<div class="field"><label>Max files scanned per folder</label>' + num("safety.max_scan_files", 1000, 50000000) + "</div></div></div>";
  bind(el);
}

/* ---------- Security ---------- */
async function renderSecurityTab(el) {
  el.innerHTML = '<div class="grid g2"><div class="card"><div class="card-head"><h2>Change password</h2></div><form id="pw-form">' +
    '<div class="field"><label>Current password</label><input type="password" id="pw-cur" autocomplete="current-password" required></div>' +
    '<div class="field"><label>New password</label><input type="password" id="pw-new" autocomplete="new-password" minlength="8" required></div>' +
    '<div class="field"><label>Confirm new password</label><input type="password" id="pw-new2" autocomplete="new-password" required></div>' +
    '<button class="btn primary" type="submit">Update password</button></form></div>' +
    '<div class="card"><div class="card-head"><h2>API keys</h2><button class="right btn sm" id="k-new">' + ICON.key + "New key</button></div>" +
    '<p class="muted" style="margin-top:0;font-size:13px">For scripts and monitoring. Send it as the <code>X-API-Key</code> header. Interactive docs: <a href="/api/docs" target="_blank" rel="noopener">/api/docs</a>.</p><div id="k-list"></div></div></div>';
  $("#pw-form", el).addEventListener("submit", async (e) => {
    e.preventDefault();
    if ($("#pw-new").value !== $("#pw-new2").value) return toast("The new passwords do not match.", "err");
    try {
      await api("POST", "/api/auth/password", { current: $("#pw-cur").value, new: $("#pw-new").value });
      showLogin("Password updated — please sign in with the new password.");
    } catch (err) { toast(err.message, "err"); }
  });
  $("#k-new", el).addEventListener("click", async () => {
    const m = modal('<h2>New API key</h2><div class="field"><label>Name</label><input type="text" id="k-name" placeholder="e.g. monitoring"></div><div class="modal-foot"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="k-go">Create</button></div>');
    $("#k-name", m.el).focus();
    $("#k-go", m.el).addEventListener("click", async () => {
      try {
        const r = await api("POST", "/api/keys", { name: $("#k-name", m.el).value || "key" });
        m.el.innerHTML = '<h2>Your new API key</h2>' + alertsHtml([{ level: "warn", text: "Copy it now — it will not be shown again." }]) +
          '<div class="crumbs" style="user-select:all">' + esc(r.key) + '</div><div class="modal-foot"><button class="btn" id="k-copy">Copy</button><button class="btn primary" data-close>Done</button></div>';
        $$("[data-close]", m.el).forEach((b) => b.addEventListener("click", m.close));
        $("#k-copy", m.el).addEventListener("click", () => { try { navigator.clipboard.writeText(r.key); toast("Copied.", "ok"); } catch (e) {} });
        loadKeys();
      } catch (e) { toast(e.message, "err"); }
    });
  });
  async function loadKeys() {
    const r = await api("GET", "/api/keys");
    const box = $("#k-list", el);
    if (!box) return;
    box.innerHTML = r.keys.length ? '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Key</th><th>Last used</th><th></th></tr></thead><tbody>' +
      r.keys.map((k) => "<tr><td>" + esc(k.name) + '</td><td class="mono">' + esc(k.prefix) + "…</td><td>" + (k.last_used ? esc(fmtAgo(k.last_used)) : "never") +
        '</td><td class="num"><button class="btn sm ghost" data-del="' + k.id + '">Revoke</button></td></tr>').join("") + "</tbody></table></div>"
      : '<div class="empty">No API keys yet.</div>';
    $$("[data-del]", box).forEach((b) => b.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!(await confirmBox("Revoke API key?", "Anything using this key will stop working immediately.", "Revoke", true))) return;
      await api("DELETE", "/api/keys/" + b.dataset.del);
      loadKeys();
    }));
  }
  await loadKeys();
}

boot();
