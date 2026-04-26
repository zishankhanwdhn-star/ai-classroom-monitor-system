/* common.js — AI Classroom Monitor v3 — Shared JS utilities */
'use strict';

// ── Clock ─────────────────────────────────────────────────────────────────────
function startClock() {
  function tick() {
    const d = new Date();
    const el = document.getElementById('clock');
    if (el) el.textContent =
      [d.getHours(), d.getMinutes(), d.getSeconds()]
        .map(n => String(n).padStart(2,'0')).join(':');
  }
  setInterval(tick, 1000); tick();
}

// ── Toast notification ────────────────────────────────────────────────────────
function showToast(msg, type = 'ok') {
  const el = document.getElementById('toast');
  if (!el) return;
  const styles = {
    ok:      { bg:'rgba(0,255,153,.1)',  border:'rgba(0,255,153,.35)',  color:'#00ff99' },
    error:   { bg:'rgba(255,34,68,.1)', border:'rgba(255,34,68,.35)', color:'#ff2244' },
    warning: { bg:'rgba(255,136,0,.1)', border:'rgba(255,136,0,.35)', color:'#ff8800' },
    info:    { bg:'rgba(0,238,255,.1)', border:'rgba(0,238,255,.35)', color:'#00eeff' },
  };
  const s = styles[type] || styles.ok;
  el.style.cssText = `background:${s.bg};border:1px solid ${s.border};color:${s.color};`;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3500);
}

// ── Alert popup ───────────────────────────────────────────────────────────────
let _alertSoundPlayed = false;
let _alertPopupShown  = false;

function showAlertPopup(msg) {
  const pop = document.getElementById('alert-popup');
  const txt = document.getElementById('alert-popup-msg');
  if (!pop || !txt) return;
  txt.textContent = msg;
  pop.classList.add('show');
  _alertPopupShown = true;
}

function hideAlertPopup() {
  const pop = document.getElementById('alert-popup');
  if (pop) pop.classList.remove('show');
  _alertPopupShown = false;
  _alertSoundPlayed = false;
}

function playAlertSound() {
  if (_alertSoundPlayed) return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const playBeep = (freq, startT, dur) => {
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.frequency.value = freq;
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.3, startT);
      gain.gain.exponentialRampToValueAtTime(0.001, startT + dur);
      osc.start(startT); osc.stop(startT + dur);
    };
    const now = ctx.currentTime;
    playBeep(880, now,        0.2);
    playBeep(660, now + 0.25, 0.2);
    playBeep(880, now + 0.5,  0.2);
    _alertSoundPlayed = true;
    setTimeout(() => { _alertSoundPlayed = false; }, 8000);
  } catch(e) { console.warn('Audio:', e); }
}

// ── Handle alert from API response ───────────────────────────────────────────
function handleAlert(alert) {
  const banner = document.getElementById('alert-banner');
  const msg    = document.getElementById('alert-msg');

  if (alert) {
    if (banner) { if(msg) msg.textContent = alert.message; banner.classList.add('show'); }
    if (alert.sound)  playAlertSound();
    if (alert.popup && !_alertPopupShown) showAlertPopup(alert.message);
  } else {
    if (banner) banner.classList.remove('show');
    hideAlertPopup();
  }
}

// ── Camera video fullscreen ───────────────────────────────────────────────────
function goFullscreen(imgId) {
  const img = document.getElementById(imgId);
  if (!img) return;
  if (img.requestFullscreen)            img.requestFullscreen();
  else if (img.webkitRequestFullscreen) img.webkitRequestFullscreen();
}

// ── Camera toggle ─────────────────────────────────────────────────────────────
async function toggleCamera() {
  try {
    const r = await fetch('/api/camera/toggle');
    const d = await r.json();
    showToast(d.enabled ? '📷 Camera turned ON' : '⏸ Camera disabled', d.enabled ? 'ok' : 'warning');
    return d.enabled;
  } catch { showToast('❌ Toggle failed', 'error'); }
}

// ── Camera reconnect ──────────────────────────────────────────────────────────
async function reconnectCamera() {
  try {
    await fetch('/api/camera/reconnect');
    showToast('🔄 Reconnect triggered — please wait…', 'info');
  } catch { showToast('❌ Reconnect failed', 'error'); }
}

// ── Recording controls ────────────────────────────────────────────────────────
let _recording = false;
async function toggleRecording() {
  try {
    const url = _recording ? '/api/camera/record/stop' : '/api/camera/record/start';
    const r   = await fetch(url);
    const d   = await r.json();
    _recording = !_recording;
    showToast(_recording ? `🔴 Recording started: ${d.file||''}` : '⏹ Recording stopped', _recording?'warning':'ok');
    updateRecordBtn();
    return _recording;
  } catch { showToast('❌ Recording error', 'error'); }
}

function updateRecordBtn() {
  const btn = document.getElementById('btn-record');
  if (!btn) return;
  btn.textContent  = _recording ? '⏹ STOP REC' : '🔴 RECORD';
  btn.className    = _recording ? 'btn btn-sm btn-danger' : 'btn btn-sm btn-warn';
}

// ── Capture button ────────────────────────────────────────────────────────────
async function doCapture(btn) {
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  try {
    const r = await fetch('/api/capture');
    const d = await r.json();
    if (d.status === 'ok') showToast(`📸 Snapshot saved! Count: ${d.count}`, 'ok');
    else showToast('❌ Camera offline', 'error');
  } catch { showToast('❌ Capture failed', 'error'); }
  finally {
    if (btn) { btn.disabled = false; btn.textContent = '📸'; }
  }
}

// ── Format number ─────────────────────────────────────────────────────────────
function fmt(n) { return n === null || n === undefined ? '—' : n; }

// ── Init on load ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  startClock();

  // Alert popup close button
  const closeBtn = document.getElementById('alert-popup-close');
  if (closeBtn) closeBtn.addEventListener('click', hideAlertPopup);
});
