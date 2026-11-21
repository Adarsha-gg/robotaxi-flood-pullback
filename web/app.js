/* Flood Pull-Back: shared page logic for the Replay (/) and Live trip (/trip) pages */
const $ = id => document.getElementById(id);
const post = async (u, b) => {   // never throws: bad responses come back as {error}
  try {
    const r = await fetch(u, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b || {})});
    const txt = await r.text(); let d = {};
    try { d = txt ? JSON.parse(txt) : {}; } catch { d = {error: txt || `HTTP ${r.status}`}; }
    if (!r.ok && !d.error) d.error = `HTTP ${r.status}`;
    return d;
  } catch (e) { return {error: String(e)}; }
};
window.addEventListener('pagehide', () => { try { navigator.sendBeacon('/api/genie/stop', '{}'); } catch {} });  // no paid Genie left running
async function waitGenieLive(isDone, tries = 45) {   // attach the live stream only once the session has frames
  for (let k = 0; k < tries && !isDone(); k++) {
    await sleep(550);
    const st = await fetch('/api/genie/status').then(r => r.json()).catch(() => ({}));
    if (st.status === 'live') { stageStream(); return true; }
  }
  return false;
}
// Space (or the ⏸ button) pauses the whole run between beats, so the presenter can take a question
let PAUSED = false;
const sleep = async ms => { await new Promise(r => setTimeout(r, ms)); while (PAUSED) await new Promise(r => setTimeout(r, 120)); };
function togglePause() {
  PAUSED = !PAUSED;
  const b = $('pauseBtn'); if (b) { b.textContent = PAUSED ? '▶' : '⏸'; b.classList.toggle('on', PAUSED); }
  document.body.classList.toggle('paused', PAUSED);
}
document.addEventListener('keydown', e => { if (e.code === 'Space' && !/INPUT|TEXTAREA|BUTTON/.test(document.activeElement?.tagName || '')) { e.preventDefault(); togglePause(); } });
const hm = t => String(t || '').slice(11, 16);
const toMin = t => +t.slice(11, 13) * 60 + +t.slice(14, 16) + (+t.slice(17, 19) || 0) / 60;
const fmt = m => String(Math.floor(m / 60) % 24).padStart(2, '0') + ':' + String(Math.floor(m % 60)).padStart(2, '0');
const title = s => String(s || '').toLowerCase().replace(/\b\w/g, c => c.toUpperCase()).replace(/ And /g, ' & ').replace(/, \d{5}$/, '').replace(/^Intersection (Of )?/i, '').replace(/, Virtual$/i, '');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const pct = v => Math.round((v || 0) * 100) + '%';
const PAD = {paddingTopLeft: [40, 100], paddingBottomRight: [40, 120]};

// ---------- map (no base-label layer: the pins name the streets that matter) ----------
const map = L.map('map', {zoomControl: false, attributionControl: false, preferCanvas: true}).setView([37.772, -122.43], 13);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {maxZoom: 16}).addTo(map);
const lay = {fast: L.layerGroup().addTo(map), route: L.layerGroup().addTo(map), haz: L.layerGroup().addTo(map),
             ev: L.layerGroup().addTo(map), fx: L.layerGroup().addTo(map), car: L.layerGroup().addTo(map)};
map.on('zoomend', () => $('map').classList.toggle('far', map.getZoom() < 14));
const legend = id => { const e = $(id); if (e) e.classList.add('show'); };

// ---------- panel: finished steps collapse to one line; one open card ----------
let current = null;
function collapse(line) { if (current) { current.remove(); current = null; } if (line && !$('steps')?.children.length) $('feed').insertAdjacentHTML('beforeend', `<div class="done"><span class="ck">✓</span><span>${line}</span></div>`); }
// step tracker (designed in Figma: Replay v2) + trip card progress
function initSteps(list) {
  $('steps').innerHTML = list.map(([h, d], i) => `<div class="st todo" id="st${i}"><div class="bd">${i + 1}</div><div><b>${esc(h)}</b><span>${esc(d)}</span></div></div>`).join('');
}
function step(i, st, detail) {
  const e = $('st' + i); if (!e) return;
  for (let k = 0; k < i && st === 'active'; k++) { const p = $('st' + k); if (p && !p.classList.contains('done')) { p.className = 'st done'; p.querySelector('.bd').textContent = '✓'; } }
  e.className = 'st ' + st; e.querySelector('.bd').textContent = st === 'done' ? '✓' : i + 1;
  if (detail != null) e.querySelector('span').innerHTML = detail;
}
const progress = f => { const p = $('prog'); if (p) p.style.width = Math.round(Math.max(0, Math.min(1, f)) * 100) + '%'; };
const etaLine = t => { const e = $('eta'); if (e) e.innerHTML = t; };
function card(k, h, p) {
  if (current) current.remove();
  $('feed').insertAdjacentHTML('beforeend', `<div class="card" id="cur"><div class="k">${k}</div><h3>${h}</h3>${p ? `<p>${p}</p>` : ''}<div id="curx"></div></div>`);
  current = $('cur'); return $('curx');
}
new MutationObserver(() => { $('feed').scrollTop = $('feed').scrollHeight; }).observe($('feed'), {childList: true, subtree: true});
const say = t => { const c = $('caption'); c.textContent = t; c.style.display = t ? 'block' : 'none'; };
const state = (t, slow) => { $('state').textContent = t; $('state').className = 'pillst ' + (slow ? 'slow' : /arrived|done/.test(t) ? 'done' : ''); };

