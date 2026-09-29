/* ==========================================================================
   Vitals mockup — screens, navigation, motion
   ========================================================================== */

const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
const EASE_SHEET = 'cubic-bezier(.32,.72,0,1)';
const EASE_OUT = 'cubic-bezier(.16,1,.3,1)';

/* Icons — drawn for Vitals. 24 grid, 1.6 stroke, round joins.
   .ds = the form's own fill (quiet, fuller when active), .d2 = a solid accent part. */
const I = {
  // sun rising over the horizon: the day, not generic weather
  today: '<path class="ds" d="M7 17a5 5 0 0 1 10 0"/><path d="M3 17h18M8.5 20.5h7M12 6.2v2.3M5.4 9.9l1.6 1.6M18.6 9.9 17 11.5"/>',
  heart: '<path class="ds" d="M12 20c-2.8-2.1-8.5-6.2-8.5-10.9C3.5 6.4 5.5 4.5 8 4.5c1.7 0 3.1.9 4 2.3.9-1.4 2.3-2.3 4-2.3 2.5 0 4.5 1.9 4.5 4.6 0 4.7-5.7 8.8-8.5 10.9z"/>',
  // bathroom scale with its readout window
  scale: '<rect class="ds" x="4" y="4" width="16" height="16" rx="4.5"/><rect class="d2" x="8.5" y="7.4" width="7" height="3.4" rx="1.2"/><path d="M9 16.3h.01M15 16.3h.01"/>',
  // recovery = the night: crescent + a small star
  pulse: '<path class="ds" d="M19.5 14.2A7.8 7.8 0 1 1 9.8 4.5a6.2 6.2 0 0 0 9.7 9.7z"/><path d="M17 3.8v2.6M15.7 5.1h2.6"/>',
  dumbbell: '<rect class="ds" x="5" y="6.5" width="3.3" height="11" rx="1.3"/><rect class="ds" x="15.7" y="6.5" width="3.3" height="11" rx="1.3"/><path d="M8.3 12h7.4M2.8 9.6v4.8M21.2 9.6v4.8"/>',
  // an apple, not a bowl
  bowl: '<path class="ds" d="M12 8.2c-1.2-.8-2.5-1.1-3.8-.9C5.7 7.7 4.3 10 4.5 12.8c.3 4 2.8 7.7 5.2 7.7.9 0 1.5-.4 2.3-.4s1.4.4 2.3.4c2.4 0 4.9-3.7 5.2-7.7.2-2.8-1.2-5.1-3.7-5.5-1.3-.2-2.6.1-3.8.9z"/><path d="M12 8.2c0-2 .9-3.5 2.6-4.5"/>',
  // injector pen — what semaglutide actually comes in
  syringe: '<g transform="rotate(-45 12 12)"><rect class="ds" x="5.2" y="9.3" width="10.6" height="5.4" rx="2.2"/><path d="M15.8 10.4h1.9a.8.8 0 0 1 .8.8v1.6a.8.8 0 0 1-.8.8h-1.9M5.2 12H2.6M18.5 12h2.6M8.6 12h3.2"/></g>',
  // test tube with a sample in it
  flask: '<g transform="rotate(35 12 12)"><path d="M9.3 3.6h5.4M10.2 3.6v13.1a1.8 1.8 0 0 0 3.6 0V3.6"/><path class="d2" d="M10.2 11.2h3.6v5.5a1.8 1.8 0 0 1-3.6 0z"/></g>',
  // markers rubric: a drop of blood
  drop: '<path class="ds" d="M12 3.5c3 3.6 6 7.1 6 10.4a6 6 0 0 1-12 0c0-3.3 3-6.8 6-10.4z"/><path d="M9.2 14.2a2.9 2.9 0 0 0 2.6 2.8"/>',
  dna: '<path d="M8 3c0 4.5 8 4.5 8 9s-8 4.5-8 9M16 3c0 4.5-8 4.5-8 9s8 4.5 8 9"/><path d="M10 6.6h4M10 17.4h4M11.2 9.4h1.6M11.2 14.6h1.6"/>',
  // two-tone capsule
  pill: '<g transform="rotate(-45 12 12)"><rect x="4" y="8.5" width="16" height="7" rx="3.5"/><path class="d2" d="M12 8.5h4.5a3.5 3.5 0 0 1 0 7H12z"/><path d="M12 8.5v7"/></g>',
  // pump bottle
  skincare: '<path class="ds" d="M9 10h6a1.5 1.5 0 0 1 1.5 1.5V19a1.5 1.5 0 0 1-1.5 1.5H9A1.5 1.5 0 0 1 7.5 19v-7.5A1.5 1.5 0 0 1 9 10z"/><path d="M10.5 10V7.5h3V10M12 7.5v-3h3.6M10 14.5h4"/>',
  doc: '<path class="ds" d="M6.5 3.5H14l4 4v11.5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 5 19V5a1.5 1.5 0 0 1 1.5-1.5z"/><path d="M14 3.5v4h4M8.5 12h7M8.5 15.5h4.5"/>',
  chart: '<path d="M4 4v13.5A2.5 2.5 0 0 0 6.5 20H20M7.5 15.5l3.5-4 3 2.5 3.8-4.6"/><circle class="d2" cx="18.8" cy="8.4" r="1.7"/>',
  timeline: '<path d="M6.5 3.5v1.7M6.5 8.8v1.4M6.5 13.8v1.4M6.5 18.8v1.7M11 7h8.5M11 12h6M11 17h7.5"/><circle class="ds" cx="6.5" cy="7" r="1.8"/><circle class="ds" cx="6.5" cy="12" r="1.8"/><circle class="ds" cx="6.5" cy="17" r="1.8"/>',
  grid: '<rect x="4" y="4" width="6.5" height="6.5" rx="2"/><rect class="ds" x="13.5" y="4" width="6.5" height="6.5" rx="2"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="2"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  x: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  chevL: '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
  chevR: '<path d="M9.5 5.5 16 12l-6.5 6.5"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  sync: '<path d="M19 12a7 7 0 0 1-12 4.9M5 12a7 7 0 0 1 12-4.9"/><path d="M17.3 3.6v3.6h-3.6M6.7 20.4v-3.6h3.6"/>',
  upload: '<path d="M12 15V4.5M7.8 8.7 12 4.5l4.2 4.2M4.5 14.5v3A2.5 2.5 0 0 0 7 20h10a2.5 2.5 0 0 0 2.5-2.5v-3"/>',
  sliders: '<path d="M4 7.5h8M16 7.5h4M4 16.5h3M11 16.5h9"/><circle class="ds" cx="14" cy="7.5" r="2"/><circle class="ds" cx="9" cy="16.5" r="2"/>',
  // for the doctor: a stethoscope
  clipboard: '<path d="M6 3.5v4.8a4 4 0 0 0 8 0V3.5M10 12.3v1.9a4.8 4.8 0 0 0 9.6 0v-1.5"/><circle class="ds" cx="19.6" cy="10.6" r="2.1"/>',
  info: '<circle class="ds" cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/>',
  warn: '<path class="ds" d="M10.3 4.6 3.4 17a2 2 0 0 0 1.7 3h13.8a2 2 0 0 0 1.7-3L13.7 4.6a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4M12 16.8h.01"/>',
  block: '<circle class="ds" cx="12" cy="12" r="8.5"/><path d="M12 7.5v5.5M12 16.3h.01"/>',
  eye: '<path d="M2.5 12c2.2-4 5.4-6 9.5-6s7.3 2 9.5 6c-2.2 4-5.4 6-9.5 6s-7.3-2-9.5-6z"/><circle class="ds" cx="12" cy="12" r="2.8"/>',
  cal: '<rect x="4" y="5.5" width="16" height="14.5" rx="3"/><path d="M4 10h16M8.5 3.5V7M15.5 3.5V7"/><rect class="d2" x="13" y="13" width="3.6" height="3.6" rx="1"/>',
  down: '<path d="M12 5v13.5M6.5 13 12 18.5 17.5 13"/>',
  up: '<path d="M12 19V5.5M6.5 11 12 5.5l5.5 5.5"/>',
  // tape measure
  ruler: '<circle class="ds" cx="10" cy="12" r="6.5"/><circle cx="10" cy="12" r="2"/><path d="M16.5 12H21v3.5h-4.5"/>',
};
const ic = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[n]}</svg>`;

/* ---------- Navigation model — one registry, every surface reads it ---------- */
const RUBRICS = [
  { id: 'health', name: 'Здоровье', icon: 'heart', items: [['weight', 'Вес', 'scale'], ['recovery', 'Восстановление', 'pulse'], ['workouts', 'Тренировки', 'dumbbell'], ['nutrition', 'Питание', 'bowl']] },
  { id: 'markers', name: 'Маркеры', icon: 'drop', items: [['glp1', 'GLP-1', 'syringe'], ['labs', 'Анализы', 'flask'], ['genetics', 'Генетика', 'dna']] },
  { id: 'life', name: 'Образ жизни', icon: 'pill', items: [['supplements', 'Добавки', 'pill'], ['skincare', 'Уход за кожей', 'skincare']] },
  { id: 'journal', name: 'Журнал', icon: 'doc', items: [['timeline', 'Хронология', 'timeline'], ['reports', 'Отчёты', 'doc'], ['charts', 'Графики', 'chart']] },
];
const BUILT = new Set(['today', 'weight', 'recovery', 'glp1', 'labs', 'more']);
const TITLE = { today: 'Сегодня', more: 'Ещё' };
RUBRICS.forEach(r => r.items.forEach(([id, t]) => TITLE[id] = t));
const rubricOf = (id) => RUBRICS.find(r => r.items.some(i => i[0] === id));
const TAB_ROOT = { today: 'today', health: 'weight', markers: 'glp1', more: 'more' };
function tabOf(id) {
  if (id === 'today') return 'today';
  if (id === 'more') return 'more';
  const r = rubricOf(id); if (!r) return 'more';
  return r.id === 'health' ? 'health' : r.id === 'markers' ? 'markers' : 'more';
}

/* ---------- Small helpers ---------- */
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const esc = (s) => String(s);
const DIG = '0123456789'.split('').map(d => `<span>${d}</span>`).join('');
function odoInner(str, zero = false) {
  return [...str].map(ch => /\d/.test(ch)
    ? `<span class="odo-d"><span class="odo-s" style="transform:translateY(${zero ? 0 : -ch * 1.1}em)">${DIG}</span></span>`
    : `<span class="odo-c">${ch}</span>`).join('');
}
function odo(str, zero = false) { return `<span class="odo${zero ? ' pre' : ''}" data-odo="${str}">${odoInner(str, zero)}</span>`; }
function setOdo(node, str, stagger = 0) {
  if (!node) return;
  const old = node.dataset.odo;
  const shape = (s) => s.replace(/\d/g, '0');
  if (!old || shape(old) !== shape(str)) {
    // Structure changed (e.g. 9,9 → 10,0): rebuild at the old digits' zero, then roll.
    node.innerHTML = odoInner(str, true);
    node.dataset.odo = str;
    requestAnimationFrame(() => requestAnimationFrame(() => setOdo(node, str, stagger)));
    return;
  }
  node.dataset.odo = str;
  let i = 0;
  node.querySelectorAll('.odo-s').forEach((s, k) => {
    const ch = str.replace(/[^\d]/g, '')[k];
    s.style.transitionDelay = stagger ? `${i++ * stagger}ms` : '';
    s.style.transform = `translateY(${-ch * 1.1}em)`;
  });
}
const words = (html, base = 0, step = 22) => {
  let i = 0;
  return html.replace(/(<[^>]+>)|([^ \n<]+)/g, (m, tag, w) => tag ? tag : `<span class="w" style="animation-delay:${base + (i++) * step}ms">${w}</span>`);
};
const pct = (v, a, b) => clamp((v - a) / (b - a) * 100, 0, 100);

function rbar({ v, lo, hi, min, max, prev, tone }) {
  const ref = lo !== hi ? `<span class="ref" style="left:${pct(lo, min, max)}%;width:${pct(hi, min, max) - pct(lo, min, max)}%"></span>` : '';
  let con = '';
  if (prev != null) {
    const a = pct(prev, min, max), b = pct(v, min, max);
    const col = tone === 'good' ? 'var(--good)' : tone === 'bad' ? 'var(--bad-strong)' : 'var(--muted)';
    con = `<span class="con" style="left:${Math.min(a, b)}%;width:${Math.abs(b - a)}%;background:${col};opacity:.55"></span><span class="prev" style="left:${a}%"></span>`;
  }
  return `<div class="rbar"><span class="track"></span>${ref}${con}<span class="pt ${tone || ''}" style="left:${pct(v, min, max)}%"></span></div>`;
}

/* ==========================================================================
   Charts (SVG, drawn at the real pixel width of their box)
   ========================================================================== */
function linePath(pts) { return pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(''); }
function smoothPath(pts) {
  if (pts.length < 3) return linePath(pts);
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const t = .18;
    d += `C${(p1[0] + (p2[0] - p0[0]) * t).toFixed(1)} ${(p1[1] + (p2[1] - p0[1]) * t).toFixed(1)} ${(p2[0] - (p3[0] - p1[0]) * t).toFixed(1)} ${(p2[1] - (p3[1] - p1[1]) * t).toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}
