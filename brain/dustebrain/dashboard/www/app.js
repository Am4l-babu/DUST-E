// DUST-E BRAIN dashboard - Phase 2 (DRIVE, HW, DEBUG).
// No framework, no build step: this is served by dustebrain.dashboard.server
// straight from disk. Polls /api/status every 150 ms - well under the body's
// own command TTL - and while a drive button is held, resends /api/drive on
// the same cadence so the command never expires mid-press.

(() => {
  const POLL_MS = 150;
  const $ = (sel) => document.querySelector(sel);

  async function postJSON(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    return res.json();
  }

  // ---------------------------------------------------------------- tabs
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(`.panel[data-panel="${btn.dataset.tab}"]`).classList.add("active");
    });
  });

  // --------------------------------------------------------------- drive
  const speedInput = $("#speed");
  const speedOut = $("#speedOut");
  speedInput.addEventListener("input", () => { speedOut.textContent = `${speedInput.value}%`; });

  let driveTimer = null;

  function startDrive(lMul, rMul) {
    stopDrive();
    const speed = parseInt(speedInput.value, 10);
    const send = () => postJSON("/api/drive", {
      l: Math.round(lMul * speed),
      r: Math.round(rMul * speed),
    });
    send();
    driveTimer = setInterval(send, 100);
  }

  function stopDrive() {
    if (driveTimer) { clearInterval(driveTimer); driveTimer = null; }
    postJSON("/api/stop");
  }

  document.querySelectorAll(".dbtn[data-l]").forEach((btn) => {
    const l = parseFloat(btn.dataset.l);
    const r = parseFloat(btn.dataset.r);
    const down = (e) => { e.preventDefault(); startDrive(l, r); };
    const up = (e) => { e.preventDefault(); stopDrive(); };
    btn.addEventListener("mousedown", down);
    btn.addEventListener("touchstart", down, { passive: false });
    btn.addEventListener("mouseup", up);
    btn.addEventListener("mouseleave", up);
    btn.addEventListener("touchend", up);
    btn.addEventListener("touchcancel", up);
  });
  $("#stopBtn").addEventListener("click", stopDrive);

  // -------------------------------------------------------------- e-stop
  $("#estop").addEventListener("click", () => postJSON("/api/estop", { reason: "dashboard button" }));
  $("#resetSafety").addEventListener("click", () => postJSON("/api/reset_estop"));

  // ------------------------------------------------------------- render
  function kvRows(obj) {
    const entries = Object.entries(obj || {});
    if (!entries.length) return '<div class="row"><span>&mdash;</span></div>';
    return entries.map(([k, v]) => `<div class="row"><b>${k}</b><span>${fmt(v)}</span></div>`).join("");
  }

  function fmt(v) {
    if (v === null || v === undefined) return "null";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }

  function renderStatus(s) {
    const link = $("#link");
    link.classList.toggle("online", s.online);
    link.innerHTML = `<i class="dot"></i>${s.online ? "ONLINE" : (s.handshaken ? "STALE" : "OFFLINE")}`;

    $("#stHandshake").textContent = s.handshaken ? "YES" : "NO";
    $("#stMotionOk").textContent = s.motion_ok ? "CLEAR" : "BLOCKED";
    $("#stBattery").textContent = s.battery_mv === null || s.battery_mv === undefined
      ? "NOT INSTALLED" : `${(s.battery_mv / 1000).toFixed(2)} V`;
    $("#stInhibit").textContent = s.inhibit || "none";

    $("#ceilings").innerHTML = kvRows({
      "manual ceiling": `${s.manual_max_pct}%`,
      "auto ceiling": `${s.auto_max_pct}%`,
    });

    const banner = $("#estopBanner");
    if (s.estop) {
      banner.hidden = false;
      $("#estopReason").textContent = s.estop_reason || "(no reason reported)";
    } else {
      banner.hidden = true;
    }

    $("#hwFw").innerHTML = kvRows({ "firmware": s.fw_version || "(no handshake yet)" });
    $("#hwList").innerHTML = kvRows(s.hw);
    $("#limitsList").innerHTML = kvRows(s.limits);
    $("#telemetryRaw").innerHTML = kvRows(s.telemetry);

    $("#counters").innerHTML = kvRows({
      "crc errors": s.crc_errors,
      "rejected locally": s.rejected_local,
    });
  }

  function renderLog(entry) {
    const t = entry.dir || "?";
    return `<div class="${t}">[${entry.t}ms] ${t} ${JSON.stringify(entry)}</div>`;
  }

  async function poll() {
    try {
      const s = await (await fetch("/api/status")).json();
      renderStatus(s);
    } catch (e) { /* transient - next poll retries */ }

    const activeTab = document.querySelector(".tab.active").dataset.tab;
    if (activeTab === "debug") {
      try {
        const log = await (await fetch("/api/log")).json();
        $("#wireLog").innerHTML = log.wire.slice().reverse().map(renderLog).join("");
        $("#eventLog").innerHTML = log.events.slice().reverse().map((e) => `<div>${JSON.stringify(e)}</div>`).join("");
      } catch (e) { /* transient */ }
    }
  }

  setInterval(poll, POLL_MS);
  poll();
})();