// ---------- map marks ----------
const carIcon = () => L.divIcon({className: '', iconSize: [26, 26], iconAnchor: [13, 13],
  html: '<div style="width:26px;height:26px;border-radius:50%;background:#fff;border:3px solid #38e1ff;box-shadow:0 0 0 6px rgba(56,225,255,.2),0 0 26px #38e1ff"></div>'});
function waterPin(r, label) {
  legend('lgWater');
  L.circleMarker([r.lat, r.lon], {radius: 9, color: '#4da3ff', weight: 3, fillColor: '#4da3ff', fillOpacity: .15})
    .bindTooltip(`${esc(title(r.name))} · water on the street in ${r.n_storm_days || 0} past storms`).addTo(lay.haz);
  if (label) L.marker([r.lat, r.lon], {icon: L.divIcon({className: '', html: `<div class="pin">${esc(title(r.name))}</div>`, iconAnchor: [-14, 14]})}).addTo(lay.haz);
}
function conePin(c) {
  legend('lgCone');
  L.polyline(c.line, {color: '#ff9a3c', weight: 6, opacity: .95, dashArray: '7 5'})
    .bindTooltip(`${esc(title(c.street))} · ${esc(String(c.impact).replace(/-/g, ' '))} · permitted closure`).addTo(lay.haz);
}
function floodDot(e) {
  legend('lgFlood');
  L.circleMarker([e.lat, e.lon], {radius: 7, color: '#ff4d5e', weight: 1, fillColor: '#ff4d5e', fillOpacity: .9})
    .bindTooltip(`${hm(e.t)} · ${esc(title(e.address))} · flood reported to 311`).addTo(lay.ev);
}
function pulse(lat, lon, label) {
  lay.fx.clearLayers();
  L.marker([lat, lon], {icon: L.divIcon({className: '', iconSize: [44, 44], iconAnchor: [22, 22], html: '<div class="ring"></div>'})}).addTo(lay.fx);
  if (label) L.marker([lat, lon], {icon: L.divIcon({className: '', html: `<div class="pin">${esc(label)}</div>`, iconAnchor: [-18, 14]})}).addTo(lay.fx);
}
function fastLine(coords) {   // the fastest route, not taken: red dashes with a label
  legend('lgFast');
  L.polyline(coords, {color: '#ff4d5e', weight: 4, opacity: .9, dashArray: '2 9', lineCap: 'round'}).addTo(lay.fast);
  const m = coords[Math.floor(coords.length * .55)];
  L.marker(m, {icon: L.divIcon({className: '', html: '<div class="pin fast">Fastest route</div>', iconAnchor: [-12, 26]})}).addTo(lay.fast);
}
async function drawLine(group, coords, style, ms) {
  const pl = L.polyline([], style).addTo(group), n = coords.length, t0 = performance.now();
  while (true) { const f = Math.min(1, (performance.now() - t0) / ms); pl.setLatLngs(coords.slice(0, Math.max(2, Math.ceil(n * f)))); if (f >= 1) break; await sleep(25); }
  return pl;
}

// ---------- decision + meters ----------
const actPill = a => a === 'reroute' ? '<span class="pill p-slow">REROUTE</span>' : '<span class="pill p-go">KEEP ROUTE</span>';
function why(D) {
  return `<ul class="why">${D.reasons.slice(0, 2).map(r => `<li>${esc(r)}</li>`).join('')}</ul>
    ${D.rider_message ? `<div class="rider"><button class="play" style="display:none" title="Play to the rider">🔊</button>“${esc(D.rider_message)}”</div>` : ''}
    <p>Gemini 4 Carbon · ${((D.latency_ms || 0) / 1000).toFixed(1)} s</p>`;
}
function meters(v) {
  const col = x => x < .33 ? '#566070' : x < .66 ? 'var(--cone)' : 'var(--flood)';
  const row = (l, x) => `<div class="m"><span>${l}</span><div class="t"><div style="width:${pct(x)};background:${col(x || 0)}"></div></div><b>${pct(x)}</b></div>`;
  return `<div class="meters">${row('Water across the lane', v.lane_covered)}${row('Up to tire sidewall', v.p_tire_or_worse)}${row('Lane edges hidden', v.edges_hidden)}${v.lane_closed != null ? row('Lane closed / cones', v.lane_closed) : ''}</div>`;
}
const verdictPill = a => `<span class="pill ${a === 'avoid' ? 'p-stop' : a === 'slow' ? 'p-slow' : 'p-go'}">${String(a || '').toUpperCase()}</span>`;