function niceTicks(a, b, n) {
  const span = b - a, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0) || mag * 10;
  const out = []; for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function weightChart(box, { range = '3m', intro = false, phone = true }) {
  const W = box.clientWidth; if (!W) return;
  const H = phone ? 224 : 300;
  const days = range === '1m' ? 30 : range === '3m' ? 92 : 999;
  const from = new Date(Math.max(new Date(2026, 3, 1), addDays(TODAY, -days)));
  const ma = DATA.weightMA.filter(p => p.date >= from);
  const pts = DATA.weights.filter(p => p.date >= from);
  const L = 0, R = 36, T = 26, B = 26;
  const x0 = from.getTime(), x1 = TODAY.getTime();
  const all = [...ma.map(p => p.w), ...pts.map(p => p.w)];
  let lo = Math.floor(Math.min(...all) - .4), hi = Math.ceil(Math.max(...all) + .4);
  const X = (d) => L + (d.getTime() - x0) / (x1 - x0) * (W - L - R);
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const yt = niceTicks(lo, hi, phone ? 3 : 4);
  const nx = phone ? 3 : 6;
  const xt = Array.from({ length: nx + 1 }, (_, i) => new Date(x0 + (x1 - x0) * i / nx));

  let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
  s += `<defs><linearGradient id="wg${box.dataset.cid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F4F0F6" stop-opacity=".07"/><stop offset="1" stop-color="#F4F0F6" stop-opacity="0"/></linearGradient></defs>`;
  // dose phases
  DATA.PHASES.forEach((ph, i) => {
    const a = X(new Date(Math.max(ph.from, from))), b = X(new Date(Math.min(ph.to, TODAY)));
    if (b <= a) return;
    s += `<rect x="${a}" y="${T - 10}" width="${b - a}" height="${H - T - B + 10}" fill="#BCA4DC" fill-opacity="${i ? .05 : .03}"/>`;
    s += `<line x1="${a}" x2="${a}" y1="${T - 10}" y2="${H - B}" stroke="#BCA4DC" stroke-opacity=".35" stroke-dasharray="2 3"/>`;
    if (b - a > 64) s += `<text x="${a + 7}" y="${T + 2}" class="ax" style="fill:var(--violet)">${ph.label}</text>`;
  });
  yt.forEach(v => { s += `<line class="grid" x1="${L}" x2="${W - R + 6}" y1="${Y(v)}" y2="${Y(v)}"/><text class="ax" x="${W}" y="${Y(v) + 4}" text-anchor="end">${fmt(v, v % 1 ? 1 : 0)}</text>`; });
  xt.forEach((d, i) => { s += `<text class="ax" x="${X(d)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === nx ? 'end' : 'middle'}">${dShort(d)}</text>`; });
  const mp = ma.map(p => [X(p.date), Y(p.w)]);
  const area = smoothPath(mp) + `L${mp[mp.length - 1][0]} ${H - B}L${mp[0][0]} ${H - B}Z`;
  s += `<path class="late" d="${area}" fill="url(#wg${box.dataset.cid})"/>`;
  s += `<g class="late">${pts.map(p => `<circle cx="${X(p.date).toFixed(1)}" cy="${Y(p.w).toFixed(1)}" r="${phone ? 2 : 2.4}" fill="#857B93"/>`).join('')}</g>`;
  s += `<path class="draw" pathLength="1" d="${smoothPath(mp)}" fill="none" stroke="#F4F0F6" stroke-width="2" stroke-linecap="round"/>`;
  const last = mp[mp.length - 1];
  s += `<g class="late"><circle class="now-ring" cx="${last[0]}" cy="${last[1]}" r="4" fill="#F5A623"/><circle cx="${last[0]}" cy="${last[1]}" r="4.5" fill="#F5A623" stroke="#221E27" stroke-width="2"/></g>`;
  s += `</svg><div class="scrub"></div><div class="scrub-dot"></div><div class="tip"></div>`;
  box.innerHTML = s;
  box.classList.toggle('intro', intro);
  box._scrub = ma.map((p, i) => ({ x: mp[i][0], y: mp[i][1], label: `${WD[p.date.getDay()]}, ${dShort(p.date)}`, val: `${fmt(p.w)} кг`, sub: (pts.find(q => daysBetween(q.date, p.date) === 0) ? `взвешивание ${fmt(pts.find(q => daysBetween(q.date, p.date) === 0).w)}` : 'тренд 7 дней') }));
  box._w = W;
}

function hypChart(box, { intro }) {
  const W = box.clientWidth; if (!W) return;
  const H = 132, T = 4, B = 22, L = 64;
  const rows = [['Бодрств.', 'var(--bad)'], ['REM', 'var(--violet)'], ['Лёгкий', 'var(--cool)'], ['Глубокий', 'var(--deep)']];
  const rh = (H - T - B) / 4, n = DATA.hyp.length, bw = (W - L) / n;
  let s = `<svg width="${W}" height="${H}">`;
  rows.forEach(([l], i) => {
    s += `<text class="ax" x="0" y="${T + rh * i + rh / 2 + 4}">${l}</text>`;
    s += `<line class="grid" x1="${L}" x2="${W}" y1="${T + rh * i + rh}" y2="${T + rh * i + rh}" stroke-dasharray="2 4"/>`;
  });
  // step outline
  let d = '';
  DATA.hyp.forEach((st, i) => { const y = T + rh * st + rh / 2; d += (i ? `L${L + i * bw} ${y}` : `M${L} ${y}`) + `L${L + (i + 1) * bw} ${y}`; });
  s += `<path class="draw" pathLength="1" d="${d}" fill="none" stroke="#F4F0F6" stroke-opacity=".28" stroke-width="1"/>`;
  // blocks
  let i = 0; let seg = '';
  while (i < n) {
    let j = i; while (j < n && DATA.hyp[j] === DATA.hyp[i]) j++;
    const st = DATA.hyp[i];
    seg += `<rect x="${(L + i * bw + .5).toFixed(1)}" y="${(T + rh * st + 4).toFixed(1)}" width="${Math.max(1, (j - i) * bw - 1).toFixed(1)}" height="${(rh - 8).toFixed(1)}" rx="3" fill="${rows[st][1]}" fill-opacity="${st === 3 ? .95 : .8}"/>`;
    i = j;
  }
  s += `<g class="late">${seg}</g>`;
  ['00:00', '02:00', '04:00', '06:00'].forEach((t, k) => {
    const mins = (k * 120) + 20; // from 23:40
    s += `<text class="ax" x="${L + mins / 5 * bw}" y="${H - 5}" text-anchor="middle">${t}</text>`;
  });
  s += `</svg>`;
  box.innerHTML = s; box.classList.toggle('intro', intro);
}

function markerChart(box, m, { intro, phone }) {
  const W = box.clientWidth; if (!W) return;
  const H = phone ? 150 : 190, T = 18, B = 24, L = 8, R = 44;
  const vals = m.hist.map(h => h[1]);
  let lo = Math.min(m.lo, ...vals), hi = Math.max(m.hi === m.lo ? m.hi : m.hi, ...vals);
  const pad = (hi - lo) * .12; lo = Math.max(m.min, lo - pad); hi = Math.min(m.max, hi + pad);
  if (m.id === 'vitd') { lo = 10; hi = 60; }
  if (m.id === 'tg') { lo = 60; hi = 190; }
  if (m.id === 'fer') { lo = 20; hi = 160; }
  const x0 = m.hist[0][0].getTime(), x1 = m.hist[m.hist.length - 1][0].getTime();
  const X = (d) => L + 18 + (d.getTime() - x0) / (x1 - x0) * (W - L - R - 36);
  const Y = (v) => T + (1 - (clamp(v, lo, hi) - lo) / (hi - lo)) * (H - T - B);
  let s = `<svg width="${W}" height="${H}">`;
  const ry0 = Y(Math.min(m.hi, hi)), ry1 = Y(Math.max(m.lo, lo));
  s += `<rect x="${L}" y="${ry0}" width="${W - L - R + 8}" height="${Math.max(0, ry1 - ry0)}" rx="6" fill="#CEC6D7" fill-opacity=".07"/><text class="ax" x="${L + 10}" y="${ry0 + 16}">норма</text>`;
  if (m.lo > lo) s += `<line x1="${L}" x2="${W - R + 8}" y1="${Y(m.lo)}" y2="${Y(m.lo)}" stroke="#CEC6D7" stroke-opacity=".28" stroke-dasharray="3 4"/><text class="ax" x="${W}" y="${Y(m.lo) + 4}" text-anchor="end">${fmt(m.lo, m.d || 0)}</text>`;
  if (m.hi < hi) s += `<line x1="${L}" x2="${W - R + 8}" y1="${Y(m.hi)}" y2="${Y(m.hi)}" stroke="#CEC6D7" stroke-opacity=".28" stroke-dasharray="3 4"/><text class="ax" x="${W}" y="${Y(m.hi) + 4}" text-anchor="end">${fmt(m.hi, m.d || 0)}</text>`;
  const pts = m.hist.map(h => [X(h[0]), Y(h[1])]);
  s += `<path class="draw" pathLength="1" d="${linePath(pts)}" fill="none" stroke="#F4F0F6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
  m.hist.forEach((h, i) => {
    const out = h[1] < m.lo || h[1] > m.hi, last = i === m.hist.length - 1;
    s += `<g class="late"><circle cx="${pts[i][0]}" cy="${pts[i][1]}" r="${last ? 5 : 3.5}" fill="${out ? '#FF8469' : '#F4F0F6'}" stroke="#221E27" stroke-width="2"/>`;
    s += `<text x="${pts[i][0]}" y="${pts[i][1] - 11}" text-anchor="middle" style="font:600 12px var(--f-display);fill:${out ? 'var(--bad-strong)' : 'var(--fg-2)'};font-variant-numeric:tabular-nums">${fmt(h[1], m.d || 0)}</text>`;
    s += `<text class="ax" x="${pts[i][0]}" y="${H - 5}" text-anchor="middle">${MONTHS_S[h[0].getMonth()]}</text></g>`;
  });
  s += `</svg>`;
  box.innerHTML = s; box.classList.toggle('intro', intro);
}

function doseChart(box, { intro, phone }) {
  const W = box.clientWidth; if (!W) return;
  const H = phone ? 170 : 210, T = 20, B = 24, L = 2, R = 38;
  const from = new Date(2026, 5, 29);
  const x0 = from.getTime(), x1 = TODAY.getTime();
  const X = (d) => L + (d.getTime() - x0) / (x1 - x0) * (W - L - R);
  const Yd = (v) => T + (1 - v / .6) * (H - T - B);
  const ma = DATA.weightMA.filter(p => p.date >= from);
  const wl = 85, wh = 95; const Yw = (v) => T + (1 - (v - wl) / (wh - wl)) * (H - T - B);
  let s = `<svg width="${W}" height="${H}">`;
  [0.25, 0.5].forEach(v => { s += `<line class="grid" x1="${L}" x2="${W - R + 4}" y1="${Yd(v)}" y2="${Yd(v)}"/><text class="ax" x="${W}" y="${Yd(v) + 4}" text-anchor="end" style="fill:var(--violet)">${fmt(v, 2)}</text>`; });
  s += `<line class="grid" x1="${L}" x2="${W - R + 4}" y1="${H - B}" y2="${H - B}"/>`;
  const a = X(DATA.PHASES[0].from), b = X(DATA.PHASES[1].from), e = X(TODAY);
  const step = `M${L} ${H - B}L${a} ${H - B}L${a} ${Yd(.25)}L${b} ${Yd(.25)}L${b} ${Yd(.5)}L${e} ${Yd(.5)}`;
  s += `<path class="draw" pathLength="1" d="${step}" fill="none" stroke="#BCA4DC" stroke-width="2" stroke-linejoin="round"/>`;
  s += `<path class="draw" pathLength="1" d="${smoothPath(ma.map(p => [X(p.date), Yw(p.w)]))}" fill="none" stroke="#F4F0F6" stroke-opacity=".75" stroke-width="1.75"/>`;
  const lw = ma[ma.length - 1];
  s += `<g class="late"><text x="${X(lw.date) - 4}" y="${Yw(lw.w) + 22}" text-anchor="end" style="font:600 12px var(--f-display);fill:var(--fg-2);font-variant-numeric:tabular-nums">${fmt(lw.w)} кг</text><text x="${L + 4}" y="${Yw(ma[0].w) - 10}" style="font:600 12px var(--f-display);fill:var(--muted);font-variant-numeric:tabular-nums">${fmt(ma[0].w)} кг</text>`;
  s += `<circle class="now-ring" cx="${X(lw.date)}" cy="${Yw(lw.w)}" r="4" fill="#F5A623"/><circle cx="${X(lw.date)}" cy="${Yw(lw.w)}" r="4.5" fill="#F5A623" stroke="#221E27" stroke-width="2"/></g>`;
  [new Date(2026, 6, 1), new Date(2026, 7, 1), new Date(2026, 8, 1)].forEach(d => { s += `<text class="ax" x="${X(d)}" y="${H - 5}" text-anchor="middle">${MONTHS_S[d.getMonth()]}</text>`; });
  s += `</svg>`;
  box.innerHTML = s; box.classList.toggle('intro', intro);
}

function bodyMap() {
  const last = {}; DATA.injections.forEach(j => { if (!last[j.site]) last[j.site] = j.date; });
  const SITES = { 'Плечо Л': [44, 64], 'Плечо П': [106, 64], 'Живот Л': [64, 104], 'Живот П': [86, 104], 'Бедро Л': [62, 150], 'Бедро П': [88, 150] };
  const order = Object.keys(SITES).sort((a, b) => (last[a] || 0) - (last[b] || 0));
  let s = `<svg viewBox="0 0 150 190" width="150" height="190" fill="none" stroke="#433C4D" stroke-width="1.5">`;
  s += `<circle cx="75" cy="20" r="12"/><path d="M52 40c6-5 14-7 23-7s17 2 23 7l12 30-8 3-9-22v44c0 4 1 8 2 12l-2 70h-12l-4-62h-4l-4 62H57l-2-70c1-4 2-8 2-12V51l-9 22-8-3z"/>`;
  Object.entries(SITES).forEach(([name, [x, y]]) => {
    const d = last[name]; const age = d ? daysBetween(d, TODAY) : 99;
    if (name === order[0]) s += `<circle cx="${x}" cy="${y}" r="9" stroke="#BCA4DC" stroke-dasharray="3 3"/>`;
    else if (age <= 3) s += `<circle cx="${x}" cy="${y}" r="7" fill="#BCA4DC" stroke="none"/><circle cx="${x}" cy="${y}" r="11" stroke="#BCA4DC" stroke-opacity=".35"/>`;
    else s += `<circle cx="${x}" cy="${y}" r="5.5" fill="#BCA4DC" fill-opacity="${clamp(.7 - age / 40, .15, .6)}" stroke="none"/>`;
  });
  s += `</svg>`;
  return { svg: s, last, suggest: order[0] };
}

/* ==========================================================================
   Screen templates
   ========================================================================== */
function topbar(title, { back } = {}) {
  return `<div class="topbar">
    <div class="topbar-l">${back ? `<button class="back" data-back>${ic('chevL')}<span>${back}</span></button>` : ''}</div>
    <div class="topbar-title">${title}</div>
    <div class="topbar-r"></div>
  </div>`;
}
function mast(id, { actions = '' } = {}) {
  const r = rubricOf(id);
  return `<header class="mast">
    <div class="kicker"><span class="crumb">${r.name}</span></div>
    <div class="mast-actions">${actions}</div>
    <nav class="chips">${r.items.map(([cid, t]) => `<a href="#" class="chip${cid === id ? ' on' : ''}${BUILT.has(cid) ? '' : ' soon'}" data-go="${cid}" data-chip>${t}</a>`).join('')}<i class="ink"></i></nav>
  </header>`;
}
const secH = (h, meta = '') => `<div class="sec-h"><h2>${h}</h2>${meta}</div>`;

/* ---------- Today ---------- */
function scrToday(ctx) {
  const w = DATA.lastW.w;
  const nar = `Вес ${fmt(w)} и уходит на 0,6 в неделю. <em>Сон 82, но HRV третью ночь ниже нормы.</em>`;
  const n0 = DATA.nights[DATA.nights.length - 1];
  const changes = DATA.weekChanges.map(c => {
    const dlt = c.to - c.from; const tone = Math.sign(dlt) * c.better > 0 ? 'good' : 'bad';
    return `<a href="#" class="row dumb" data-go="${c.go}">
      <div><div class="t">${c.name}</div><div class="m num">${fmt(c.from)} → ${fmt(c.to)}${c.unit ? ' ' + c.unit : ''}</div></div>
      ${rbar({ v: c.to, prev: c.from, lo: c.lo, hi: c.hi, min: c.min, max: c.max, tone })}
      <div class="v ${tone}">${fmtS(dlt)}</div>
    </a>`;
  }).join('');
  const feed = DATA.feed.map(f => `<div class="feed-row"><span class="time">${f.time}</span><span class="rail-dot"><span class="dot ${f.dot}"></span></span><div><div class="tx">${f.text}</div><div class="dt">${f.detail}</div></div></div>`).join('');
  const g = DATA.goal, done = g.start - w, total = g.start - g.target, gp = done / total * 100;
  const intro = ctx.intro;
  const figAnim = (v) => odo(v, intro);
  return `
  ${topbar('Сегодня')}
  <div class="today-top">
    <div class="kicker">Вторник, 29 сентября <span class="sep"></span> <span class="num">${DATA.now}</span></div>
    <div class="sync"><span><i class="dot good"></i>Garmin · 07:02</span><span><i class="dot good"></i>Hevy · вс</span></div>
  </div>
  <h1 class="narr${intro ? ' intro' : ''}">${intro ? words(nar, 60, 26) : nar}</h1>
  <div class="figs today-figs">
    <a href="#" class="f f-weight" data-go="weight" data-shared>
      <div class="fig-weight"><div class="fw-v" data-fig="weight">${figAnim(fmt(w))}<span class="u">кг</span></div></div>
      <div class="f-l">Вес <span class="delta good" style="margin-left:6px;vertical-align:1px">${ic('down')}0,6 кг/нед</span></div>
      ${ic('chevR').replace('<svg', '<svg class="go"')}
    </a>
    <a href="#" class="f" data-go="recovery"><div class="f-v">${figAnim('82')}</div><div class="f-l">Сон</div><div class="f-s">7 ч 34 мин</div>${ic('chevR').replace('<svg', '<svg class="go"')}</a>
    <a href="#" class="f" data-go="recovery"><div class="f-v bad">${figAnim(String(n0.hrv))}<span class="u">мс</span></div><div class="f-l">HRV</div><div class="f-s bad">ниже нормы 50–58</div>${ic('chevR').replace('<svg', '<svg class="go"')}</a>
    <a href="#" class="f" data-go="recovery"><div class="f-v">${figAnim('94')}</div><div class="f-l">Body Battery</div><div class="f-s">+58 за ночь</div>${ic('chevR').replace('<svg', '<svg class="go"')}</a>
    <a href="#" class="f" data-go="nutrition"><div class="f-v">${figAnim(String(DATA.eaten))}<span class="u">ккал</span></div><div class="f-l">Съедено</div><div class="f-s">из ${fmtI(DATA.kcalTarget)}</div>${ic('chevR').replace('<svg', '<svg class="go"')}</a>
  </div>

  <div class="grid">
    <div class="c7">
      <section class="sec o2">
        ${secH('Что изменилось за неделю', '<span class="meta">к прошлой неделе · коридор нормы</span>')}
        <div class="rows">${changes}</div>
      </section>
      <section class="sec o3">
        ${secH('День', `<span class="meta">${DATA.feed.length} записи</span>`)}
        <div class="feed" data-feed>${feed}</div>
      </section>
    </div>
    <div class="c5">
      <div class="panel today-log sec o0" data-logform>
        <div class="panel-h"><h3>Вес сегодня</h3><span class="sub">утром ${fmt(w)} · 07:55</span></div>
        ${stepper(w)}
        ${conflictBox()}
        <button class="btn w" data-save="weight" style="margin-top:12px">Сохранить вес</button>
        <div class="qchips" style="margin-top:12px">
          <button class="qchip" data-log="meal">${ic('bowl')}Еда</button>
          <button class="qchip" data-log="dose">${ic('syringe')}Доза</button>
          <button class="qchip" data-log="measure">${ic('ruler')}Замер</button>
        </div>
      </div>
      <section class="sec o1">
        ${secH('Внимание', '<span class="meta">3</span>')}
        <div class="alerts">
          <div class="alert">${ic('eye')}<div><span style="color:var(--muted)">Наблюдение · </span>HRV третью ночь ниже твоего коридора 50–58 мс, пульс покоя на верхней границе. Восстановление отстаёт от нагрузки.<span class="ev">Garmin · 14 ночей</span></div></div>
          <a href="#" class="alert warn" data-go="labs">${ic('warn')}<div><b>Витамин D 28 нг/мл</b> — ниже референса <span class="nw">30–100</span>.<span class="ev">анализ от 6 сентября · правило «добавки ↔ анализы»</span></div></a>
          <div class="alert info">${ic('cal')}<div>Инъекция по графику — <b>воскресенье, 4 октября</b>.</div></div>
        </div>
      </section>
      <section class="sec o4">
        ${secH('Цель', `<span class="meta">80 кг к ${dLong(g.deadline)}</span>`)}
        <div class="goal-top"><span class="gv">${fmt(done)}<span class="u">из ${fmt(total, 0)} кг</span></span><span class="sub num">${Math.round(gp)} %</span></div>
        <div class="meter"><i style="width:${gp}%"></i><span class="tick" style="left:25%"></span><span class="tick" style="left:50%"></span><span class="tick" style="left:75%"></span></div>
        <div class="goal-scale"><span>${fmt(g.start, 0)}</span><span>сейчас ${fmt(w)}</span><span>${fmt(g.target, 0)}</span></div>
        <p class="sub" style="margin:12px 0 0">При нынешнем тренде — около 10 декабря, на 17 дней раньше срока.</p>
      </section>
    </div>
  </div>`;
}

/* ---------- Weight ---------- */
function scrWeight(ctx) {
  const w = DATA.lastW.w, dW = DATA.ma7 - DATA.weekAgo;
  const hist = DATA.weightHistory.map(h => {
    const src = h.src === 'manual' ? '<span class="badge good">вручную</span>' : h.src === 'bia' ? '<span class="badge violet">InBody</span>' : '<span class="badge cool">Garmin</span>';
    return `<div class="row${h.superseded ? ' dim' : ''}" style="grid-template-columns:minmax(0,1fr) auto 72px">
      <div><div class="t">${dRel(h.date)} <span class="m num" style="margin-left:4px">${h.time}</span></div>${h.superseded ? '<div class="m">перекрыто ручной записью за тот же день</div>' : h.note ? `<div class="m">${h.note}</div>` : ''}</div>
      ${src}<div class="v">${fmt(h.w)}<span class="u">кг</span></div></div>`;
  }).join('');
  return `
  ${topbar('Вес', { back: ctx.back })}
  ${mast('weight', { actions: `<button class="ghost" data-log="weight">${ic('plus')}Записать</button>` })}
  <div class="headline">
    <h1 class="h1">Вес</h1>
    <div class="fig-hero">
      <div class="big" data-fig="weight" data-shared-target>${odo(fmt(w))}<span class="unit">кг</span></div>
      <div class="side"><span class="delta good">${ic('down')}${fmt(Math.abs(dW))} кг за неделю</span><span class="sub">среднее 7 дней ${fmt(DATA.ma7)} · жир ${fmt(DATA.bodyFat)} % (Navy)</span></div>
    </div>
  </div>
  <section class="sec">
    <div class="panel bare">
      <div class="panel-h"><h3>Вес и тренд</h3>
        <div class="seg" data-seg="range"><i class="pill"></i>
          <button data-range="1m">1 мес</button><button data-range="3m" class="on">3 мес</button><button data-range="all">6 мес</button>
        </div>
      </div>
      <div class="chart" data-chart="weight"></div>
      <div class="legend"><span><i></i>тренд 7 дней</span><span><i class="dots"></i>взвешивания</span><span><i class="band"></i>семаглутид</span><span><i class="now"></i>сейчас</span></div>
    </div>
  </section>
  <div class="grid">
    <div class="c7">
      <section class="sec">${secH('История', '<span class="meta">ручной ввод и скан перекрывают Garmin</span>')}<div class="rows">${hist}</div></section>
    </div>
    <div class="c5">
      <section class="sec">${secH('Темп')}
        <div class="rows">
          <div class="row" style="grid-template-columns:1fr auto"><div><div class="t">Тренд</div><div class="m">регрессия за 28 дней</div></div><div class="v good">−0,6<span class="u">кг/нед</span></div></div>
          <div class="row" style="grid-template-columns:1fr auto"><div><div class="t">На дозе 0,5 мг</div><div class="m">с 2 августа · 58 дней</div></div><div class="v">−3,1<span class="u">кг</span></div></div>
          <div class="row" style="grid-template-columns:1fr auto"><div><div class="t">До цели 80 кг</div><div class="m">при нынешнем тренде</div></div><div class="v">≈10<span class="u">нед</span></div></div>
        </div>
      </section>
      <section class="sec">${secH('Последний скан', '<a href="#" class="link" data-soon="Замеры">все замеры' + ic('chevR') + '</a>')}<p class="sub" style="margin:-4px 0 10px">InBody · 12 сентября</p>
        <div class="rows">
          ${[['Жир', '18,4', '%'], ['Скелетные мышцы', '39,2', 'кг'], ['Висцеральный жир', '7', 'ур.'], ['Вода', '53,1', 'л']].map(([t, v, u]) => `<div class="row" style="grid-template-columns:1fr auto;min-height:44px"><div class="t" style="font-weight:400;color:var(--fg-2)">${t}</div><div class="v">${v}<span class="u">${u}</span></div></div>`).join('')}
        </div>
      </section>
    </div>
  </div>`;
}

/* ---------- Recovery ---------- */
function toneCell(k, v) {
  const n = DATA.NORMS[k]; const span = n.hi - n.lo;
  let z = 0; if (v < n.lo) z = (v - n.lo) / span; else if (v > n.hi) z = (v - n.hi) / span;
  z *= n.better;
  if (z === 0) return '';
  const s = Math.abs(z) > .25 ? 2 : 1;
  return (z > 0 ? 'g' : 'b') + s;
}
function scrRecovery(ctx) {
  const N = DATA.nights, n0 = N[N.length - 1];
  const hm = (m) => `${Math.floor(m / 60)} ч ${String(m % 60).padStart(2, '0')}`;
  const [aw, rem, li, de] = DATA.stageMin, tot = aw + rem + li + de;
  const norms = [['sleep', n0.sleep, 40, 100], ['hrv', n0.hrv, 35, 70], ['rhr', n0.rhr, 44, 60], ['stress', n0.stress, 0, 60]].map(([k, v, mn, mx]) => {
    const n = DATA.NORMS[k]; const out = v < n.lo || v > n.hi; const bad = out && ((v < n.lo) === (n.better > 0));
    return `<div class="row"><div><div class="t">${n.label}</div><div class="m">норма ${n.lo}–${n.hi}${n.unit ? ' ' + n.unit : ''}</div></div><div class="v ${bad ? 'bad' : ''}">${v}${n.unit ? `<span class="u">${n.unit}</span>` : ''}</div>${rbar({ v, lo: n.lo, hi: n.hi, min: mn, max: mx, tone: bad ? 'bad' : '' })}</div>`;
  }).join('');
  const keys = ['sleep', 'hrv', 'rhr', 'stress', 'steps', 'bb'];
  const heat = `<table><colgroup><col class="lblc">${N.map(() => '<col>').join('')}</colgroup><thead><tr><th></th>${N.map((n, i) => `<th class="${i === N.length - 1 ? 'now' : ''}">${WD[n.date.getDay()]}<br>${n.date.getDate()}</th>`).join('')}</tr></thead><tbody>
    ${keys.map(k => `<tr><td class="lbl">${DATA.NORMS[k].label}<small>${DATA.NORMS[k].lo}–${k === 'steps' ? fmtI(DATA.NORMS[k].hi) : DATA.NORMS[k].hi}</small></td>${N.map(n => `<td><div class="cell ${toneCell(k, n[k])}">${k === 'steps' ? (n[k] / 1000).toFixed(1).replace('.', ',') + 'k' : n[k]}</div></td>`).join('')}</tr>`).join('')}
  </tbody></table>`;
  const daysM = `<div class="days-head"><span>день</span><span>сон</span><span>HRV</span><span>пульс</span><span>шаги</span></div><div class="days">${[...N].reverse().slice(0, 10).map(n => `<div class="day"><div class="d">${daysBetween(n.date, TODAY) === 0 ? 'сегодня' : daysBetween(n.date, TODAY) === 1 ? 'вчера' : WD[n.date.getDay()]}<small>${dShort(n.date)}</small></div>${['sleep', 'hrv', 'rhr', 'steps'].map(k => `<div class="cell ${toneCell(k, n[k])}">${k === 'steps' ? (n[k] / 1000).toFixed(1).replace('.', ',') + 'k' : n[k]}</div>`).join('')}</div>`).join('')}</div>`;
  return `
  ${topbar('Восстановление', { back: ctx.back })}
  ${mast('recovery', { actions: `<button class="ghost" data-sync>${ic('sync')}Синхронизировать</button>` })}
  <div class="headline">
    <h1 class="h1">Восстановление</h1>
    <div class="figs inline">
      <div class="f"><div class="f-v">82</div><div class="f-l">Сон</div><div class="f-s">7 ч 34 мин</div></div>
      <div class="f"><div class="f-v bad">${n0.hrv}<span class="u">мс</span></div><div class="f-l">HRV</div><div class="f-s bad">3 ночи ниже нормы</div></div>
      <div class="f"><div class="f-v">${n0.rhr}<span class="u">уд/мин</span></div><div class="f-l">Пульс покоя</div><div class="f-s">верх нормы</div></div>
      <div class="f"><div class="f-v">36→94</div><div class="f-l">Body Battery</div><div class="f-s">зарядка за ночь</div></div>
    </div>
  </div>
  <div class="grid" style="margin-top:0">
    <div class="c7">
      <section class="sec">${secH('Ночь на 29 сентября', '<span class="meta num">23:40 → 07:14</span>')}
        <div class="panel bare">
          <div class="chart" data-chart="hyp"></div>
          <div class="compo${ctx.intro ? '' : ''}" data-compo>
            <i style="flex:${de};background:var(--deep)"></i><i style="flex:${li};background:var(--cool)"></i><i style="flex:${rem};background:var(--violet)"></i><i style="flex:${aw};background:var(--bad)"></i>
          </div>
          <div class="hyp-legend">
            <div><i style="background:var(--deep)"></i>Глубокий<b>${hm(de)}</b></div>
            <div><i style="background:var(--cool)"></i>Лёгкий<b>${hm(li)}</b></div>
            <div><i style="background:var(--violet)"></i>REM<b>${hm(rem)}</b></div>
            <div><i style="background:var(--bad)"></i>Пробужд.<b>${aw} мин</b></div>
          </div>
        </div>
      </section>
    </div>
    <div class="c5">
      <section class="sec">${secH('Относительно нормы', '<span class="meta">твой коридор, 60 дней</span>')}<div class="rows norms">${norms}</div></section>
    </div>
  </div>
  <section class="sec">${secH('14 дней', '<span class="meta">цвет — отклонение от твоей нормы</span>')}
    <div class="heat">${heat}</div>
    <div class="days-m">${daysM}</div>
  </section>`;
}

/* ---------- GLP-1 ---------- */
function scrGlp(ctx) {
  const bm = bodyMap();
  const cyc = [];
  for (let i = 0; i <= 7; i++) {
    const d = addDays(new Date(2026, 8, 27), i);
    const k = daysBetween(TODAY, d);
    const cls = i === 0 ? 'inj past' : i === 7 ? 'next' : k === 0 ? 'now' : k < 0 ? 'past' : '';
    cyc.push(`<div class="cyc ${cls}"><i></i><b>${d.getDate()}</b><span>${k === 0 ? 'сегодня' : WD[d.getDay()]}</span></div>`);
  }
  const sites = Object.keys(bm.last).concat(['Плечо Л']).filter((v, i, a) => a.indexOf(v) === i)
    .sort((a, b) => (bm.last[b] || 0) - (bm.last[a] || 0))
    .map(s => `<div class="${s === bm.suggest ? 'sug' : ''}"><span>${s}</span><span>${s === bm.suggest ? 'реже всего' : bm.last[s] ? dShort(bm.last[s]) : '—'}</span></div>`).join('');
  return `
  ${topbar('GLP-1', { back: ctx.back })}
  ${mast('glp1', { actions: `<button class="ghost" data-log="dose">${ic('syringe')}Инъекция</button>` })}
  <div class="headline">
    <h1 class="h1">GLP-1</h1>
    <div class="fig-hero">
      <div class="big">0,5<span class="unit">мг</span></div>
      <div class="side"><span class="badge violet">Семаглутид</span><span class="sub">58-й день на дозе · с 2 августа</span></div>
    </div>
  </div>
  <div class="grid">
    <div class="c7">
      <section class="sec">${secH('Цикл')}
        <div class="panel bare">
          <div class="cyc-cap"><div class="big">Следующая — <span class="nw">вс, 4 октября</span></div><span class="sub">через 5 дней</span></div>
          <div class="cycle"><span class="prog"></span>${cyc.join('')}</div>
        </div>
      </section>
      <section class="sec">${secH('Доза и вес', '<span class="meta">тренд 7 дней</span>')}
        <div class="panel bare">
          <div class="chart" data-chart="dose"></div>
          <div class="legend"><span><i style="background:var(--violet)"></i>доза, мг</span><span><i style="opacity:.75"></i>вес</span></div>
          <p class="sub" style="margin:12px 0 0">На 0,25 мг: −2,1 кг за 4 недели. На 0,5 мг: −3,1 кг за 58 дней, темп замедлился с середины сентября.</p>
        </div>
      </section>
    </div>
    <div class="c5">
      <section class="sec">${secH('Места инъекций', '<span class="meta">ротация</span>')}
        <div class="sites"><div>${bm.svg}</div><div class="site-list">${sites}</div></div>
      </section>
      <section class="sec">${secH('Побочные эффекты')}
        <div class="rows">${DATA.sideEffects.map(e => `<div class="row" style="grid-template-columns:1fr auto"><div><div class="t">${e.name}</div><div class="m">${dLong(e.date)}</div></div><span class="pips${e.sev < 3 ? ' l2' : ''}" title="${e.sev} из 5">${[1, 2, 3, 4, 5].map(k => `<i class="${k <= e.sev ? 'on' : ''}"></i>`).join('')}</span></div>`).join('')}</div>
      </section>
      <section class="sec">${secH('История', `<span class="meta">${DATA.injections.length} инъекций</span>`)}
        <div class="rows">${DATA.injections.slice(0, 5).map(j => `<div class="row" style="grid-template-columns:1fr auto auto"><div class="t" style="font-weight:400">${dRel(j.date)}</div><span class="m">${j.site}</span><div class="v">${fmt(j.dose, j.dose < .5 ? 2 : 1)}<span class="u">мг</span></div></div>`).join('')}</div>
      </section>
    </div>
  </div>`;
}

/* ---------- Labs ---------- */
function mkRow(m, sel) {
  const bad = m.status !== 'ok';
  return `<div class="row mk${sel ? ' sel' : ''}" data-mk="${m.id}" data-group="${m.group}" data-status="${m.status}" tabindex="0" role="button">
    <div><div class="t">${m.name}</div><div class="m">${m.group}</div></div>
    <div style="text-align:right"><div class="v ${bad ? 'bad' : ''}">${fmt(m.v, m.d || 0)}<span class="u">${m.unit}</span></div><div class="st ${bad ? 'bad' : ''}" style="${bad ? '' : 'color:var(--faint)'}">${m.status === 'low' ? 'ниже нормы' : m.status === 'high' ? 'выше нормы' : 'в норме'}</div></div>
    ${rbar({ v: m.v, lo: m.lo, hi: m.hi, min: m.min, max: m.max, tone: bad ? 'bad' : '' })}
    <div class="scale"><span>${fmt(m.min, m.d || 0)}</span><span>норма ${fmt(m.lo, m.d || 0)}–${fmt(m.hi, m.d || 0)}</span><span>${fmt(m.max, m.d || 0)}</span></div>
    <div class="mk-detail collapse${sel ? ' open' : ''}"><div><div class="mk-detail-in"><div class="chart" data-chart="mk" data-mkid="${m.id}"></div><p class="mk-note">${labNote(m)}</p></div></div></div>
  </div>`;
}
function labNote(m) {
  const f = m.hist[0][1], l = m.hist[m.hist.length - 1][1];
  const dir = l > f ? 'вырос' : 'снизился';
  return `С марта ${dir} с ${fmt(f, m.d || 0)} до ${fmt(l, m.d || 0)} ${m.unit}. ${m.status === 'low' ? 'Всё ещё ниже референса — движение в нужную сторону.' : 'В пределах референса.'}`;
}
function labSide(m) {
  const bad = m.status !== 'ok';
  return `<div class="panel" data-labside>
    <div class="panel-h"><h3>${m.name}</h3><span class="sub">${dLong(DATA.LAB_DATE)}</span></div>
    <div class="fig-hero" style="margin-top:4px"><div class="big" style="font-size:56px;${bad ? 'color:var(--bad-strong)' : ''}">${fmt(m.v, m.d || 0)}<span class="unit">${m.unit}</span></div>
    <div class="side"><span class="delta ${bad ? 'bad' : ''}">${m.status === 'low' ? 'ниже нормы' : 'в норме'}</span><span class="sub">норма ${fmt(m.lo, m.d || 0)}–${fmt(m.hi, m.d || 0)}</span></div></div>
    <div class="chart" data-chart="mkside" style="margin-top:22px"></div>
    <p class="mk-note">${labNote(m)}</p>
    <div class="rows" style="margin-top:14px">${[...m.hist].reverse().map(h => `<div class="row" style="grid-template-columns:1fr auto;min-height:42px"><span class="m" style="font-size:var(--t-body);color:var(--fg-2)">${dLong(h[0])}</span><div class="v ${h[1] < m.lo || h[1] > m.hi ? 'bad' : ''}">${fmt(h[1], m.d || 0)}<span class="u">${m.unit}</span></div></div>`).join('')}</div>
  </div>`;
}
function scrLabs(ctx) {
  const sel = ctx.st.labSel;
  const groups = ['Метаболизм', 'Гормоны', 'Витамины'];
  return `
  ${topbar('Анализы', { back: ctx.back })}
  ${mast('labs', { actions: `<button class="ghost" data-upload>${ic('upload')}Загрузить бланк</button>` })}
  <div class="headline">
    <h1 class="h1">Анализы</h1>
    <div class="figs inline n3">
      <div class="f"><div class="f-v">${DATA.labs.length}</div><div class="f-l">Маркеров</div><div class="f-s">в последней сдаче</div></div>
      <div class="f"><div class="f-v bad">1</div><div class="f-l">Вне нормы</div><div class="f-s">витамин D</div></div>
      <div class="f"><div class="f-v">6 сен</div><div class="f-l">Сдано</div><div class="f-s">Инвитро · PDF</div></div>
    </div>
  </div>
  <button class="drop sec" data-upload style="margin-top:28px"><span class="ico">${ic('upload')}</span><span><b>Загрузить PDF или фото бланка</b><small>распознаем маркеры, единицы и референсы — проверишь перед сохранением</small></span></button>
  <div class="filters" data-filters>
    <button class="filter on" data-filter="all">Все ${DATA.labs.length}</button>
    <button class="filter" data-filter="out">Вне нормы<span class="n">1</span></button>
    ${groups.map(g => `<button class="filter" data-filter="${g}">${g}</button>`).join('')}
  </div>
  <div class="grid" style="margin-top:8px">
    <div class="c7"><div class="rows" data-mklist style="margin-top:12px;border-top:0">${DATA.labs.map(m => mkRow(m, m.id === sel)).join('')}</div></div>
    <div class="c5"><div class="lab-side sticky" data-labside-wrap style="margin-top:12px">${labSide(DATA.labs.find(m => m.id === sel))}</div></div>
  </div>`;
}

/* ---------- More (phone) ---------- */
function scrMore() {
  const status = { weight: ['86,1 кг', ''], recovery: ['сон 82', ''], workouts: ['5 дн назад', ''], nutrition: ['420 ккал', ''], glp1: ['через 5 дн', ''], labs: ['1 вне нормы', 'bad'], genetics: ['VCF · 14 правил', ''], supplements: ['3 активных', ''], skincare: ['утро ✓', ''], timeline: ['', ''], reports: ['дайджест вс', ''], charts: ['4', ''] };
  return `
  ${topbar('Ещё')}
  <div class="kicker" style="margin-top:4px">Все разделы</div>
  <h1 class="h1">Ещё</h1>
  ${RUBRICS.map(r => `<section class="more-group"><h2>${r.name}</h2><div class="more-list">
    ${r.items.map(([id, t, icn]) => `<button class="more-row" data-go="${id}"><span class="mi">${ic(icn)}</span><span class="t">${t}</span><span class="s ${status[id]?.[1] || ''}">${status[id]?.[0] || ''}</span>${ic('chevR').replace('<svg', '<svg class="chev"')}</button>`).join('')}
  </div></section>`).join('')}
  <section class="more-group"><h2>Система</h2><div class="more-list">
    <button class="more-row" data-soon="Для врача"><span class="mi">${ic('clipboard')}</span><span class="t">Для врача</span><span class="s">отчёт по ссылке</span>${ic('chevR').replace('<svg', '<svg class="chev"')}</button>
    <button class="more-row" data-soon="Настройки"><span class="mi">${ic('sliders')}</span><span class="t">Настройки</span><span class="s">14 модулей</span>${ic('chevR').replace('<svg', '<svg class="chev"')}</button>
  </div></section>`;
}

const SCREENS = { today: scrToday, weight: scrWeight, recovery: scrRecovery, glp1: scrGlp, labs: scrLabs, more: scrMore };

/* ---------- Shared pieces: stepper, conflict box, sheet ---------- */
function stepper(v) {
  return `<div class="stepper" data-stepper data-val="${v.toFixed(1)}">
    <button class="k" data-step="-1" aria-label="минус 0,1 кг">${ic('minus')}</button>
    <div class="val" data-stepval tabindex="0" role="spinbutton" aria-valuenow="${v}">${odo(fmt(v))}<span class="u">кг</span></div>
    <button class="k" data-step="1" aria-label="плюс 0,1 кг">${ic('plus')}</button>
  </div>`;
}
function conflictBox() {
  return `<div class="collapse" data-conflict><div><div class="alert block" style="margin-top:12px">${ic('block')}<div><span data-conflict-text></span><span class="ev">правило «скачок веса» · блок до подтверждения</span>
    <div class="acts"><button class="ghost" data-fix>Исправить</button><button class="ghost danger" data-override>Сохранить всё равно</button></div></div></div></div></div>`;
}
function sheetHTML() {
  return `<div class="scrim" data-close></div>
  <div class="sheet" role="dialog" aria-modal="true" aria-label="Записать">
    <div class="sheet-grab" data-grab><i></i></div>
    <div class="sheet-head" data-grab><h3>Записать</h3><button class="ibtn" data-close aria-label="Закрыть">${ic('x')}</button></div>
    <div class="sheet-body">
      <div class="seg" data-seg="log"><i class="pill"></i>
        <button data-logtab="weight" class="on">Вес</button><button data-logtab="meal">Еда</button><button data-logtab="dose">Доза</button><button data-logtab="measure">Замер</button>
      </div>
      <div class="sheet-pane" data-pane="weight" data-logform>
        ${stepper(DATA.lastW.w)}
        <div class="stepper-cap"><span>шаг 0,1 · удерживай для быстрой прокрутки</span><span>утром ${fmt(DATA.lastW.w)}</span></div>
        <div class="meta-line"><span class="badge plain">${ic('cal')}сегодня, ${DATA.now}</span><span class="badge good">вручную · приоритет над Garmin</span></div>
        ${conflictBox()}
        <button class="btn w" data-save="weight">Сохранить вес</button>
      </div>
      <div class="sheet-pane" data-pane="meal" hidden data-logform>
        <div class="field"><label for="in1-${CID}">Что ели</label><input id="in1-${CID}" name="in1" class="input" placeholder="например, гречка с курицей"></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div class="field"><label for="in2-${CID}">Калории</label><input id="in2-${CID}" name="in2" class="input" inputmode="numeric" placeholder="ккал"></div>
          <div class="field"><label for="in3-${CID}">Белок</label><input id="in3-${CID}" name="in3" class="input" inputmode="numeric" placeholder="г"></div>
        </div>
        <div class="field"><span class="flabel">Приём</span><div class="opts" data-opts><button class="opt">Завтрак</button><button class="opt on">Обед</button><button class="opt">Ужин</button><button class="opt">Перекус</button></div></div>
        <button class="btn w" data-save="meal">Сохранить приём пищи</button>
      </div>
      <div class="sheet-pane" data-pane="dose" hidden data-logform>
        <div class="field"><span class="flabel">Препарат</span><div class="opts" data-opts><button class="opt on">Семаглутид 0,5 мг</button><button class="opt">Другая доза</button></div></div>
        <div class="field"><span class="flabel">Место</span><div class="opts" data-opts>
          <button class="opt">Живот Л</button><button class="opt">Живот П</button><button class="opt on">Плечо Л<span class="hint">реже всего</span></button><button class="opt">Бедро Л</button><button class="opt">Бедро П</button><button class="opt">Плечо П</button>
        </div></div>
        <div class="alert warn">${ic('warn')}<div>По графику следующая — <b>вс, 4 октября</b>. Сегодня на 5 дней раньше.<span class="ev">запишется как внеплановая</span></div></div>
        <button class="btn w" data-save="dose">Записать инъекцию</button>
      </div>
      <div class="sheet-pane" data-pane="measure" hidden data-logform>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div class="field"><label for="in4-${CID}">Талия</label><input id="in4-${CID}" name="in4" class="input" inputmode="decimal" placeholder="см" value="84,5"></div>
          <div class="field"><label for="in5-${CID}">Шея</label><input id="in5-${CID}" name="in5" class="input" inputmode="decimal" placeholder="см" value="39,0"></div>
        </div>
        <p class="sub" style="margin:0">Жир по формуле Navy пересчитается сразу: сейчас ${fmt(DATA.bodyFat)} %.</p>
        <button class="btn w" data-save="measure">Сохранить замер</button>
      </div>
      <div style="height:6px"></div>
    </div>
  </div>`;
}

function railHTML() {
  return `<aside class="rail">
    <div class="brand">Vitals</div>
    <button class="rail-log" data-log="weight">${ic('plus')}Записать<kbd>N</kbd></button>
    <nav class="rail-nav"><span class="rail-ink"></span>
      <a href="#" class="rail-a pinned" data-go="today" data-nav="today"><span class="ic">${ic('today')}</span><span>Сегодня</span></a>
      ${RUBRICS.map(r => `<div class="rail-g">${r.name}</div>${r.items.map(([id, t, icn]) => `<a href="#" class="rail-a${BUILT.has(id) ? '' : ' soon'}" data-go="${id}" data-nav="${id}"><span class="ic">${ic(icn)}</span><span>${t}</span>${id === 'labs' ? '<span class="n">1</span>' : ''}</a>`).join('')}`).join('')}
    </nav>
    <div class="rail-status">
      <div class="rs"><span>Вес</span><b data-rs-weight>${fmt(DATA.lastW.w)}<small class="good">−0,6/нед</small></b></div>
      <div class="rs"><span>Сон · HRV</span><b>82 · 46<small class="bad">↓</small></b></div>
      <div class="rs"><span>Тренировка</span><b>5 дн назад</b></div>
    </div>
    <div class="rail-foot"><a href="#" data-soon="Для врача">${ic('clipboard')}Для врача</a><a href="#" data-soon="Настройки">${ic('sliders')}Настройки</a></div>
  </aside>`;
}
function bnavHTML() {
  return `<nav class="bnav"><i class="ink"></i>
    <a href="#" data-tab="today">${ic('today')}<span>Сегодня</span></a>
    <a href="#" data-tab="health">${ic('heart')}<span>Здоровье</span></a>
    <button class="plus" data-log="weight" aria-label="Записать">${ic('plus')}</button>
    <a href="#" data-tab="markers">${ic('drop')}<span>Маркеры</span></a>
    <a href="#" data-tab="more">${ic('grid')}<span>Ещё</span></a>
  </nav>`;
}

/* ==========================================================================
   App instance
   ========================================================================== */
let CID = 0;
const INSTANCES = [];
function createApp(host, { onNav } = {}) {
  const el = document.createElement('div');
  el.className = 'vt';
  CID++; el.innerHTML = railHTML() + `<div class="stage"><div class="screen-shade"></div></div>` + bnavHTML() + sheetHTML() + `<div class="toasts" aria-live="polite"></div>`;
  host.appendChild(el);
  const stage = el.querySelector('.stage'), shade = stage.querySelector('.screen-shade');
  const st = { stack: [], els: {}, range: '3m', labSel: 'vitd', introDone: false, busy: false, logTab: 'weight' };
  const app = { el, st, go, openSheet, closeSheet, replay, toast, reset };
  INSTANCES.push(app);

  const isDesk = () => el.clientWidth >= 768;
  const scaleOf = () => el.getBoundingClientRect().width / el.offsetWidth || 1;
  const anim = (node, kf, o) => node.animate(kf, { fill: 'both', easing: EASE_SHEET, ...o, duration: RM ? 1 : o.duration });

  /* ---------- Screens ---------- */
  function build(id, { intro = false, back = null } = {}) {
    const s = document.createElement('section');
    s.className = 'screen'; s.dataset.id = id;
    s.innerHTML = `<div class="page">${SCREENS[id]({ intro, back: isDesk() ? null : back, st })}</div>`;
    stage.appendChild(s);
    s.addEventListener('scroll', () => onScroll(s), { passive: true });
    return s;
  }
  function hydrate(s, { intro = false } = {}) {
    const phone = !isDesk();
    s.querySelectorAll('[data-chart]').forEach(box => {
      box.dataset.cid = box.dataset.cid || ++CID;
      const k = box.dataset.chart;
      if (k === 'weight') weightChart(box, { range: st.range, intro, phone });
      if (k === 'hyp') hypChart(box, { intro });
      if (k === 'dose') doseChart(box, { intro, phone });
      if (k === 'mk') { if (box.closest('.collapse.open') && phone) markerChart(box, DATA.labs.find(m => m.id === box.dataset.mkid), { intro, phone }); }
      if (k === 'mkside') { if (!phone) markerChart(box, DATA.labs.find(m => m.id === st.labSel), { intro, phone }); }
    });
    s.querySelectorAll('[data-compo]').forEach(c => c.classList.toggle('intro', intro));
    placeInks(s);
    onScroll(s);
  }
  function placeInks(root = el) {
    root.querySelectorAll('.chips').forEach(ch => {
      const on = ch.querySelector('.chip.on'), ink = ch.querySelector('.ink');
      if (!on || !ink) return;
      ink.style.transform = `translateX(${on.offsetLeft}px) scaleX(${on.offsetWidth / 100})`;
      if (!isDesk()) ch.scrollLeft = on.offsetLeft + on.offsetWidth > ch.clientWidth - 20 ? on.offsetLeft - 20 : 0;
    });
    root.querySelectorAll('.seg').forEach(sg => {
      const on = sg.querySelector('button.on'), p = sg.querySelector('.pill');
      if (on && p) { p.style.width = on.offsetWidth + 'px'; p.style.transform = `translateX(${on.offsetLeft}px)`; }
    });
    root.querySelectorAll('[data-subtabs]').forEach(sg => {
      const on = sg.querySelector('.on'), p = sg.querySelector('.ink');
      if (on && p) { p.style.width = on.offsetWidth + 'px'; p.style.transform = `translateX(${on.offsetLeft}px)`; }
    });
  }
  function onScroll(s) {
    const p = clamp((s.scrollTop - 24) / 40, 0, 1);
    s.style.setProperty('--p', p.toFixed(3));
  }
  function current() { return st.stack[st.stack.length - 1]; }

  function syncNav(instant = false) {
    const cur = current(), root = st.stack[0];
    el.querySelectorAll('.rail-ink, .bnav .ink').forEach(n => { n.style.transition = instant ? 'none' : ''; });
    // rail
    el.querySelectorAll('.rail-a').forEach(a => a.classList.toggle('on', a.dataset.nav === cur));
    const on = el.querySelector(`.rail-a[data-nav="${cur}"]`), ink = el.querySelector('.rail-ink');
    if (on && ink) { ink.style.opacity = 1; ink.style.height = on.offsetHeight + 'px'; ink.style.transform = `translateY(${on.offsetTop}px)`; }
    // bottom bar — the root's tab stays lit while you are deeper in it
    const tab = tabOf(root);
    el.querySelectorAll('.bnav a').forEach(a => { const onA = a.dataset.tab === tab; a.classList.toggle('on', onA); if (onA) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    const ta = el.querySelector(`.bnav a[data-tab="${tab}"]`), bi = el.querySelector('.bnav .ink');
    if (ta && bi) bi.style.transform = `translateX(${ta.offsetLeft + ta.offsetWidth / 2 - 10}px)`;
    if (instant) requestAnimationFrame(() => el.querySelectorAll('.rail-ink, .bnav .ink').forEach(n => { n.offsetHeight; n.style.transition = ''; }));
    onNav && onNav(cur);
  }

  /* ---------- Navigation ---------- */
  async function go(id, { mode, shared } = {}) {
    if (!BUILT.has(id)) { toast(`«${TITLE[id]}» в макет не входит`, { icon: 'info' }); return; }
    if (st.busy || id === current()) { if (id === current()) scrollTop(); return; }
    if (id === 'more' && isDesk()) { id = 'today'; }
    st.busy = true;
    const from = current(), fromEl = st.els[from];
    if (isDesk() || !mode) mode = isDesk() ? 'fade' : mode || 'fade';

    if (mode === 'push') {
      const s = build(id, { back: TITLE[from] }); st.els[id] = s; st.stack.push(id);
      hydrate(s, { intro: true });
      syncNav();
      if (shared) await sharedMorph(fromEl, s, shared); else await slide(fromEl, s, 1);
      fromEl.hidden = true;
    } else {
      // tab / chip / desktop: crossfade, the stack starts over
      const keep = mode === 'replace' ? st.stack.slice(0, -1) : [];
      const s = build(id, { back: keep.length ? TITLE[keep[keep.length - 1]] : null }); st.els[id] = s;
      const drop = st.stack.filter(x => !keep.includes(x));
      st.stack = [...keep, id];
      hydrate(s, { intro: true });
      syncNav();
      if (shared) await sharedMorph(fromEl, s, shared);
      else await fade(fromEl, s);
      drop.forEach(x => { if (x !== id && st.els[x]) { st.els[x].remove(); delete st.els[x]; } });
      if (mode === 'replace') keep.forEach(x => st.els[x] && (st.els[x].hidden = true));
    }
    st.busy = false;
  }
  async function pop() {
    if (st.busy || st.stack.length < 2) return;
    st.busy = true;
    const cur = st.stack.pop(), curEl = st.els[cur], prevEl = st.els[current()];
    prevEl.hidden = false; syncNav();
    await slide(curEl, prevEl, -1);
    curEl.remove(); delete st.els[cur];
    st.busy = false;
  }
  function scrollTop() { const s = st.els[current()]; s && s.scrollTo({ top: 0, behavior: RM ? 'auto' : 'smooth' }); }

  async function slide(a, b, dir, fromProgress = 0) {
    // dir 1: b enters from the right over a; dir -1: a leaves to the right, b comes back
    const D = 540 * (1 - fromProgress);
    const top = dir > 0 ? b : a, under = dir > 0 ? a : b;
    under.style.zIndex = 1; shade.style.zIndex = 2; top.style.zIndex = 3;
    top.style.boxShadow = '-24px 0 48px -18px rgba(0,0,0,.55)';
    const W = stage.offsetWidth;
    const p0 = dir > 0 ? 1 : fromProgress, p1 = dir > 0 ? 0 : 1; // top element x as fraction of width
    const u0 = dir > 0 ? 0 : -.28 * (1 - fromProgress), u1 = dir > 0 ? -.28 : 0;
    const sh0 = dir > 0 ? 0 : .32 * (1 - fromProgress), sh1 = dir > 0 ? .32 : 0;
    await Promise.all([
      anim(top, [{ transform: `translateX(${p0 * W}px)` }, { transform: `translateX(${p1 * W}px)` }], { duration: D }).finished,
      anim(under, [{ transform: `translateX(${u0 * W}px)` }, { transform: `translateX(${u1 * W}px)` }], { duration: D }).finished,
      anim(shade, [{ opacity: sh0 }, { opacity: sh1 }], { duration: D }).finished,
    ]);
    [top, under, shade].forEach(n => { n.getAnimations().forEach(x => x.cancel()); n.style.zIndex = ''; });
    top.style.boxShadow = '';
  }
  async function fade(a, b) {
    b.style.zIndex = 2; if (a) a.style.zIndex = 1;
    const jobs = [anim(b, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'none' }], { duration: 380, delay: 40, easing: EASE_OUT }).finished];
    if (a) jobs.push(anim(a, [{ opacity: 1 }, { opacity: 0 }], { duration: 140, easing: 'linear' }).finished);
    await Promise.all(jobs);
    b.getAnimations().forEach(x => x.cancel()); b.style.zIndex = '';
    if (a) { a.getAnimations().forEach(x => x.cancel()); a.style.zIndex = ''; }
  }
  async function sharedMorph(a, b, srcNode) {
    // The weight figure leaves Today and lands as the Weight page's hero.
    const tgt = b.querySelector('[data-shared-target]');
    if (!tgt || RM) return fade(a, b);
    const k = scaleOf(), root = el.getBoundingClientRect();
    const r0 = srcNode.getBoundingClientRect(), r1 = tgt.getBoundingClientRect();
    const fs0 = parseFloat(getComputedStyle(srcNode).fontSize), fs1 = parseFloat(getComputedStyle(tgt).fontSize);
    const fly = srcNode.cloneNode(true);
    fly.classList.add('flyer');
    Object.assign(fly.style, { left: (r0.left - root.left) / k + 'px', top: (r0.top - root.top) / k + 'px', fontSize: fs0 + 'px', width: 'auto' });
    el.appendChild(fly);
    srcNode.style.visibility = 'hidden'; tgt.style.visibility = 'hidden';
    b.style.zIndex = 2; a.style.zIndex = 1;
    const dx = (r1.left - r0.left) / k, dy = (r1.top - r0.top) / k, sc = fs1 / fs0;
    await Promise.all([
      anim(fly, [{ transform: 'none' }, { transform: `translate(${dx}px, ${dy}px) scale(${sc})` }], { duration: 620 }).finished,
      anim(b, [{ opacity: 0, transform: 'scale(.985)' }, { opacity: 1, transform: 'none' }], { duration: 460, delay: 90, easing: EASE_OUT }).finished,
      anim(a, [{ opacity: 1 }, { opacity: 0 }], { duration: 220, easing: 'linear' }).finished,
    ]);
    tgt.style.visibility = ''; srcNode.style.visibility = '';
    fly.remove();
    [a, b].forEach(n => { n.getAnimations().forEach(x => x.cancel()); n.style.zIndex = ''; });
  }

  /* ---------- Edge swipe back (phone) ---------- */
  let sw = null;
  stage.addEventListener('pointerdown', (e) => {
    if (isDesk() || st.busy || st.stack.length < 2 || e.pointerType === 'mouse' && e.button !== 0) return;
    const k = scaleOf(), x = (e.clientX - stage.getBoundingClientRect().left) / k;
    if (x > 28) return;
    const cur = st.els[current()], prev = st.els[st.stack[st.stack.length - 2]];
    sw = { id: e.pointerId, x0: e.clientX, t0: performance.now(), cur, prev, k, W: stage.offsetWidth, dx: 0 };
    prev.hidden = false; prev.style.zIndex = 1; shade.style.zIndex = 2; cur.style.zIndex = 3;
    cur.style.boxShadow = '-24px 0 48px -18px rgba(0,0,0,.55)';
    try { stage.setPointerCapture(e.pointerId); } catch (_) { }
  });
  stage.addEventListener('pointermove', (e) => {
    if (!sw || e.pointerId !== sw.id) return;
    sw.dx = clamp((e.clientX - sw.x0) / sw.k, 0, sw.W);
    const p = sw.dx / sw.W;
    sw.cur.style.transform = `translateX(${sw.dx}px)`;
    sw.prev.style.transform = `translateX(${-.28 * sw.W * (1 - p)}px)`;
    shade.style.opacity = .32 * (1 - p);
  });
  const endSwipe = async (e) => {
    if (!sw || e.pointerId !== sw.id) return;
    const s = sw; sw = null;
    const p = s.dx / s.W, v = s.dx / Math.max(1, performance.now() - s.t0);
    [s.cur, s.prev].forEach(n => { n.style.transform = ''; }); shade.style.opacity = '';
    if (p > .35 || (v > .5 && p > .08)) {
      st.busy = true;
      const cur = st.stack.pop(); syncNav();
      await slide(s.cur, s.prev, -1, p);
      s.cur.remove(); delete st.els[cur]; st.busy = false;
    } else {
      st.busy = true;
      const D = RM ? 1 : 360;
      await Promise.all([
        anim(s.cur, [{ transform: `translateX(${s.dx}px)` }, { transform: 'none' }], { duration: D }).finished,
        anim(s.prev, [{ transform: `translateX(${-.28 * s.W * (1 - p)}px)` }, { transform: `translateX(${-.28 * s.W}px)` }], { duration: D }).finished,
        anim(shade, [{ opacity: .32 * (1 - p) }, { opacity: .32 }], { duration: D }).finished,
      ]);
      [s.cur, s.prev, shade].forEach(n => { n.getAnimations().forEach(x => x.cancel()); n.style.zIndex = ''; });
      s.cur.style.boxShadow = ''; s.prev.hidden = true; st.busy = false;
    }
  };
  stage.addEventListener('pointerup', endSwipe); stage.addEventListener('pointercancel', endSwipe);

  /* ---------- Sheet ---------- */
  const sheet = el.querySelector('.sheet');
  const closedT = () => isDesk() ? 'translateX(calc(100% + 24px))' : 'translateY(105%)';
  function openSheet(tab = 'weight') {
    setLogTab(tab, false);
    const sv = sheet.querySelector('[data-pane="weight"] [data-stepper]');
    setStep(sv, DATA.lastW.w, false);
    closeConflict(sheet);
    sheet.classList.add('vis'); el.classList.add('sheet-open');
    sheet.style.transition = 'none'; sheet.style.transform = closedT();
    sheet.offsetHeight;
    sheet.style.transition = `transform ${RM ? 1 : 520}ms ${EASE_SHEET}`;
    sheet.style.transform = 'none';
    requestAnimationFrame(() => placeInks(sheet));
  }
  function closeSheet() {
    if (!sheet.classList.contains('vis')) return;
    el.classList.remove('sheet-open');
    sheet.style.transition = `transform ${RM ? 1 : 380}ms ${EASE_SHEET}`;
    sheet.style.transform = closedT();
    const done = () => { sheet.classList.remove('vis'); sheet.style.transform = ''; sheet.style.transition = ''; };
    RM ? done() : setTimeout(done, 390);
  }
  function setLogTab(tab, animate = true) {
    st.logTab = tab;
    sheet.querySelectorAll('[data-logtab]').forEach(b => b.classList.toggle('on', b.dataset.logtab === tab));
    sheet.querySelectorAll('[data-pane]').forEach(p => {
      const on = p.dataset.pane === tab; p.hidden = !on;
      if (on && animate) { p.classList.remove('enter'); p.offsetHeight; p.classList.add('enter'); }
    });
    placeInks(sheet);
  }
  // drag to dismiss
  let dg = null;
  sheet.addEventListener('pointerdown', (e) => {
    if (isDesk() || !e.target.closest('[data-grab]') || e.target.closest('button')) return;
    dg = { id: e.pointerId, y0: e.clientY, t0: performance.now(), k: scaleOf(), dy: 0 };
    sheet.style.transition = 'none'; try { sheet.setPointerCapture(e.pointerId); } catch (_) { }
  });
  sheet.addEventListener('pointermove', (e) => {
    if (!dg || e.pointerId !== dg.id) return;
    const raw = (e.clientY - dg.y0) / dg.k;
    dg.dy = raw > 0 ? raw : -Math.sqrt(-raw) * 2; // resist upward
    sheet.style.transform = `translateY(${dg.dy}px)`;
    el.querySelector('.scrim').style.opacity = clamp(1 - dg.dy / sheet.offsetHeight, 0, 1);
  });
  const endDrag = (e) => {
    if (!dg || e.pointerId !== dg.id) return;
    const v = dg.dy / Math.max(1, performance.now() - dg.t0), h = sheet.offsetHeight; const dy = dg.dy; dg = null;
    el.querySelector('.scrim').style.opacity = '';
    if (dy > h * .28 || v > .6) closeSheet();
    else { sheet.style.transition = `transform 420ms ${EASE_SHEET}`; sheet.style.transform = 'none'; }
  };
  sheet.addEventListener('pointerup', endDrag); sheet.addEventListener('pointercancel', endDrag);

  /* ---------- Stepper ---------- */
  function setStep(stp, v, roll = true) {
    if (!stp) return;
    v = Math.round(clamp(v, 30, 250) * 10) / 10;
    stp.dataset.val = v.toFixed(1);
    const val = stp.querySelector('[data-stepval]');
    val.setAttribute('aria-valuenow', v);
    const o = val.querySelector('.odo');
    if (roll) setOdo(o, fmt(v)); else { o.outerHTML = odo(fmt(v)); }
  }
  let hold = null;
  el.addEventListener('pointerdown', (e) => {
    const k = e.target.closest('[data-step]'); if (!k) return;
    e.preventDefault();
    const stp = k.closest('[data-stepper]'), dir = +k.dataset.step;
    const tick = () => setStep(stp, +stp.dataset.val + dir * .1);
    tick(); k.classList.add('held');
    let n = 0;
    hold = { k, t: setTimeout(function rep() { tick(); n++; hold.t = setTimeout(rep, n < 6 ? 110 : n < 16 ? 60 : 30); }, 420) };
    closeConflict(stp.closest('[data-logform]'));
  });
  const stopHold = () => { if (hold) { clearTimeout(hold.t); hold.k.classList.remove('held'); hold = null; } };
  el.addEventListener('pointerup', stopHold); el.addEventListener('pointercancel', stopHold); el.addEventListener('pointerleave', stopHold);
  // tap the number to type it
  function editValue(val) {
    if (val.querySelector('input')) return;
    const stp = val.closest('[data-stepper]');
    const inp = document.createElement('input');
    inp.inputMode = 'decimal'; inp.value = fmt(+stp.dataset.val);
    val.appendChild(inp); inp.focus(); inp.select();
    const commit = () => { const v = parseFloat(inp.value.replace(',', '.').replace('−', '-')); inp.remove(); if (!isNaN(v)) setStep(stp, v); closeConflict(stp.closest('[data-logform]')); };
    inp.addEventListener('blur', commit, { once: true });
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') inp.blur(); if (e.key === 'Escape') { inp.value = ''; inp.blur(); } });
  }

  /* ---------- Save flow (with the conflict ladder) ---------- */
  function closeConflict(scope) { scope && scope.querySelector('[data-conflict]')?.classList.remove('open'); }
  async function save(btn, override = false) {
    const form = btn.closest('[data-logform]') || btn.closest('.sheet-pane');
    const kind = btn.dataset.save;
    const label = btn.textContent;
    if (kind === 'weight') {
      const v = +form.querySelector('[data-stepper]').dataset.val;
      const diff = v - DATA.lastW.w;
      if (!override && Math.abs(diff) >= 1.5) {
        const box = form.querySelector('[data-conflict]');
        box.querySelector('[data-conflict-text]').innerHTML = `<b>${fmtS(diff)} кг</b> к утреннему взвешиванию за пару часов — так быстро вес не меняется. Проверь ввод.`;
        box.classList.add('open');
        return;
      }
      closeConflict(form);
    }
    btn.style.width = btn.offsetWidth + 'px';
    btn.innerHTML = '<span class="spinner"></span>';
    await wait(RM ? 0 : 520);
    btn.dataset.state = 'done'; btn.innerHTML = ic('check') + 'Записано';
    await wait(RM ? 0 : 520);
    const inSheet = !!btn.closest('.sheet');
    if (inSheet) closeSheet();
    setTimeout(() => { btn.dataset.state = ''; btn.innerHTML = label; btn.style.width = ''; }, inSheet ? 420 : 900);
    if (kind === 'weight') {
      const v = +form.querySelector('[data-stepper]').dataset.val;
      const prev = DATA.lastW.w;
      applyWeight(v, true);
      toast(`Вес ${fmt(v)} кг записан${override ? ' · с подтверждением' : ''}`, { undo: () => applyWeight(prev, false, true) });
    } else if (kind === 'meal') toast('Приём пищи записан');
    else if (kind === 'dose') toast('Инъекция записана · Плечо Л');
    else toast('Замер записан · жир пересчитан');
  }
  function applyWeight(v, addFeed, undo) {
    DATA.lastW.w = v;
    INSTANCES.forEach(inst => {
      inst.el.querySelectorAll('[data-fig="weight"] .odo').forEach(o => setOdo(o, fmt(v)));
      inst.el.querySelectorAll('[data-rs-weight]').forEach(b => b.firstChild.nodeValue = fmt(v));
      inst.el.querySelectorAll('.today-log .sub').forEach(b => b.textContent = `сейчас ${fmt(v)} · ${DATA.now}`);
      const feed = inst.el.querySelector('[data-feed]');
      if (feed && addFeed) {
        feed.insertAdjacentHTML('beforeend', `<div class="feed-row enter" data-new><span class="time">${DATA.now}</span><span class="rail-dot"><span class="dot good"></span></span><div><div class="tx">Вес ${fmt(v)} кг</div><div class="dt">вручную</div></div></div>`);
      }
      if (feed && undo) feed.querySelector('[data-new]:last-child')?.remove();
    });
  }

  /* ---------- Toast ---------- */
  function toast(text, { undo, icon = 'check' } = {}) {
    const box = el.querySelector('.toasts');
    const t = document.createElement('div'); t.className = 'toast';
    t.innerHTML = `${ic(icon).replace('<svg', icon === 'info' ? '<svg style="color:var(--muted)"' : '<svg')}<span>${text}</span>${undo ? '<button class="tb">Отменить</button>' : '<span style="width:6px"></span>'}`;
    box.appendChild(t);
    anim(t, [{ opacity: 0, transform: 'translateY(16px) scale(.97)' }, { opacity: 1, transform: 'none' }], { duration: 420 });
    const kill = () => { if (!t.isConnected) return; anim(t, [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(8px)' }], { duration: 220, easing: 'ease-in' }).finished.then(() => t.remove()); };
    if (undo) t.querySelector('.tb').onclick = () => { undo(); kill(); };
    setTimeout(kill, undo ? 4200 : 2600);
  }
  const wait = (ms) => new Promise(r => setTimeout(r, ms));

  /* ---------- Labs interactions ---------- */
  function selectMarker(id, row) {
    const s = st.els[current()];
    const phone = !isDesk();
    if (phone) {
      const was = row.classList.contains('sel');
      s.querySelectorAll('.mk').forEach(r => { r.classList.remove('sel'); r.querySelector('.collapse')?.classList.remove('open'); });
      if (!was) {
        row.classList.add('sel'); row.querySelector('.collapse').classList.add('open'); st.labSel = id;
        const box = row.querySelector('[data-chart="mk"]'); box.dataset.cid = box.dataset.cid || ++CID;
        markerChart(box, DATA.labs.find(m => m.id === id), { intro: true, phone: true });
      }
      return;
    }
    st.labSel = id;
    s.querySelectorAll('.mk').forEach(r => r.classList.toggle('sel', r === row));
    const wrap = s.querySelector('[data-labside-wrap]');
    const old = wrap.firstElementChild;
    anim(old, [{ opacity: 1 }, { opacity: 0, transform: 'translateY(-4px)' }], { duration: 120, easing: 'linear' }).finished.then(() => {
      wrap.innerHTML = labSide(DATA.labs.find(m => m.id === id));
      const n = wrap.firstElementChild;
      const box = n.querySelector('[data-chart="mkside"]'); box.dataset.cid = ++CID;
      markerChart(box, DATA.labs.find(m => m.id === id), { intro: true, phone: false });
      anim(n, [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: 360, easing: EASE_OUT }).finished.then(() => n.getAnimations().forEach(a => a.cancel()));
    });
  }
  function filterMarkers(f, btn) {
    const s = st.els[current()];
    btn.parentElement.querySelectorAll('.filter').forEach(b => b.classList.toggle('on', b === btn));
    s.querySelectorAll('.mk').forEach((r, i) => {
      const show = f === 'all' || (f === 'out' ? r.dataset.status !== 'ok' : r.dataset.group === f);
      if (show && r.hidden) { r.hidden = false; anim(r, [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: 320, delay: i * 25, easing: EASE_OUT }).finished.then(() => r.getAnimations().forEach(a => a.cancel())); }
      else if (!show) r.hidden = true;
    });
  }

  /* ---------- Delegated clicks ---------- */
  el.addEventListener('click', (e) => {
    const t = e.target;
    const a = t.closest('a[href="#"]'); if (a) e.preventDefault();
    let n;
    if ((n = t.closest('[data-close]'))) return closeSheet();
    if ((n = t.closest('[data-logtab]'))) return setLogTab(n.dataset.logtab);
    if ((n = t.closest('[data-log]'))) { if (el.classList.contains('sheet-open')) return closeSheet(); return openSheet(n.dataset.log); }
    if ((n = t.closest('[data-save]'))) return save(n);
    if ((n = t.closest('[data-override]'))) return save(n.closest('[data-logform]').querySelector('[data-save]'), true);
    if ((n = t.closest('[data-fix]'))) { const f = n.closest('[data-logform]'); closeConflict(f); const stp = f.querySelector('[data-stepper]'); setStep(stp, DATA.lastW.w); return; }
    if ((n = t.closest('[data-stepval]'))) return editValue(n);
    if ((n = t.closest('[data-back]'))) return pop();
    if ((n = t.closest('[data-tab]'))) {
      const tab = n.dataset.tab, root = TAB_ROOT[tab];
      if (tabOf(st.stack[0]) === tab) { if (st.stack.length > 1) return popToRoot(); return scrollTop(); }
      return go(root, { mode: 'tab' });
    }
    if ((n = t.closest('[data-go]'))) {
      const id = n.dataset.go;
      if (n.hasAttribute('data-chip')) return go(id, { mode: 'replace' });
      const shared = n.hasAttribute('data-shared') ? n.querySelector('[data-fig]') : null;
      const sameTab = tabOf(id) === tabOf(current()) && current() !== 'today' && current() !== 'more';
      return go(id, { mode: sameTab ? 'replace' : 'push', shared });
    }
    if ((n = t.closest('[data-range]'))) {
      st.range = n.dataset.range;
      n.parentElement.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === n));
      placeInks(n.closest('.panel'));
      const box = n.closest('.panel').querySelector('[data-chart="weight"]');
      weightChart(box, { range: st.range, intro: true, phone: !isDesk() });
      return;
    }
    if ((n = t.closest('[data-mk]'))) { if (t.closest('.mk-detail')) return; return selectMarker(n.dataset.mk, n); }
    if ((n = t.closest('[data-filter]'))) return filterMarkers(n.dataset.filter, n);
    if ((n = t.closest('[data-sync]'))) {
      if (n.classList.contains('busy')) return;
      n.classList.add('busy', 'spin'); n.querySelector('svg').style.animation = 'spin 900ms linear infinite';
      setTimeout(() => { n.classList.remove('busy', 'spin'); n.querySelector('svg').style.animation = ''; toast('Garmin: новых данных нет · 08:14'); }, 1400);
      return;
    }
    if ((n = t.closest('[data-upload]'))) return toast('Выбор файла — в макете не подключён', { icon: 'info' });
    if ((n = t.closest('[data-soon]'))) return toast(`«${n.dataset.soon}» в макет не входит`, { icon: 'info' });
    if ((n = t.closest('.opt'))) { n.parentElement.querySelectorAll('.opt').forEach(o => o.classList.toggle('on', o === n)); return; }
  });
  async function popToRoot() {
    while (st.stack.length > 2) { const x = st.stack.splice(st.stack.length - 2, 1)[0]; st.els[x]?.remove(); delete st.els[x]; }
    return pop();
  }

  /* ---------- Resize: charts are drawn at real width ---------- */
  let lastW = 0, lastDesk = null;
  new ResizeObserver(() => {
    const w = el.clientWidth; if (!w || w === lastW) return; lastW = w;
    const d = isDesk();
    if (lastDesk !== null && d !== lastDesk) reset(current());
    lastDesk = d;
    const s = st.els[current()]; if (s) hydrate(s);
    syncNav(); placeInks();
  }).observe(el);

  function reset(id = 'today', { intro = false } = {}) {
    Object.values(st.els).forEach(n => n.remove()); st.els = {}; st.stack = [];
    const s = build(id, { intro }); st.els[id] = s; st.stack = [id];
    hydrate(s, { intro });
    syncNav(true);
    if (intro && id === 'today') rollFigures(s);
  }
  function rollFigures(s) {
    // Figures arrive as the sentence finishes: an odometer, staggered by figure.
    const odos = s.querySelectorAll('.today-figs .odo');
    setTimeout(() => odos.forEach((o, i) => setTimeout(() => { o.classList.remove('pre'); setOdo(o, o.dataset.odo, 40); }, i * 70)), RM ? 0 : 420);
  }
  function replay() { closeSheet(); reset('today', { intro: true }); }

  return app;
}

/* Keyboard: N opens the log on the desktop instance, Esc closes */
document.addEventListener('keydown', (e) => {
  if (e.target.closest('input, textarea')) return;
  const desk = INSTANCES.find(i => i.el.clientWidth >= 768 && i.el.offsetParent) || INSTANCES[0];
  if ((e.key === 'n' || e.key === 'т') && !e.metaKey && !e.ctrlKey) { desk.openSheet('weight'); }
  if (e.key === 'Escape') INSTANCES.forEach(i => i.closeSheet());
});