// ---------- the Genie stage (hero) ----------
function stageOpen(street, when, seedSrc, seedLabel, fc) {
  const s = $('stage');
  s.innerHTML = `<div class="eb">Genie 4 · simulating the forecast at arrival</div><h2>${esc(street)} at ${esc(when)}</h2>
    <div class="fcline" id="simFc">${fc ? esc(fc) : ''}</div>
    <div class="frame"><img id="simImg" onerror="this.style.visibility='hidden'" onload="this.style.visibility='visible'">
      <div class="inset"><img id="seedImg" ${seedSrc ? `src="${seedSrc}"` : ''} onerror="this.style.visibility='hidden'"><div id="seedC">${esc(seedLabel || 'finding the nearest real image…')}</div></div>
      <div class="tag live" id="simTag">LIVE</div>
      <div class="stctl"><button onclick="genieKey('key_a')">◀</button><button onclick="genieKey('key_w')">▲ Drive</button><button onclick="genieKey('key_d')">▶</button></div></div>
    <div class="verdict" id="simV"></div>`;
  s.style.display = 'block'; requestAnimationFrame(() => s.classList.add('on')); say('');
}
function stageFc(t) { if ($('simFc')) $('simFc').textContent = t; }
function stageStream() { if ($('simImg')) $('simImg').src = '/api/genie/stream?ts=' + Date.now(); }
function stageSeed(src, label) { if ($('seedImg')) { $('seedImg').src = src; $('seedImg').style.visibility = 'visible'; } if ($('seedC')) $('seedC').textContent = label; }
function stageResult(frame, when, v, secs) {
  if (frame && $('simImg')) $('simImg').src = '/' + frame;
  if ($('simTag')) { $('simTag').className = 'tag'; $('simTag').textContent = 'SIMULATED ' + when; }
  if ($('simV') && v) { $('simV').innerHTML = `<div class="line">${verdictPill(v.action)} ${esc(v.depth_label || '')}</div>${meters(v)}`; $('simV').classList.add('on'); }
}
async function stageClose() { const s = $('stage'); s.classList.remove('on'); await sleep(260); s.style.display = 'none'; s.innerHTML = ''; }

// Genie stage: drive the live world model (key_w / key_a / key_d)
function genieKey(key) { post('/api/genie/key', {action: 'key_down', key}); setTimeout(() => post('/api/genie/key', {action: 'key_up', key}), 700); }
// rider voice: Gemini TTS reads Carbon's rider message
async function riderVoice(text) {
  const v = await post('/api/voice', {text});
  const b = document.querySelector('.rider .play');
  if (v.path && b) { b.style.display = ''; b.onclick = () => new Audio('/' + v.path + '?t=' + Date.now()).play(); }
}

// ---------- fleet agent (Antigravity Managed Agent): this car's simulation -> an avoid zone for the whole fleet ----------
const TOOL_LABEL = {get_cell_history: 'flood history', get_forecast: 'forecast', judge_frame: 're-check image', estimate_fleet_detour: 'fleet detour cost', propose_zone: 'zone for the fleet'};
async function fleetAgent(stepIdx, inc, alive) {
  const st = await post('/api/fleet/start', inc); if (st.error) { step(stepIdx, 'done', 'agent unavailable'); return; }
  step(stepIdx, 'active', 'Antigravity Managed Agent · starting…');
  for (let k = 0; k < 90 && alive(); k++) {
    await sleep(1000);
    const f = await fetch('/api/fleet/status').then(r => r.json()).catch(() => null);
    if (!f || f.run !== st.run) return;
    const tools = f.steps.map(s => TOOL_LABEL[s.tool] || s.tool);
    if (tools.length) step(stepIdx, 'active', 'Agent tools: ' + tools.join(' → '));
    if (f.done) {
      const z = f.zone;
      if (!z || !z.polygon) { step(stepIdx, 'done', f.error ? 'agent unavailable' : 'no zone needed'); return; }
      legend('lgZone');
      L.polygon(z.polygon.map(p => p.length === 2 && Math.abs(p[0]) > 90 ? [p[1], p[0]] : p), {color: '#b18cff', weight: 2, fillColor: '#b18cff', fillOpacity: .18, dashArray: '4 4'})
        .bindTooltip(`Fleet avoid zone · ${hm(z.start)}–${hm(z.end)}`).addTo(lay.fx2 || (lay.fx2 = L.layerGroup().addTo(map)));
      step(stepIdx, 'done', `Fleet avoids ${esc(title(z.name || ''))} until ${hm(z.end)}`);
      say(`Fleet agent: ${z.fleet_notice || 'avoid zone sent to every robotaxi'}`);
      return z;
    }
  }
}
