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


/* Added to the family for the remaining screens: same grid, same stroke, same quiet fill. */
Object.assign(I, {
  edit: '<path class="ds" d="M4.6 19.4l.9-4.1 9.6-9.6a2.1 2.1 0 0 1 3 3l-9.6 9.6z"/><path d="M13.3 7.5l3.2 3.2"/>',
  trash: '<path class="ds" d="M6.6 8h10.8l-.8 10.1a1.8 1.8 0 0 1-1.8 1.7H9.2a1.8 1.8 0 0 1-1.8-1.7z"/><path d="M4.5 8h15M9.6 8V5.7a1.2 1.2 0 0 1 1.2-1.2h2.4a1.2 1.2 0 0 1 1.2 1.2V8M10.3 11.6v4.6M13.7 11.6v4.6"/>',
  copy: '<rect class="ds" x="8.6" y="8.6" width="11" height="11" rx="2.6"/><path d="M15.4 8.6V6.7a2.2 2.2 0 0 0-2.2-2.2H6.7a2.2 2.2 0 0 0-2.2 2.2v6.5a2.2 2.2 0 0 0 2.2 2.2h1.9"/>',
  download: '<path d="M12 4.5V15M7.8 11.3 12 15.5l4.2-4.2M4.5 15.2v2.3A2.5 2.5 0 0 0 7 20h10a2.5 2.5 0 0 0 2.5-2.5v-2.3"/>',
  link: '<path d="M10.3 13.7a3.6 3.6 0 0 0 5.1 0l3-3a3.6 3.6 0 0 0-5.1-5.1l-1 1M13.7 10.3a3.6 3.6 0 0 0-5.1 0l-3 3a3.6 3.6 0 0 0 5.1 5.1l1-1"/>',
  lock: '<rect class="ds" x="5.5" y="10.5" width="13" height="9.5" rx="2.6"/><path d="M8.6 10.5V8a3.4 3.4 0 0 1 6.8 0v2.5M12 14.3v2"/>',
  archive: '<path class="ds" d="M5 8h14v9.5a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z"/><path d="M4 5.6A1.6 1.6 0 0 1 5.6 4h12.8A1.6 1.6 0 0 1 20 5.6V8H4zM10 12h4"/>',
  image: '<rect class="ds" x="4" y="5" width="16" height="14" rx="3"/><circle cx="9" cy="10" r="1.5"/><path d="M4.5 16.6l4.2-3.7 3 2.6 2.6-2.2 5.2 4.3"/>',
  chevD: '<path d="M5.5 9.5 12 16l6.5-6.5"/>',
  wifiOff: '<path d="M4.5 4.5l15 15M5.2 9.6a11 11 0 0 1 3.8-2.1M18.8 9.6a11 11 0 0 0-5.4-3M8.4 13.4a6.4 6.4 0 0 1 2.5-1.2M15.6 13.4a6.4 6.4 0 0 0-1.7-1.1M12 17h.01"/>',
  // HRT: an ampoule with a crimped cap
  hrt: '<path class="ds" d="M8.5 9.6h7v8.2a2.4 2.4 0 0 1-2.4 2.4h-2.2a2.4 2.4 0 0 1-2.4-2.4z"/><path d="M9.6 9.6V7.8h4.8v1.8M8.4 6.2h7.2M8.5 13.4h7M11 16.7h2"/>',
  // interactions: two circles and the overlap they share
  interactions: '<circle cx="9.2" cy="12" r="5.7"/><circle cx="14.8" cy="12" r="5.7"/><path class="d2" d="M12 7.04A5.7 5.7 0 0 0 12 16.96 5.7 5.7 0 0 0 12 7.04z"/>',
  // signals: what was said to the bot, as a speech bubble with a small wave in it
  signals: '<path class="ds" d="M5.6 5h12.8A1.6 1.6 0 0 1 20 6.6v7.8a1.6 1.6 0 0 1-1.6 1.6H11l-4.4 3.5V16H5.6A1.6 1.6 0 0 1 4 14.4V6.6A1.6 1.6 0 0 1 5.6 5z"/><path d="M8.4 10.6v-1M11 12.2V8.2M13.6 11.2V9.4M16.2 10.6v-1"/>',
});

/* ---------- Navigation model — one registry, every surface reads it ---------- */
const RUBRICS = [
  { id: 'health', name: 'Здоровье', icon: 'heart', items: [['weight', 'Вес', 'scale'], ['recovery', 'Восстановление', 'pulse'], ['workouts', 'Тренировки', 'dumbbell'], ['nutrition', 'Питание', 'bowl']] },
  { id: 'markers', name: 'Маркеры', icon: 'drop', items: [['glp1', 'GLP-1', 'syringe'], ['hrt', 'ГЗТ / TRT', 'hrt'], ['labs', 'Анализы', 'flask'], ['genetics', 'Генетика', 'dna']] },
  { id: 'life', name: 'Образ жизни', icon: 'pill', items: [['supplements', 'Добавки', 'pill'], ['skincare', 'Уход за кожей', 'skincare'], ['interactions', 'Взаимодействия', 'interactions'], ['signals', 'Сигналы', 'signals']] },
  { id: 'journal', name: 'Журнал', icon: 'doc', items: [['timeline', 'Хронология', 'timeline'], ['reports', 'Отчёты', 'doc'], ['charts', 'Графики', 'chart']] },
];
// Screens that live one level below a section: the rail and the bottom bar keep the parent lit.
const PARENT = { measures: 'weight', sleep: 'recovery', nights: 'recovery', activities: 'recovery' };
// Pages the server renders on their own, without the app around them.
const BARE = new Set(['login', 'twofa', 'oauth', 'report', 'reportpw', 'gone', 'notfound', 'offline']);
const BUILT = new Set(['today', 'weight', 'recovery', 'glp1', 'labs', 'more',
  'measures', 'sleep', 'nights', 'activities', 'workouts', 'nutrition', 'hrt', 'genetics', 'supplements', 'skincare', 'interactions', 'signals',
  'timeline', 'reports', 'charts', 'share', 'settings', ...BARE]);
const TITLE = {
  today: 'Сегодня', more: 'Ещё', measures: 'Замеры', sleep: 'Ночь', nights: 'Сон', activities: 'Тренировки', share: 'Для врача', settings: 'Настройки',
  login: 'Вход', twofa: 'Подтверждение', oauth: 'Доступ', report: 'Отчёт врачу', reportpw: 'Документ под паролем', gone: 'Ссылка недоступна', notfound: '404', offline: 'Офлайн',
};
RUBRICS.forEach(r => r.items.forEach(([id, t]) => TITLE[id] = t));
const navId = (id) => PARENT[id] || id;
const rubricOf = (id) => RUBRICS.find(r => r.items.some(i => i[0] === navId(id)));
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

function hypChart(box, { intro, data = DATA.hyp, start = 23 * 60 + 40 }) {
  const W = box.clientWidth; if (!W) return;
  const H = 132, T = 4, B = 22, L = 64;
  const rows = [['Бодрств.', 'var(--bad)'], ['REM', 'var(--violet)'], ['Лёгкий', 'var(--cool)'], ['Глубокий', 'var(--deep)']];
  const rh = (H - T - B) / 4, n = data.length, bw = (W - L) / n;
  let s = `<svg width="${W}" height="${H}">`;
  rows.forEach(([l], i) => {
    s += `<text class="ax" x="0" y="${T + rh * i + rh / 2 + 4}">${l}</text>`;
    s += `<line class="grid" x1="${L}" x2="${W}" y1="${T + rh * i + rh}" y2="${T + rh * i + rh}" stroke-dasharray="2 4"/>`;
  });
  // step outline
  let d = '';
  data.forEach((st, i) => { const y = T + rh * st + rh / 2; d += (i ? `L${L + i * bw} ${y}` : `M${L} ${y}`) + `L${L + (i + 1) * bw} ${y}`; });
  s += `<path class="draw" pathLength="1" d="${d}" fill="none" stroke="#F4F0F6" stroke-opacity=".28" stroke-width="1"/>`;
  // blocks
  let i = 0; let seg = '';
  while (i < n) {
    let j = i; while (j < n && data[j] === data[i]) j++;
    const st = data[i];
    seg += `<rect x="${(L + i * bw + .5).toFixed(1)}" y="${(T + rh * st + 4).toFixed(1)}" width="${Math.max(1, (j - i) * bw - 1).toFixed(1)}" height="${(rh - 8).toFixed(1)}" rx="3" fill="${rows[st][1]}" fill-opacity="${st === 3 ? .95 : .8}"/>`;
    i = j;
  }
  s += `<g class="late">${seg}</g>`;
  // every second hour from the first full hour after lights out
  for (let t = Math.ceil(start / 60) * 60; t - start <= n * 5 - 30; t += 120) {
    s += `<text class="ax" x="${L + (t - start) / 5 * bw}" y="${H - 5}" text-anchor="middle">${clock(t)}</text>`;
  }
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
   Helpers shared by the added screens
   ========================================================================== */
let VIEW = 'data';          // which state the screen being built is drawn in (see the viewer's "Состояние")
const chev = ic('chevR').replace('<svg', '<svg class="chev"');
const caret = ic('chevD').replace('<svg', '<svg class="caret"');
const dot = (tone, text, cls = '') => `<span class="badge${tone ? ' ' + tone : ''}${cls ? ' ' + cls : ''}">${text}</span>`;
const plur = (n, a, b, c) => { const m = n % 100, k = n % 10; return m > 10 && m < 20 ? c : k === 1 ? a : k > 1 && k < 5 ? b : c; };
const dW = (d) => `${WD[d.getDay()]}, ${dShort(d)}`;
const pips = (sev, l2) => `<span class="pips${l2 ? ' l2' : ''}" title="${sev} из 5">${[1, 2, 3, 4, 5].map(k => `<i class="${k <= sev ? 'on' : ''}"></i>`).join('')}</span>`;
const compo = (segs) => `<div class="compo" data-compo>${segs.map(([v, col]) => `<i style="flex:${v};background:${col}"></i>`).join('')}</div>`;
const meterH = (v, tone = '', zone = null) => `<div class="meter${tone ? ' ' + tone : ''}"><i style="width:${clamp(v, 0, 100)}%"></i>${zone ? `<span class="zone" style="left:${zone[0]}%;width:${zone[1] - zone[0]}%"></span>` : ''}</div>`;
const thead = (cls, cols) => `<div class="tbl-h ${cls}">${cols.map(c => `<span>${c}</span>`).join('')}</div>`;

function topbar(title, { back, right = '' } = {}) {
  return `<div class="topbar">
    <div class="topbar-l">${back ? `<button class="back" data-back>${ic('chevL')}<span>${back}</span></button>` : ''}</div>
    <div class="topbar-title">${title}</div>
    <div class="topbar-r">${right}</div>
  </div>`;
}
function mast(id, { actions = '', sub = '', crumb = null } = {}) {
  const r = rubricOf(id), nid = navId(id);
  const chips = r ? `<nav class="chips">${r.items.map(([cid, t]) => `<a href="#" class="chip${cid === nid ? ' on' : ''}" data-go="${cid}" data-chip>${t}</a>`).join('')}<i class="ink"></i></nav>` : '';
  const live = VIEW === 'refresh' ? `<span class="sync-live">${ic('sync')}обновляю…</span>` : '';
  return `<header class="mast">
    <div class="kicker"><span class="crumb">${crumb || (r ? r.name : 'Система')}</span>${live}</div>
    <div class="mast-actions">${actions}</div>
    ${chips}${sub}
  </header>`;
}
const secH = (h, meta = '') => `<div class="sec-h"><h2>${h}</h2>${meta}</div>`;

// One action, drawn twice: text + icon in the desktop masthead, an icon in the phone's top bar.
const act = (icon, label, attrs = '') => ({
  d: `<button class="ghost" ${attrs}>${ic(icon)}${label}</button>`,
  p: `<button class="ibtn" ${attrs} aria-label="${label}">${ic(icon)}</button>`,
});
function head(id, ctx, { h1, acts = [], sub = '', figs = null, right = '', crumb = null, title = null } = {}) {
  const fg = figs ? `<div class="figs inline${figs.length === 3 ? ' n3' : figs.length === 1 ? ' n1' : ''}">${figs.map(([v, l, s, tone, u]) => `<div class="f"><div class="f-v${tone ? ' ' + tone : ''}">${v}${u ? `<span class="u">${u}</span>` : ''}</div><div class="f-l">${l}</div>${s ? `<div class="f-s${tone === 'bad' ? ' bad' : ''}">${s}</div>` : ''}</div>`).join('')}</div>` : '';
  return `${topbar(title || TITLE[id] || h1, { back: ctx.back, right: right + acts.map(a => a.p).join('') })}
  ${mast(id, { actions: acts.map(a => a.d).join(''), sub, crumb })}
  <div class="headline"><h1 class="h1">${h1}</h1>${fg}</div>`;
}
// A second level of "where you are": same underline, a step quieter.
const subtabs = (items, on) => `<nav class="chips sub">${items.map(([id, t]) => `<a href="#" class="chip${id === on ? ' on' : ''}" data-go="${id}" data-chip>${t}</a>`).join('')}<i class="ink"></i></nav>`;
const paneTabs = (items, on) => `<nav class="chips sub">${items.map(([id, t]) => `<button class="chip${id === on ? ' on' : ''}" data-pane-btn="${id}">${t}</button>`).join('')}<i class="ink"></i></nav>`;
const paneSeg = (items, on) => `<div class="seg scroll"><i class="pill"></i>${items.map(([id, t]) => `<button data-pane-btn="${id}" class="${id === on ? 'on' : ''}">${t}</button>`).join('')}</div>`;
const GARMIN_TABS = [['recovery', 'Обзор'], ['nights', 'Сон'], ['activities', 'Тренировки']];
const WEIGHT_TABS = [['weight', 'Динамика'], ['measures', 'Замеры']];

// Form pieces — one label above, one field, no boxes around the group.
const fld = (label, control, hint = '') => `<label class="field"><span class="flabel">${label}</span>${control}${hint ? `<span class="fhint">${hint}</span>` : ''}</label>`;
const fldd = (label, control, hint = '') => `<div class="field"><span class="flabel">${label}</span>${control}${hint ? `<span class="fhint">${hint}</span>` : ''}</div>`;
const inp = (name, { type = 'text', ph = '', val = '', mode = '', cls = '' } = {}) => `<input class="input${cls ? ' ' + cls : ''}" name="${name}" type="${type}"${ph ? ` placeholder="${ph}"` : ''}${val !== '' ? ` value="${val}"` : ''}${mode ? ` inputmode="${mode}"` : ''}>`;
const area = (name, ph = '', rows = 2) => `<textarea class="input" name="${name}" rows="${rows}"${ph ? ` placeholder="${ph}"` : ''}></textarea>`;
const sel = (name, options, cur) => `<select class="input" name="${name}">${options.map(o => { const [v, t] = Array.isArray(o) ? o : [o, o]; return `<option value="${v}"${v === cur ? ' selected' : ''}>${t}</option>`; }).join('')}</select>`;
const g2 = (...a) => `<div class="g2">${a.join('')}</div>`;
const g3 = (...a) => `<div class="g3">${a.join('')}</div>`;
const optsH = (items, { multi = false, on = [] } = {}) => {
  const isOn = (k) => Array.isArray(on) ? on.includes(k) : on === k;
  return `<div class="opts"${multi ? ' data-multi' : ''}>${items.map(it => { const [k, t, x, h] = Array.isArray(it) ? it : [it, it]; return `<button type="button" class="opt${isOn(k) ? ' on' : ''}" data-k="${k}"${h ? ` data-hint="${h}"` : ''}>${t}${x ? `<span class="hint">${x}</span>` : ''}</button>`; }).join('')}</div>`;
};
const formPanel = (id, title, body, { open = false } = {}) => `<div class="collapse fp${open ? ' open' : ''}" data-collapse="${id}"><div><div class="panel fpanel"><div class="panel-h"><h3>${title}</h3><button class="ibtn" data-shut="${id}" aria-label="Закрыть">${ic('x')}</button></div><div class="form">${body}</div></div></div></div>`;
const saveBtn = (label, msg, { cls = 'btn w', icon = '', shut = '' } = {}) => `<button type="button" class="${cls}" data-fsave="${msg}"${shut ? ` data-fshut="${shut}"` : ''}>${icon ? ic(icon) : ''}${label}</button>`;
const emptyH = ({ icon = 'info', line, sub = '', act = '', tone = '' }) => `<div class="empty${tone ? ' ' + tone : ''}">${ic(icon)}<p>${line}${sub ? `<small>${sub}</small>` : ''}</p>${act}</div>`;
const fakeQR = () => { const q = rng(7), n = 25; let s = `<svg viewBox="0 0 ${n} ${n}" width="132" height="132" shape-rendering="crispEdges" fill="#1C1917">`; const fin = (x, y) => `<path d="M${x} ${y}h7v7h-7zM${x + 1} ${y + 1}v5h5v-5z" fill-rule="evenodd"/><rect x="${x + 2}" y="${y + 2}" width="3" height="3"/>`; for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) { const inF = (x < 8 && y < 8) || (x > n - 9 && y < 8) || (x < 8 && y > n - 9); if (!inF && q() > .52) s += `<rect x="${x}" y="${y}" width="1" height="1"/>`; } return s + fin(0, 0) + fin(n - 7, 0) + fin(0, n - 7) + '</svg>'; };

/* ==========================================================================
   Charts for the added screens
   ========================================================================== */
// A line chart for anything: several series, an optional second axis, flags for timeline events, the "now" dot.
function lineChart(box, o) {
  const W = box.clientWidth; if (!W) return;
  const H = o.h || (o.phone ? 176 : 232);
  const T = o.flags && o.flags.length ? 34 : 18, B = 24, L = o.y2 ? 30 : 0, R = 36;
  const main = o.series.filter(s => !s.y2), alt = o.series.filter(s => s.y2);
  const ys = main.flatMap(s => s.pts.map(p => p[1]));
  let lo = o.yMin != null ? o.yMin : Math.min(...ys), hi = o.yMax != null ? o.yMax : Math.max(...ys);
  if (o.band) { lo = Math.min(lo, o.band[0]); hi = Math.max(hi, o.band[1]); }
  const pad = (hi - lo) * .14 || 1; if (o.yMin == null) lo -= pad; if (o.yMax == null) hi += pad;
  const xs = o.series.flatMap(s => s.pts.map(p => p[0]));
  const x0 = o.x0 != null ? o.x0 : Math.min(...xs), x1 = o.x1 != null ? o.x1 : Math.max(...xs);
  const X = (v) => L + (v - x0) / (x1 - x0 || 1) * (W - L - R);
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  let a0 = 0, a1 = 1;
  if (alt.length) { const av = alt.flatMap(s => s.pts.map(p => p[1])); a0 = o.y2 && o.y2.min != null ? o.y2.min : Math.min(...av); a1 = o.y2 && o.y2.max != null ? o.y2.max : Math.max(...av); }
  const Y2 = (v) => T + (1 - (v - a0) / (a1 - a0 || 1)) * (H - T - B);
  const yf = o.yFmt || ((v) => fmt(v, v % 1 ? 1 : 0));
  const gid = 'lg' + (box.dataset.cid || (box.dataset.cid = ++CID));
  let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F4F0F6" stop-opacity=".08"/><stop offset="1" stop-color="#F4F0F6" stop-opacity="0"/></linearGradient></defs>`;
  if (o.band) s += `<rect x="${L}" y="${Y(o.band[1])}" width="${W - L - R + 6}" height="${Math.max(0, Y(o.band[0]) - Y(o.band[1]))}" rx="5" fill="#CEC6D7" fill-opacity=".07"/>`;
  niceTicks(lo, hi, o.phone ? 3 : 4).forEach(v => { s += `<line class="grid" x1="${L}" x2="${W - R + 6}" y1="${Y(v)}" y2="${Y(v)}"/><text class="ax" x="${W}" y="${Y(v) + 4}" text-anchor="end">${yf(v)}</text>`; });
  if (alt.length) niceTicks(a0, a1, 3).forEach(v => { s += `<text class="ax" x="0" y="${Y2(v) + 4}" style="fill:${alt[0].color}">${fmt(v, v % 1 ? 1 : 0)}</text>`; });
  (o.xt || []).forEach(([v, l], i, arr) => { s += `<text class="ax" x="${X(v)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === arr.length - 1 ? 'end' : 'middle'}">${l}</text>`; });
  // flags close to each other drop their label a line lower
  let fx = -1e9, fr = 0;
  (o.flags || []).forEach(([v, l]) => { const x = X(v); fr = x - fx < 110 ? 1 - fr : 0; fx = x; s += `<line x1="${x}" x2="${x}" y1="${T - 12 - (fr ? 0 : 12) + 12}" y2="${H - B}" stroke="#BCA4DC" stroke-opacity=".35" stroke-dasharray="2 3"/><text class="ax" x="${x + 5}" y="${T - 16 + fr * 13}" style="fill:var(--violet)">${l}</text>`; });
  (o.marks || []).forEach(v => { s += `<line x1="${X(v)}" x2="${X(v)}" y1="${H - B - 7}" y2="${H - B}" stroke="#BCA4DC" stroke-width="2" stroke-linecap="round"/>`; });
  let lastPt = null;
  o.series.forEach((sr, si) => {
    const P = sr.pts.map(p => [X(p[0]), (sr.y2 ? Y2 : Y)(p[1])]); if (!P.length) return;
    if (o.area && si === 0) s += `<path class="late" d="${linePath(P)}L${P[P.length - 1][0]} ${H - B}L${P[0][0]} ${H - B}Z" fill="url(#${gid})"/>`;
    const d = sr.smooth ? smoothPath(P) : linePath(P);
    if (P.length > 1 && sr.line !== false) s += `<path ${sr.dash ? '' : 'class="draw" pathLength="1" '}d="${d}" fill="none" stroke="${sr.color}" stroke-opacity="${sr.op || 1}" stroke-width="${sr.w || 2}" stroke-linecap="round" stroke-linejoin="round"${sr.dash ? ` stroke-dasharray="${sr.dash}"` : ''}/>`;
    if (sr.dots) s += `<g class="late">${P.map(p => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${sr.r || 2.6}" fill="${sr.color}" stroke="#221E27" stroke-width="1.5"/>`).join('')}</g>`;
    if (sr.labels) s += `<g class="late">${P.map((p, i) => `<text x="${p[0].toFixed(1)}" y="${(p[1] - 11).toFixed(1)}" text-anchor="middle" style="font:600 12px var(--f-display);fill:var(--fg-2);font-variant-numeric:tabular-nums">${(sr.lblFmt || yf)(sr.pts[i][1])}</text>`).join('')}</g>`;
    if (si === 0) lastPt = P[P.length - 1];
  });
  if (o.now && lastPt) s += `<g class="late"><circle class="now-ring" cx="${lastPt[0]}" cy="${lastPt[1]}" r="4" fill="#F5A623"/><circle cx="${lastPt[0]}" cy="${lastPt[1]}" r="4.5" fill="#F5A623" stroke="#221E27" stroke-width="2"/></g>`;
  s += `</svg><div class="scrub"></div><div class="scrub-dot"></div><div class="tip"></div>`;
  box.innerHTML = s; box.classList.toggle('intro', !!o.intro);
  const sc = o.series[0];
  box._scrub = sc.pts.map(p => ({ x: X(p[0]), y: Y(p[1]), label: o.tipLabel ? o.tipLabel(p) : dW(new Date(p[0])), val: (o.tipVal || yf)(p[1]) }));
}
// Hold a finger (or the pointer) on any chart: a rule, a dot, the reading.
function bindScrub(box) {
  if (box._bound || !box._scrub) return; box._bound = true;
  const show = (e) => {
    // the chart may have been redrawn since binding: look the parts up each time
    const sc = box.querySelector('.scrub'), dotEl = box.querySelector('.scrub-dot'), tip = box.querySelector('.tip'); if (!sc || !box._scrub) return;
    const r = box.getBoundingClientRect(), k = r.width / box.offsetWidth || 1, x = (e.clientX - r.left) / k;
    let b = box._scrub[0]; for (const p of box._scrub) if (Math.abs(p.x - x) < Math.abs(b.x - x)) b = p;
    sc.style.left = b.x + 'px'; dotEl.style.left = b.x + 'px'; dotEl.style.top = b.y + 'px'; tip.style.left = clamp(b.x, 70, box.offsetWidth - 70) + 'px';
    tip.innerHTML = `<b>${b.val}</b>${b.label}`; box.classList.add('scrubbing');
  };
  box.addEventListener('pointerdown', (e) => show(e));
  box.addEventListener('pointermove', (e) => { if (e.pointerType === 'mouse' || e.buttons) show(e); });
  ['pointerleave', 'pointerup', 'pointercancel'].forEach(t => box.addEventListener(t, () => box.classList.remove('scrubbing')));
}

// Thirty days of intake as thin columns; the corridor of the goal sits behind them.
function dayBars(box, days, { phone, sel, min, max }) {
  const W = box.clientWidth; if (!W) return;
  const H = phone ? 92 : 112, T = 6, B = 20, n = days.length, bw = W / n, top = 2700;
  const Y = (v) => T + (1 - Math.min(v, top) / top) * (H - T - B);
  let s = `<svg width="${W}" height="${H}"><rect x="0" y="${Y(max)}" width="${W}" height="${Y(min) - Y(max)}" rx="3" fill="#CEC6D7" fill-opacity=".08"/>`;
  days.forEach((d, i) => {
    const col = !d.cal ? '#433C4D' : d.cal > max ? '#FF8469' : d.cal >= min ? '#6FC58E' : '#857B93', on = d.k === sel;
    s += `<g class="dbar" data-day="${d.k}"><rect x="${(i * bw).toFixed(1)}" y="0" width="${bw.toFixed(1)}" height="${H - B}" fill="transparent"/>`
      + (d.cal ? `<rect x="${(i * bw + 1.2).toFixed(1)}" y="${Y(d.cal).toFixed(1)}" width="${(bw - 2.4).toFixed(1)}" height="${(H - B - Y(d.cal)).toFixed(1)}" rx="2" fill="${col}" fill-opacity="${on ? 1 : .7}"/>` : `<rect x="${(i * bw + 1.2).toFixed(1)}" y="${H - B - 2}" width="${(bw - 2.4).toFixed(1)}" height="2" rx="1" fill="${col}"/>`)
      + (on ? `<rect x="${(i * bw).toFixed(1)}" y="${H - B + 5}" width="${bw.toFixed(1)}" height="2.5" rx="1" fill="#F4F0F6"/>` : '') + `</g>`;
  });
  s += `<text class="ax" x="0" y="${H - 5}">${dShort(days[0].date)}</text><text class="ax" x="${W}" y="${H - 5}" text-anchor="end">сегодня</text>`;
  s += `<circle cx="${W - bw / 2}" cy="${H - B + 9}" r="0" fill="#F5A623"/></svg>`;
  box.innerHTML = s;
}

// Injection sites on the body: front and back, the darker the dot the more it was used. A record, not a suggestion.
function hrtMap(counts) {
  const body = `<circle cx="75" cy="20" r="12"/><path d="M52 40c6-5 14-7 23-7s17 2 23 7l12 30-8 3-9-22v44c0 4 1 8 2 12l-2 70h-12l-4-62h-4l-4 62H57l-2-70c1-4 2-8 2-12V51l-9 22-8-3z"/>`;
  const SITES = { delt_left: [44, 64, 0], delt_right: [106, 64, 0], ventroglute_left: [58, 108, 0], ventroglute_right: [92, 108, 0], quad_left: [66, 150, 0], quad_right: [84, 150, 0], vastus_lateralis_left: [58, 138, 0], vastus_lateralis_right: [92, 138, 0], glute_left: [63, 116, 1], glute_right: [87, 116, 1] };
  const mx = Math.max(...Object.values(counts), 1);
  const dots = (back) => Object.entries(SITES).filter(([, v]) => v[2] === back).map(([k, [x, y]]) => { const n = counts[k] || 0; return n ? `<circle cx="${x}" cy="${y}" r="6.5" fill="#BCA4DC" fill-opacity="${(.28 + .62 * n / mx).toFixed(2)}" stroke="none"/>` : `<circle cx="${x}" cy="${y}" r="4" stroke="#433C4D" stroke-dasharray="2 2.5"/>`; }).join('');
  return `<svg viewBox="0 0 320 190" width="100%" style="max-width:320px" fill="none" stroke="#433C4D" stroke-width="1.5"><g>${body}${dots(0)}</g><g transform="translate(160 0)">${body}${dots(1)}</g><text class="ax" x="75" y="188" text-anchor="middle" style="fill:var(--faint);stroke:none">спереди</text><text class="ax" x="235" y="188" text-anchor="middle" style="fill:var(--faint);stroke:none">сзади</text></svg>`;
}
// The skin: a face and a back, a dot where something was noted, its size the severity.
function faceMap(zones) {
  const Z = { 'лоб': [56, 32], 'щёки': [56, 64], 'подбородок': [56, 92], 'нос': [56, 58], 'спина': [206, 64] };
  const dots = Object.entries(zones).map(([z, sev]) => { const p = Z[z]; if (!p) return ''; const r = 5 + sev * 2; return `<circle cx="${p[0]}" cy="${p[1]}" r="${r}" fill="${sev >= 3 ? '#FF8469' : '#F0B24A'}" fill-opacity=".55" stroke="none"/>`; }).join('');
  return `<svg viewBox="0 0 260 130" width="100%" style="max-width:300px" fill="none" stroke="#433C4D" stroke-width="1.5"><path d="M56 12c20 0 32 16 32 40 0 26-12 52-32 52S24 78 24 52c0-24 12-40 32-40z"/><path d="M24 54c-6 0-7 10 0 12M88 54c6 0 7 10 0 12M48 84c5 4 11 4 16 0M50 44h1M62 44h1"/><path d="M186 30c12-8 40-8 52 0l16 12 6 34-12 4-8-20v56h-56V60l-8 20-12-4 6-34z" transform="translate(-30 -6) scale(.9)"/>${dots}<text class="ax" x="56" y="126" text-anchor="middle" style="fill:var(--faint);stroke:none">лицо</text><text class="ax" x="206" y="126" text-anchor="middle" style="fill:var(--faint);stroke:none">спина</text></svg>`;
}

/* ==========================================================================
   Screen templates
   ========================================================================== */

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
      <section class="sec">${secH('Последний скан', '<a href="#" class="link" data-go="measures" data-push>все замеры' + ic('chevR') + '</a>')}<p class="sub" style="margin:-4px 0 10px">InBody · 12 сентября</p>
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
  ${mast('recovery', { actions: `<button class="ghost" data-sync>${ic('sync')}Синхронизировать</button>`, sub: subtabs(GARMIN_TABS, 'recovery') })}
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
  const status = { weight: ['86,1 кг', ''], recovery: ['сон 82', ''], workouts: ['5 дн назад', ''], nutrition: ['420 ккал', ''], glp1: ['через 5 дн', ''], hrt: ['неделя 9 из 12', ''], labs: ['1 вне нормы', 'bad'], genetics: ['VCF · 14 правил', ''], supplements: ['3 активных', ''], skincare: ['утро ✓', ''], interactions: ['1 срабатывает', 'bad'], signals: ['сегодня', ''], timeline: ['', ''], reports: ['дайджест вс', ''], charts: ['4', ''] };
  return `
  ${topbar('Ещё')}
  <div class="kicker" style="margin-top:4px">Все разделы</div>
  <h1 class="h1">Ещё</h1>
  ${RUBRICS.map(r => `<section class="more-group"><h2>${r.name}</h2><div class="more-list">
    ${r.items.map(([id, t, icn]) => `<button class="more-row" data-go="${id}"><span class="mi">${ic(icn)}</span><span class="t">${t}</span><span class="s ${status[id]?.[1] || ''}">${status[id]?.[0] || ''}</span>${ic('chevR').replace('<svg', '<svg class="chev"')}</button>`).join('')}
  </div></section>`).join('')}
  <section class="more-group"><h2>Система</h2><div class="more-list">
    <button class="more-row" data-go="share"><span class="mi">${ic('clipboard')}</span><span class="t">Для врача</span><span class="s">отчёт по ссылке</span>${ic('chevR').replace('<svg', '<svg class="chev"')}</button>
    <button class="more-row" data-go="settings"><span class="mi">${ic('sliders')}</span><span class="t">Настройки</span><span class="s">16 из 16</span>${ic('chevR').replace('<svg', '<svg class="chev"')}</button>
  </div></section>`;
}


/* ==========================================================================
   Added screens — Health
   ========================================================================== */

/* ---------- Measures (a level under Weight) ---------- */
function scrMeasures(ctx) {
  const w = DATA.lastW.w, dW7 = DATA.ma7 - DATA.weekAgo;
  const fatOf = (s) => +s.cats[0][1].find(m => m[0] === 'Процент жира')[1].replace(',', '.');
  const rows = [...MEAS.navy.map(r => ({ d: r[0], neck: r[1], waist: r[2], fat: r[3], lbm: r[4], src: 'navy' })),
    ...MEAS.scans.map((s, i) => ({ d: s.date, neck: null, waist: null, fat: fatOf(s), lbm: i === 0 ? 71.8 : null, src: s.dev }))].sort((a, b) => b.d - a.d);
  const hist = rows.map(r => {
    const sub = [r.neck != null ? `шея ${fmt(r.neck)}` : null, r.waist != null ? `талия ${fmt(r.waist)}` : null, r.lbm != null ? `сухая масса ${fmt(r.lbm)} кг` : null].filter(Boolean).join(' · ');
    return `<div class="row t-meas" data-item${r.src === 'navy' ? ` data-mrow data-date="${r.d.toISOString().slice(0, 10)}" data-neck="${r.neck}" data-waist="${r.waist}"` : ''}>
      <div><div class="t">${dRel(r.d)}</div><div class="m hd">${sub || '—'}</div></div>
      <div class="v hs">${r.neck != null ? fmt(r.neck) : '—'}</div><div class="v hs">${r.waist != null ? fmt(r.waist) : '—'}</div>
      <div class="v">${fmt(r.fat)}<span class="u">%</span></div>
      <div class="v hs">${r.lbm != null ? `${fmt(r.lbm)}<span class="u">кг</span>` : '—'}</div>
      <div class="acts">${r.src === 'navy' ? `<button class="ibtn" data-edit-m aria-label="Редактировать">${ic('edit')}</button><button class="ibtn" data-del aria-label="Удалить">${ic('trash')}</button>` : `<span class="m">${r.src}</span>`}</div>
    </div>`;
  }).join('');
  const head6 = [['Скелетно-мышечная масса', '39,2', 'кг'], ['Процент жира', '18,4', '%'], ['Площадь висцерального жира', '96', 'см²'], ['ВнеКЖ / ОВО', '0,379', ''], ['Фазовый угол', '6,8', ''], ['Балл InBody', '78', '']];
  const scans = MEAS.scans.map((s, i) => `<div class="acc${i === 0 ? ' open' : ''}" data-acc data-item>
    <div class="row acc-h r-scan" role="button" tabindex="0" data-acc-h>${caret}<div><div class="t">${dLong(s.date)}</div><div class="m">${s.dev} · ${s.n} ${plur(s.n, 'метрика', 'метрики', 'метрик')}</div></div><span class="acts"><button class="ibtn" data-noop aria-label="Открыть фото листка">${ic('image')}</button><button class="ibtn" data-del aria-label="Удалить замер">${ic('trash')}</button></span></div>
    <div class="collapse${i === 0 ? ' open' : ''}"><div><div class="acc-b">${s.cats.map(([cat, ms]) => `<div class="cat">${cat}</div>${ms.map(([l, v, u, ref]) => `<div class="row kv"><span>${l}</span><span class="v">${v}${u ? `<span class="u">${u}</span>` : ''}</span><span class="m num hs">${ref}</span></div>`).join('')}`).join('')}</div></div></div>
  </div>`).join('');
  const noise = MEAS.noise.map(n => `<div class="row" data-item style="grid-template-columns:minmax(0,1fr) auto"><div><div class="t num">${dShort(n.s)}${n.e ? ' — ' + dShort(n.e) : ' <span class="m">(активен)</span>'}</div><div class="m">${n.why} · ${n.dir === 'up' ? '↑ Вес завышен' : '↓ Вес занижен'}</div></div><button class="ibtn" data-del aria-label="Удалить">${ic('trash')}</button></div>`).join('');
  const silh = (i) => `<svg viewBox="0 0 60 80" width="60" height="80" fill="none" stroke="currentColor" stroke-width="1.4" style="opacity:${(.5 + i * .12).toFixed(2)}"><circle cx="30" cy="15" r="8"/><path d="M14 30c5-4 10-5 16-5s11 1 16 5l6 20-6 2-4-13v29h-8l-2-22h-4l-2 22h-8V39l-4 13-6-2z"/></svg>`;
  const gallery = MEAS.photos.map((d, i) => `<button class="ph-tile" data-photo="${d.getTime()}"><span class="im">${silh(i)}</span><span class="m num">${dShort(d)}</span></button>`).join('');
  const body = `
    <div class="editing-tag" data-edit-tag hidden>${dot('violet', 'Правка')}<span class="m num" data-edit-date></span></div>
    <div data-pane="measure" class="form">
      ${fld('Дата', inp('date', { type: 'date', val: '2026-09-29' }))}
      ${g2(fld('Шея, см', inp('neck', { mode: 'decimal', ph: 'напр. 38.0' })), fld('Талия, см', inp('waist', { mode: 'decimal', ph: 'напр. 85.0' })))}
      ${fld('Заметка (необязательно)', area('note', 'Дополнительные детали…'))}
      <p class="sub" style="margin:0">Жир по формуле Navy пересчитается сразу: сейчас <span class="navyfig" data-navy>${odo('17,8')}</span> %</p>
      <div class="form-acts"><button type="button" class="btn grow" data-fsave="Замер записан · жир Navy 17,4 % (было 17,8)" data-roll="17,4">Сохранить замеры</button><button type="button" class="ghost" data-cancel-edit hidden>Отмена</button></div>
    </div>
    <div data-pane="noise" hidden class="form">
      ${g2(fld('Дата начала', inp('start_date', { type: 'date', val: '2026-09-29' })), fld('Окончание', inp('end_date', { type: 'date' })))}
      ${fld('Причина шума', inp('reason', { ph: 'например, загрузка креатином, избыток соли' }))}
      ${fldd('Направление искажения веса', optsH([['n', 'Неизвестно', '', 'Неизвестно / нейтрально'], ['u', '↑ Вес завышен', '', 'Креатин, соль, задержка воды — реальный прогресс лучше'], ['d', '↓ Вес занижен', '', 'Обезвоживание, болезнь — ситуация хуже, чем числа']], { on: 'n' }), 'Неизвестно / нейтрально')}
      ${saveBtn('Исключить период', 'Период исключён из трендов')}
    </div>
    <div data-pane="photo" hidden class="form">
      ${fld('Дата', inp('date', { type: 'date', val: '2026-09-29' }))}
      ${fldd('Файлы фотографий (до 5 шт.)', `<button type="button" class="drop slim" data-pick="IMG_2041.jpg, IMG_2042.jpg"><span class="ico">${ic('image')}</span><span><b>Выберите фото или перетащите сюда</b><small>Изображения · до 5 файлов · до 50 МБ каждое</small></span></button>`)}
      ${fld('Заметка (необязательно)', inp('note', { ph: 'Заметки о прогрессе…' }))}
      ${saveBtn('Загрузить фотографии', 'Фотографии загружены')}
    </div>
    <div data-pane="body" hidden class="form">
      <p class="sub" style="margin:0">Фото или PDF листка InBody / МедАсс</p>
      <div data-bs-up class="form">
        <button type="button" class="drop slim" data-pick="inbody-2026-09-29.pdf"><span class="ico">${ic('upload')}</span><span><b>Загрузить замер</b><small>Перетащите фото листка или нажмите, чтобы выбрать</small></span></button>
        <button type="button" class="btn w" data-bs-scan>Распознать замер</button>
      </div>
      <div data-bs-pre hidden class="form">
        <div><h4 class="fh">Проверьте распознанные значения</h4><p class="sub" style="margin:2px 0 0">Поправьте или удалите строки, затем сохраните.</p></div>
        ${g2(fld('Дата замера', inp('d', { type: 'date', val: '2026-09-29' })), fld('Прибор', inp('dev', { val: 'InBody 770', ph: 'InBody 770, МедАсс…' })))}
        <div class="pv"><div class="pv-h"><span>Метрика</span><span>Значение</span><span>Ед.</span><span></span></div>
          ${MEAS.preview.map(([l, v, u]) => `<div class="pv-r"><input class="input sm" value="${l}"><input class="input sm num" value="${v}" inputmode="decimal"><input class="input sm" value="${u}"><button class="ibtn" data-rm-row aria-label="Удалить строку">${ic('x')}</button></div>`).join('')}
        </div>
        <button type="button" class="ghost" data-add-row>${ic('plus')}Добавить метрику</button>
        <div class="form-acts"><button type="button" class="btn grow" data-fsave="Замер сохранён · 8 метрик" data-bs-save>Сохранить замер</button><button type="button" class="ghost" data-bs-cancel>Отмена</button></div>
      </div>
    </div>`;
  return `
  ${head('measures', ctx, {
    h1: 'Замеры', sub: subtabs(WEIGHT_TABS, 'measures'),
    figs: [[fmt(w), 'Последний вес', '', '', 'кг'], [fmt(DATA.ma7), 'Среднее за 7 дней', '', '', 'кг'], [fmt(DATA.bodyFat), 'Процент жира', 'Navy', '', '%'], [fmtS(dW7), 'Изменение за неделю', '', dW7 < 0 ? 'good' : 'bad', 'кг']],
  })}
  <div class="grid rev">
    <div class="c5">
      <section class="sec o1" data-panegroup>
        ${secH('Новая запись')}
        <div class="panel">${paneSeg([['measure', 'Замеры'], ['noise', 'Шум'], ['photo', 'Фото'], ['body', 'Состав тела']], 'measure')}<div class="pane-body">${body}</div></div>
      </section>
      <section class="sec o6">${secH('Исключённые периоды')}<div class="rows">${noise}</div></section>
      <section class="sec o7">${secH('Галерея прогресса')}<div class="ribbon">${gallery}</div></section>
    </div>
    <div class="c7">
      <section class="sec o2">${secH('Процент жира', '<span class="meta">два источника</span>')}
        <div class="panel bare"><div class="chart" data-chart="fat"></div>
        <div class="legend"><span><i></i>Navy, по замерам</span><span><i class="dots" style="background:var(--violet)"></i>InBody</span></div></div>
      </section>
      <section class="sec o3">${secH('Состав тела', '<span class="meta num">12 сентября · InBody 770</span>')}
        <div class="figs n3 six">${head6.map(([l, v, u]) => `<div class="f"><div class="f-v">${v}${u ? `<span class="u">${u}</span>` : ''}</div><div class="f-l">${l}</div></div>`).join('')}</div>
      </section>
      <section class="sec o4">${secH('История замеров')}
        ${thead('t-meas', ['Дата', 'Шея', 'Талия', 'Жир %', 'Сухая масса', ''])}
        <div class="rows">${hist}</div>
      </section>
      <section class="sec o5">${secH('История сканов состава тела')}<div class="rows">${scans}</div></section>
    </div>
  </div>`;
}

/* ---------- One night ---------- */
function scrSleep(ctx) {
  const n = nightsAll[ctx.st.night], older = ctx.st.night < nightsAll.length - 1, newer = ctx.st.night > 0;
  const [aw, rem, li, de] = n.stageMin;
  const nav = `<button class="ibtn" data-night="1" ${older ? '' : 'disabled'} aria-label="Предыдущая ночь">${ic('chevL')}</button><button class="ibtn" data-night="-1" ${newer ? '' : 'disabled'} aria-label="Следующая ночь">${ic('chevR')}</button>`;
  const deskAct = { d: `<button class="ibtn" data-night="1" ${older ? '' : 'disabled'} aria-label="Предыдущая ночь">${ic('chevL')}</button><button class="ghost" data-go="recovery">${ic('chevL')}К обзору</button><button class="ibtn" data-night="-1" ${newer ? '' : 'disabled'} aria-label="Следующая ночь">${ic('chevR')}</button>`, p: '' };
  const seg = (k, name, col, v) => v ? `<div><i style="background:${col}"></i>${name}<b>${k === 'awake' ? v + ' мин' : fmtHM(v)}</b></div>` : '';
  return `
  ${head('sleep', ctx, { h1: `${n.date.getDate()} ${MONTHS_G[n.date.getMonth()]}`, title: 'Ночь', acts: [deskAct], right: nav, sub: subtabs(GARMIN_TABS, 'nights'),
    figs: [[n.score, 'Оценка сна', `Норма: ${fmtHM(n.need)}`], [n.sleepHr, 'Пульс во сне', '', '', 'уд/мин'], [n.spo2, 'Мин. SpO₂', n.breath ? 'дыхание нарушено' : '', n.breath ? 'bad' : '', '%'], [(n.bbChange > 0 ? '+' : '') + n.bbChange, 'Body Battery восстановлено']] })}
  <p class="sub night-note num">Пробуждения: ${n.awake} · ворочания: ${n.restless}</p>
  <section class="sec">${secH('Фазы сна', `<span class="meta num">${clock(n.start)} → ${clock(n.end)}</span>`)}
    <div class="panel bare"><div class="chart" data-chart="nhyp"></div>${compo([[de, 'var(--deep)'], [li, 'var(--cool)'], [rem, 'var(--violet)'], [aw, 'var(--bad)']])}
    <div class="hyp-legend">${seg('deep', 'Глубокий', 'var(--deep)', de)}${seg('light', 'Лёгкий', 'var(--cool)', li)}${seg('rem', 'REM', 'var(--violet)', rem)}${seg('awake', 'Пробужд.', 'var(--bad)', aw)}</div></div>
  </section>
  <section class="sec">${secH('Показатели за ночь', `<div class="seg scroll" data-seg="sgroup"><i class="pill"></i>${[['pulse', 'Сердце'], ['breathing', 'Дыхание'], ['recovery', 'Восстановление'], ['movement', 'Движение']].map(([k, t]) => `<button data-sgroup="${k}" class="${k === ctx.st.sleepGroup ? 'on' : ''}">${t}</button>`).join('')}</div>`)}
    <div class="panel bare"><div class="chart" data-chart="ncurves"></div><div class="legend" data-slegend></div></div>
  </section>`;
}
const SGROUPS = {
  pulse: { list: [['pulse', 'Пульс, уд/мин', '#F4F0F6'], ['hrv', 'HRV, мс', '#BCA4DC']] },
  breathing: { list: [['spo2', 'SpO₂, %', '#6FB6C9'], ['resp', 'Дыхание, вдохов/мин', '#F4F0F6', true]], y2: { min: 8, max: 20 }, yMin: 88, yMax: 100 },
  recovery: { list: [['stress', 'Стресс', '#F0B24A'], ['bb', 'Body Battery', '#6FC58E']], yMin: 0, yMax: 100 },
  movement: { list: [['move', 'Движение', '#F4F0F6']], yMin: 0, yMax: 8 },
};
function sleepCurves(box, n, group, phone, intro) {
  const cur = nightCurves(n), g = SGROUPS[group], step = 5, len = n.hyp.length;
  const series = g.list.map(([k, , col, y2]) => ({ pts: cur[k].map((v, i) => [i * step, v]), color: col, w: 1.8, y2: !!y2, smooth: true }));
  const t0 = Math.ceil(n.start / 60) * 60, xt = [];
  for (let t = t0; t <= n.start + len * step; t += 120) xt.push([t - n.start, clock(t)]);
  lineChart(box, { series, x0: 0, x1: (len - 1) * step, xt, phone, intro, h: phone ? 190 : 260, yMin: g.yMin, yMax: g.yMax, y2: g.y2, tipLabel: (p) => clock(n.start + p[0]) });
  box.closest('.panel').querySelector('[data-slegend]').innerHTML = g.list.map(([, t, c]) => `<span><i style="background:${c}"></i>${t}</span>`).join('');
}

/* ---------- Nights list & activities (Garmin's two other tabs) ---------- */
const phaseBar = (n, lg) => `<div class="compo${lg ? '' : ' mini'}" data-compo>${[[n.stageMin[3], 'var(--deep)'], [n.stageMin[2], 'var(--cool)'], [n.stageMin[1], 'var(--violet)'], [n.stageMin[0], 'var(--bad)']].map(([v, c]) => v ? `<i style="flex:${v};background:${c}"></i>` : '').join('')}</div>`;
function scrNights(ctx) {
  const n0 = nightsAll[0];
  const list = nightsAll.map(n => `<a href="#" class="row r-night" data-go="sleep" data-push data-night-i="${n.i}">
    <span class="t num">${dW(n.date)}</span><span class="m num">${fmtHM(n.sleepMin)}</span><span class="v">${n.score}</span>${phaseBar(n)}
    <span class="m num hs">${n.awake}</span><span class="m num hs">${n.bbChange > 0 ? '+' : ''}${n.bbChange}</span>${chev}</a>`).join('');
  return `
  ${head('nights', ctx, { h1: 'Сон', sub: subtabs(GARMIN_TABS, 'nights') })}
  <section class="sec"><a href="#" class="hero-row" data-go="sleep" data-push data-night-i="0">
    <div class="hr-l"><div class="sub">Прошлая ночь</div><div class="hr-t">${dLong(n0.date)}</div><div class="sub num">${clock(n0.start)}–${clock(n0.end)} · ${fmtHM(n0.sleepMin)}</div></div>
    <div class="hr-f"><div class="f"><div class="f-v">${n0.score}</div><div class="f-l">Оценка сна</div></div><div class="f"><div class="f-v">${n0.awake}</div><div class="f-l">Пробуждения</div></div></div>${chev}
    ${phaseBar(n0, true)}</a></section>
  <section class="sec">${secH(`История ночей (${nightsAll.length})`)}
    ${thead('r-night', ['Дата', 'Длительность', 'Оценка', 'Фазы', 'Пробуждения', 'ΔBB', ''])}
    <div class="rows">${list}</div></section>`;
}
const ZC = ['var(--cool)', 'var(--good)', 'var(--violet)', 'var(--warn)', 'var(--bad)'];
function scrActivities(ctx) {
  const list = [...activities].sort((a, b) => b.at - a.at).map((a, i) => {
    const detail = a.zones || (a.splits && a.splits.length > 1) || a.teA != null || a.teN != null || a.elev != null || a.power != null;
    const zmax = a.zones ? Math.max(...a.zones.map(z => z[1])) || 1 : 1;
    const dtl = detail ? `<div class="collapse"><div><div class="acc-b act-d">
      <div class="kvs">${a.teA != null ? `<span>Аэробный эффект <b class="num">${fmt(a.teA)}</b></span>` : ''}${a.teN != null ? `<span>Анаэробный эффект <b class="num">${fmt(a.teN)}</b></span>` : ''}${a.elev != null ? `<span>Набор высоты <b class="num">${a.elev} м</b></span>` : ''}${a.power != null ? `<span>Средняя мощность <b class="num">${a.power} Вт</b></span>` : ''}</div>
      ${a.zones ? `<div class="cat">Пульсовые зоны</div>${a.zones.map(([z, m]) => `<div class="zone-row"><span class="m num">Z${z}</span><div class="zbar"><i style="width:${Math.round(m / zmax * 100)}%;background:${ZC[z - 1]}"></i></div><span class="m num">${m} мин</span></div>`).join('')}` : ''}
      ${a.splits && a.splits.length > 1 ? `<div class="cat">Круги</div><div class="spl"><div class="tbl-h spl-r on"><span>#</span><span>Дистанция</span><span>Время</span><span>Пульс</span></div>${a.splits.map(([k, km, s, hr]) => `<div class="spl-r num"><span>${k}</span><span>${fmt(km, 2)}</span><span>${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}</span><span>${hr}</span></div>`).join('')}</div>` : ''}
    </div></div></div>` : '';
    return `<div class="acc${detail ? '' : ' flat'}" data-acc>
      <div class="acc-h act-h"${detail ? ' role="button" tabindex="0" data-acc-h' : ''}>${detail ? caret : '<span class="caret-gap"></span>'}<div class="act-n"><div class="t">${a.name}</div>${a.type !== a.name ? `<div class="m">${a.type}</div>` : ''}</div><span class="m num">${a.at.getDate()} ${MONTHS_S[a.at.getMonth()]}, ${clock(a.at.getHours() * 60 + a.at.getMinutes())}</span></div>
      <div class="act-s"><div><b class="num">${a.min}</b><span>мин</span><small>Длительность</small></div><div><b class="num">${a.km ? fmt(a.km, 2) : '—'}</b>${a.km ? '<span>км</span>' : ''}<small>Дистанция</small></div><div><b class="num">${a.kcal != null ? fmtI(a.kcal) : '—'}</b><span>ккал</span><small>Калории</small></div><div><b class="num">${a.avg}/${a.max}</b><span>уд/мин</span><small>Пульс сред. / макс.</small></div></div>${dtl}</div>`;
  }).join('');
  return `
  ${head('activities', ctx, { h1: 'Активности', title: 'Активности', sub: subtabs(GARMIN_TABS, 'activities') })}
  <section class="sec"><div class="acts-list">${list}</div></section>`;
}

/* ---------- Workouts (Hevy) ---------- */
function hevySets(sets) { return sets.map(([t, kg, r]) => `<span class="set num">${t === 'w' ? '<i>W</i>' : ''}${fmt(kg, kg % 1 ? 1 : 0)} кг × ${r}</span>`).join(''); }
function hevyProgress(id) {
  const p = HEVY.progress[id], c = HEVY.catalog.find(x => x.id === id);
  const v = p.verdict ? dot(p.verdict.tone, p.verdict.msg) : '';
  let body;
  if (p.pts.length >= 2) body = `<div class="panel bare"><div class="chart" data-chart="hevy" data-exid="${id}"></div></div>`;
  else if (p.pts.length === 1) { const q = p.pts[0]; body = `<div class="figs n1"><div class="f"><div class="f-v">${fmt(q[1], q[1] % 1 ? 1 : 0)}<span class="u">кг × ${q[2]}</span></div><div class="f-l">Рабочий вес (1 сессия)</div><div class="f-s">${dShort(q[0])} · график появится со второй сессии</div></div></div>`; }
  else body = emptyH({ icon: 'chart', line: 'Нет данных по этому упражнению' });
  return `${secH(`Рабочий вес: ${c.title}`, v)}${body}${p.note ? `<p class="tech"><b>Техника</b>${p.note}</p>` : ''}`;
}
function scrWorkouts(ctx) {
  const sel = ctx.st.hevyEx;
  const wk = HEVY.workouts.map((w, i) => `<div class="acc${i === 0 ? ' open' : ''}" data-acc>
    <div class="row acc-h r-wk" role="button" tabindex="0" data-acc-h>${caret}<div><div class="t">${w.title}</div><div class="m">${dot('violet', `Программа ${w.program}`)}<span class="num"> · ${dW(w.date)}</span></div></div><span class="m num">${w.min} мин</span></div>
    <div class="collapse${i === 0 ? ' open' : ''}"><div><div class="acc-b">${w.ex.map(e => `<div class="ex"><button class="ex-t" data-ex="${e.id}">${e.title}</button><div class="sets">${hevySets(e.sets)}</div></div>`).join('')}</div></div></div>
  </div>`).join('');
  const cat = HEVY.catalog.map(c => `<button class="row pick${c.id === sel ? ' sel' : ''}" data-ex="${c.id}" style="grid-template-columns:minmax(0,1fr) auto"><div><div class="t">${c.title}</div><div class="m num">Сессий: <b>${c.sessions}</b></div></div><span class="m num">${dShort(c.last)}</span></button>`).join('');
  return `
  ${head('workouts', ctx, { h1: 'Тренировки', acts: [act('sync', 'Синхронизировать', 'data-sync="Hevy: обновлено сессий — 2 · 08:14"')],
    figs: [[HEVY.count, 'Всего тренировок'], [dShort(HEVY.last), 'Последняя', `синхронизировано ${HEVY.lastSync}`], [HEVY.catalog.length, 'Упражнений в базе']] })}
  <div class="grid">
    <div class="c7"><section class="sec o1">${secH('Недавние тренировки')}<div class="rows">${wk}</div></section></div>
    <div class="c5"><section class="sec o2">${secH('Упражнения')}<div class="rows" data-hevy-cat>${cat}</div></section></div>
  </div>
  <section class="sec o3" data-hevy-progress>${hevyProgress(sel)}</section>`;
}

/* ---------- Nutrition ---------- */
const dayAt = (k) => nutrHist.find(x => x.k === k) || { k, date: addDays(TODAY, -k), cal: 0, p: 0, f: 0, c: 0, meals: 0 };
function scrNutrition(ctx) {
  const k = ctx.st.nDay, day = dayAt(k), meals = day.cal ? mealsFor(day) : [];
  const under = day.cal < NUTR.calMin, over = day.cal > NUTR.calMax, tone = over ? 'bad' : under ? 'warn' : '';
  const scale = NUTR.calMax * 1.15, pF = day.cal ? day.f * 9 / day.cal * 100 : 0, pP = day.cal ? day.p * 4 / day.cal * 100 : 0, pC = day.cal ? Math.max(0, 100 - pF - pP) : 0;
  const dnav = `<div class="dnav"><button class="ibtn" data-nday="1" ${k >= 29 ? 'disabled' : ''} aria-label="Предыдущий день">${ic('chevL')}</button><span class="dl">${k === 0 ? 'Сегодня' : dLong(day.date)}</span><button class="ibtn" data-nday="-1" ${k === 0 ? 'disabled' : ''} aria-label="Следующий день">${ic('chevR')}</button>${k ? `<button class="ghost" data-nday-today>Сегодня</button>` : ''}</div>`;
  const rowsM = meals.map(m => `<div class="row r-meal" data-item><span class="m num tm">${m.time}</span><div><div class="t">${m.name}</div><div class="m hd num">Б ${m.p} · Ж ${m.f} · У ${m.c}</div></div><div class="v">${fmtI(m.cal)}<span class="u">ккал</span></div><span class="v hs">${m.p}</span><span class="v hs">${m.f}</span><span class="v hs">${m.c}</span><span class="acts"><button class="ibtn" data-open="meal-form" aria-label="Редактировать">${ic('edit')}</button><button class="ibtn" data-del aria-label="Удалить">${ic('trash')}</button></span></div>`).join('');
  const hist = nutrHist.map((d, i) => `<button class="row r-day${d.k === k ? ' sel' : ''}${i >= 8 ? ' more' : ''}" data-day="${d.k}"><span class="t num">${dW(d.date)}</span><span class="m num">${d.meals} ${plur(d.meals, 'приём', 'приёма', 'приёмов')} · белок ${d.p} г</span><span class="v ${d.cal > NUTR.calMax ? 'bad' : d.cal >= NUTR.calMin ? 'good' : ''}">${fmtI(d.cal)}<span class="u">ккал</span></span></button>`);
  const form = formPanel('meal-form', 'Новый приём пищи', `
    ${g2(fld('Дата', inp('date', { type: 'date', val: day.date.toISOString().slice(0, 10) })), fld('Время приёма', inp('time', { type: 'time', val: '13:00' })))}
    ${fld('Название блюда / приёма', inp('name', { ph: '2 яйца, тост, апельсиновый сок' }))}
    <div class="g4">${fld('Калории', inp('cal', { mode: 'numeric', ph: '0' }))}${fld('Белок (г)', inp('p', { mode: 'decimal', ph: '0' }))}${fld('Жиры (г)', inp('f', { mode: 'decimal', ph: '0' }))}${fld('Углеводы (г)', inp('c', { mode: 'decimal', ph: '0' }))}</div>
    ${fld('Заметка (необязательно)', area('note', 'Детали, ощущения…'))}
    <div class="form-acts">${saveBtn('Записать приём', 'Приём пищи записан', { cls: 'btn grow', shut: 'meal-form' })}<button type="button" class="ghost" data-shut="meal-form">Отмена</button></div>`);
  return `
  ${head('nutrition', ctx, { h1: 'Питание', acts: [act('plus', 'Добавить приём', 'data-open="meal-form"')],
    figs: [[fmtI(day.cal), 'Калории', `из ${fmtI(NUTR.calMin)}–${fmtI(NUTR.calMax)}`, over ? 'bad' : '', 'ккал'], [day.meals, 'Приёмы пищи']] })}
  ${form}
  <section class="sec o1">${secH('КБЖУ', dnav)}
    <div class="intake">
      <div class="mrows">
        <div class="mrow"><div class="mrow-h"><span class="t">Калории</span><span class="m num"><b>${fmtI(day.cal)}</b> / ${fmtI(NUTR.calMin)}–${fmtI(NUTR.calMax)} ккал</span></div>${meterH(day.cal / scale * 100, tone, [NUTR.calMin / scale * 100, NUTR.calMax / scale * 100])}</div>
        <div class="mrow"><div class="mrow-h"><span class="t">Белок</span><span class="m num"><b>${day.p}</b> / ${NUTR.protein} г</span></div>${meterH(day.p / NUTR.protein * 100, day.p >= NUTR.protein ? '' : 'warn')}</div>
      </div>
      <div class="mrow"><div class="mrow-h"><span class="t">Макросы</span><span class="m">% от калорий</span></div>
        ${day.cal ? compo([[pP, 'var(--good)'], [pF, 'var(--violet)'], [pC, 'var(--cool)']]) : '<div class="compo"></div>'}
        <div class="hyp-legend c3"><div><i style="background:var(--good)"></i>Белок<b class="num">${day.p} г <em>${Math.round(pP)} %</em></b></div><div><i style="background:var(--violet)"></i>Жиры<b class="num">${day.f} г <em>${Math.round(pF)} %</em></b></div><div><i style="background:var(--cool)"></i>Углеводы<b class="num">${day.c} г <em>${Math.round(pC)} %</em></b></div></div>
      </div>
    </div>
  </section>
  <div class="grid">
    <div class="c7"><section class="sec o2">${secH(k === 0 ? 'Приёмы за сегодня' : 'Приёмы', `<span class="meta">${meals.length} ${plur(meals.length, 'приём', 'приёма', 'приёмов')}</span>`)}
      ${meals.length ? thead('r-meal', ['Время', 'Блюдо', 'ккал', 'Б', 'Ж', 'У', '']) : ''}
      <div class="rows">${rowsM || `<div class="row"><span class="m">${k === 0 ? 'Сегодня приёмов пока нет.' : 'В этот день приёмов нет.'}</span></div>`}</div></section></div>
    <div class="c5"><section class="sec o3">${secH('Последние 30 дней', '<span class="meta">коридор цели — полоса</span>')}
      <div class="panel bare"><div class="chart" data-chart="bars"></div></div>
      <div class="rows daylist">${hist.join('')}</div><button class="ghost more-btn" data-more>${ic('chevD')}Показать ещё</button></section></div>
  </div>`;
}

/* ==========================================================================
   Added screens — Markers and Lifestyle
   ========================================================================== */

/* ---------- HRT / TRT: a record of what was taken ---------- */
function scrHrt(ctx) {
  const c = HRT.cycle, counts = {}; HRT.doses.forEach(d => { if (d.site) counts[d.site] = (counts[d.site] || 0) + 1; });
  const siteRows = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([s, n]) => `<div><span>${HRT.siteLabels[s]}</span><span class="num">${n}</span></div>`).join('');
  const items = HRT.items.map(it => `<div class="plan" data-item>
    <div class="row plan-h" style="grid-template-columns:minmax(0,1fr) auto"><div><div class="t">${it.name}</div><div class="m num">${it.dose} ${it.unit} / ${String(it.every).replace('.', ',')} д${it.from > 1 ? ` · с нед. ${it.from}` : ''}</div></div>
      <span class="acts"><button class="ghost" data-open="edit-${it.id}">Изменить</button><button class="ghost" data-del>Удалить</button></span></div>
    ${formPanel('edit-' + it.id, 'Изменить: ' + it.name, `${g2(fld('Доза', inp('dose', { mode: 'decimal', val: it.dose })), fld('Раз в N дней', inp('every', { mode: 'decimal', val: String(it.every).replace('.', ',') })))}${g2(fld('Длительность (дни)', inp('dur', { mode: 'numeric' })), fld('Неделя старта', inp('from', { mode: 'numeric', val: it.from })))}<div class="form-acts">${saveBtn('Сохранить', 'План обновлён', { cls: 'btn grow', shut: 'edit-' + it.id })}</div>`)}
  </div>`).join('');
  const planned = HRT.planned.map(([d, n, ds]) => `<div class="row" style="grid-template-columns:96px minmax(0,1fr) auto"><span class="m num">${dW(d)}</span><span>${n}</span><span class="v">${ds}</span></div>`).join('');
  const tpls = HRT.templates.map((t, i) => `<div class="acc" data-acc data-item>
    <div class="row acc-h" role="button" tabindex="0" data-acc-h style="grid-template-columns:16px minmax(0,1fr) auto">${caret}<div><div class="t">${t.name}</div><div class="m">${dot('violet', t.kind)} · ${t.items.length} ${plur(t.items.length, 'препарат', 'препарата', 'препаратов')}</div></div><span class="acts"><button class="ghost" data-copy="Шаблон скопирован">${ic('copy')}<span class="hs">Скопировать JSON</span></button><button class="ibtn" data-del aria-label="Удалить шаблон">${ic('trash')}</button></span></div>
    <div class="collapse"><div><div class="acc-b form">
      <p class="sub" style="margin:0">${t.items.map(([n, w]) => n + (w ? ` (с нед. ${w + 1})` : '')).join(' · ')}</p>
      <div class="g2 end">${fld('Начало', inp('start', { type: 'date', val: '2026-10-05' }))}${saveBtn('Запустить курс', 'Курс запущен', { cls: 'ghost' })}</div>
      ${fldd('Код для обмена (JSON)', `<textarea class="input mono" rows="4" readonly>{"format":"vitals.hrt_cycle_template","version":1,"name":"${t.name}","kind":"course","items":[${t.items.map(([n, w]) => `{"compound":"${n}","start_week":${w + 1}}`).join(',')}]}</textarea>`)}
    </div></div></div></div>`).join('');
  const doses = HRT.doses.map(d => `<div class="row r-dose" data-item><span class="m num">${dShort(d.date)}</span><div><div class="t">${d.name}</div><div class="m hd num">${d.dose}${d.ml ? ` · ${d.ml} мл` : ''}${d.site ? ' · ' + HRT.siteLabels[d.site] : ''}</div></div><span class="v hs">${d.dose}${d.ml ? `<span class="u">· ${d.ml} мл</span>` : ''}</span><span class="m hs">${[d.brand, d.lab].filter(Boolean).join(' / ')}${d.batch ? ` · ${d.batch}` : ''}</span><span class="m hs">${d.site ? HRT.siteLabels[d.site] : ''}</span><span class="acts"><button class="ibtn" data-del aria-label="Удалить приём">${ic('trash')}</button></span></div>`).join('');
  const side = HRT.sideEffects.map(e => `<div class="row" data-item style="grid-template-columns:minmax(0,1fr) auto auto"><div><div class="t">${e.name}</div><div class="m num">${dLong(e.date)}</div></div>${pips(e.sev, e.sev < 3)}<button class="ibtn" data-del aria-label="Удалить">${ic('trash')}</button></div>`).join('');
  const cyc = `<div class="cyc-meta">${dot('violet', c.kind)}<span class="t">${c.name}</span><span class="m num">${dShort(c.start)} — ${dShort(c.end)}</span></div>
    <p class="sub" style="margin:8px 0 0">Каденс анализов для этого типа: раз в ${c.cadence} дней.</p>
    <div class="mrow" style="margin-top:20px"><div class="mrow-h"><span class="m">Ход цикла</span><span class="m num">неделя ${c.week} из ${c.weeks}</span></div>
      <div class="meter weeks"><i style="width:${c.week / c.weeks * 100}%"></i>${Array.from({ length: c.weeks - 1 }, (_, i) => `<span class="tick" style="left:${(i + 1) / c.weeks * 100}%"></span>`).join('')}</div></div>
    <div class="mrow" style="margin-top:22px"><div class="mrow-h"><span class="m">Активный релиз (оценка)</span><span class="m num">Пик: <b data-peak></b> мг</span></div><div class="chart" data-chart="hrt"></div></div>
    <div class="rows plan-rows">${items}</div>
    <div class="row-acts"><button class="ghost" data-open="hrt-item">${ic('plus')}Добавить препарат</button><button class="ghost" data-open="hrt-tpl">${ic('doc')}Сохранить как шаблон</button><button class="ghost" data-open="hrt-cycle">${ic('cal')}Новый курс</button></div>
    ${formPanel('hrt-item', 'Добавить препарат в курс', `${fld('Препарат', sel('compound', ['Тестостерон ципионат', 'ХГЧ', 'Анастрозол']))}${g2(fld('Доза', inp('dose', { mode: 'decimal' })), fld('Раз в N дней', inp('every', { mode: 'decimal', val: '3,5' })))}${g2(fld('Неделя старта', inp('from', { mode: 'numeric', val: '1' })), fld('Длительность (дни)', inp('dur', { mode: 'numeric' })))}<div class="form-acts">${saveBtn('Добавить препарат', 'Препарат добавлен в план', { cls: 'btn grow', shut: 'hrt-item' })}</div>`)}
    ${formPanel('hrt-tpl', 'Сохранить план как шаблон', `${fld('Название шаблона', inp('name', { ph: c.name }))}<div class="form-acts">${saveBtn('Сохранить как шаблон', 'Шаблон сохранён', { cls: 'btn grow', shut: 'hrt-tpl' })}</div>`)}
    ${formPanel('hrt-cycle', 'Новый курс', `<p class="sub" style="margin:0">Начало нового открытого курса закроет текущий.</p>${fldd('Тип', optsH([['course', 'Курс', '', 'Любой протокол на экзогенных гормонах (ТРТ, загруз, вечка — уточните в названии); анализы раз в квартал.'], ['pct', 'ПКТ', '', 'Послекурсовая терапия — восстановление своей секреции (SERM/ХГЧ); анализы раз в месяц.']], { on: 'course' }), 'Любой протокол на экзогенных гормонах (ТРТ, загруз, вечка — уточните в названии); анализы раз в квартал.')}${g2(fld('Название', inp('name')), fld('Начало', inp('start', { type: 'date', val: '2026-10-05' })))}<div class="form-acts">${saveBtn('Создать курс', 'Курс создан', { cls: 'btn grow', shut: 'hrt-cycle' })}</div>`)}
    <div class="sub-sec"><div class="flabel">Ближайшие (план)</div><div class="rows">${planned}</div></div>`;
  const doseForm = formPanel('hrt-dose', 'Записать приём', `
    ${fld('Препарат', `<select class="input" name="compound"><option value="" disabled selected>Выберите из каталога</option>${HRT.compounds.map(([g, l]) => `<optgroup label="${g}">${l.map(x => `<option>${x}</option>`).join('')}</optgroup>`).join('')}</select>`)}
    ${fld('Дата', inp('date', { type: 'date', val: '2026-09-29' }))}
    <div class="g4">${fld('Доза', inp('dose', { mode: 'decimal', ph: '250' }))}${fld('Ед.', sel('unit', ['мг', 'МЕ', 'мкг']))}${fld('Объём (мл)', inp('vol', { mode: 'decimal', ph: '1.0' }))}${fld('Конц. (мг/мл)', inp('conc', { mode: 'decimal', ph: '250' }))}</div>
    <div class="g4">${fld('Бренд', inp('brand'))}${fld('Лаба / UGL', inp('lab'))}${fld('Партия', inp('batch'))}${fld('Место', sel('site', ['—', ...Object.values(HRT.siteLabels)]))}</div>
    ${fld('Заметка', inp('note'))}
    <div class="form-acts">${saveBtn('Сохранить', 'Приём записан', { cls: 'btn grow', shut: 'hrt-dose' })}</div>`);
  const sideForm = formPanel('hrt-side', 'Записать побочку', `${g2(fld('Дата', inp('date', { type: 'date', val: '2026-09-29' })), fld('Симптом', inp('name')))}${fldd('Тяжесть (1–5)', optsH([1, 2, 3, 4, 5].map(n => [String(n), String(n)]), { on: '3' }))}<div class="form-acts">${saveBtn('Записать побочку', 'Побочка записана', { cls: 'btn grow', shut: 'hrt-side' })}</div>`);
  return `
  ${head('hrt', ctx, { h1: 'ГЗТ / TRT', acts: [act('plus', 'Записать приём', 'data-open="hrt-dose"')],
    figs: [[dShort(HRT.last.date), 'Последний приём', HRT.last.name.replace('Тестостерон ', 'Тест. ')], [HRT.catalog, 'Препаратов'], [HRT.sideEffects.length, 'Побочные эффекты']] })}
  <p class="sub lede">Только учёт, без рекомендаций по дозам.</p>
  ${doseForm}
  <div class="grid">
    <div class="c7">
      <section class="sec o1">${secH('Активный курс', `<span class="acts"><button class="ghost" data-fsave="Курс закрыт">Закрыть</button><button class="ibtn" data-del aria-label="Удалить курс">${ic('trash')}</button></span>`)}${cyc}</section>
      <section class="sec o2">${secH('Журнал приёмов')}
        ${thead('r-dose', ['Дата', 'Препарат', 'Доза', 'Бренд', 'Место', ''])}<div class="rows">${doses}</div></section>
    </div>
    <div class="c5">
      <section class="sec o3">${secH('Ротация мест инъекций')}<div class="sites hrt-sites"><div>${hrtMap(counts)}</div><div class="site-list">${siteRows}</div></div></section>
      <section class="sec o4">${secH('Побочные эффекты', `<button class="ghost" data-open="hrt-side">${ic('plus')}Записать</button>`)}${sideForm}<div class="rows">${side}</div></section>
      <section class="sec o5">${secH('Шаблоны курсов')}<div class="rows">${tpls}</div>
        <div class="acc imp" data-acc><div class="acc-h imp-h" role="button" tabindex="0" data-acc-h>${caret}<span>Импорт чужого шаблона</span></div><div class="collapse"><div><div class="acc-b form"><textarea class="input mono" rows="4" placeholder='{"format": "vitals.hrt_cycle_template", ...}'></textarea>${saveBtn('Импортировать', 'Шаблон импортирован', { cls: 'ghost' })}</div></div></div></div></section>
    </div>
  </div>`;
}

/* ---------- Genetics ---------- */
function varRow(v, open) {
  const risk = !!v.marker;
  return `<div class="acc${open ? ' open' : ''}" data-acc data-g="${VGROUP[v.dom]}">
    <div class="row acc-h r-var" role="button" tabindex="0" data-acc-h>${caret}
      <div><div class="t"><span class="gene">${v.gene}</span> <span class="m num">${v.rsid}</span></div><div class="m">${v.impact}</div></div>
      ${dot(risk ? 'warn' : '', risk ? 'маркер конфликта' : 'инфо', 'hs')}<span class="gt num">${v.gt}</span></div>
    <div class="collapse${open ? ' open' : ''}"><div><div class="acc-b var-d"><div class="cat">Трактовка</div><p>${v.interp}</p>${v.action ? `<div class="alert ${risk ? 'warn' : 'info'}">${ic(risk ? 'warn' : 'info')}<div><b>Рекомендация</b><br>${v.action}</div></div>` : ''}</div></div></div></div>`;
}
function scrGenetics(ctx) {
  const list = VARIANTS.map((v, i) => varRow(v, i === 0)).join('');
  const cat = VARIANTS.map(v => `<div class="row r-cat" data-item><div><div class="t">${v.gene}</div><div class="m num">${v.rsid}</div></div><span class="v num">${v.gt}</span><span class="m hs">${v.marker || '—'}</span><div class="cat-i"><div class="t2">${v.impact}</div><div class="m">${v.interp}</div>${v.action ? `<div class="m ok">${v.action}</div>` : ''}</div><button class="ibtn" data-del aria-label="Удалить">${ic('trash')}</button></div>`).join('');
  return `
  ${head('genetics', ctx, { h1: 'Генетика', figs: [[VARIANTS.length, 'Интерпретировано']] })}
  <div class="alert info imp-ok" data-imp-ok hidden>${ic('check')}<div><b>Импортировать</b> · Загружено вариантов: <b class="num">14</b>, с конфликт-маркером: <b class="num">4</b>.</div></div>
  <div data-panegroup>
    <div class="pane-bar">${paneSeg([['profile', 'Профиль'], ['admin', 'Импорт и каталог']], 'profile')}</div>
    <div data-pane="profile">
      <div class="filters" data-gfilters><button class="filter on" data-gf="all">Все</button><button class="filter" data-gf="sup">Добавки и витамины</button><button class="filter" data-gf="sport">Спорт и вес</button><button class="filter" data-gf="health">Здоровье и кожа</button></div>
      <div class="rows vars" data-vars>${list}</div>
    </div>
    <div data-pane="admin" hidden>
      <section class="sec">${secH('Импорт VCF', '<span class="meta">Genotek / 23andMe</span>')}
        <p class="sub" style="margin:0 0 12px;max-width:60ch">Загрузите файл .vcf (можно полный геном). В каталог попадают только интерпретируемые SNP из справочника, с русской трактовкой; по rsID повторная загрузка обновляет.</p>
        <div class="form"><button type="button" class="drop" data-pick="genome-2026.vcf"><span class="ico">${ic('upload')}</span><span><b>Выберите файл или перетащите сюда</b><small>VCF · до 50 МБ</small></span></button>
        <div class="form-acts">${optsH([['only', 'Только значимые']], { multi: true })}<button type="button" class="btn" data-vcf>Импортировать</button></div></div></section>
      <div class="grid"><div class="c5"><section class="sec">${secH('Добавить вариант')}<p class="sub" style="margin:0 0 12px">Поле marker — слаг для движка конфликтов (напр. hemochromatosis_carrier).</p>
        <div class="form">${g2(fld('Ген', inp('gene', { ph: 'HFE' })), fld('rsID', inp('rsid', { ph: 'rs1800562' })))}${g2(fld('Генотип', inp('gt', { ph: 'A/G' })), fld('Marker', inp('marker', { ph: 'hemochromatosis_carrier' })))}${g2(fld('Влияние', inp('impact', { ph: 'accumulation of iron' })), fld('Домен', inp('dom', { ph: 'supplements' })))}${fld('Трактовка', area('interp'))}${fld('Рекомендация', area('action'))}${saveBtn('Добавить вариант', 'Вариант добавлен', { cls: 'ghost' })}</div></section></div>
      <div class="c7"><section class="sec">${secH('Каталог вариантов')}${thead('r-cat', ['Ген', 'Генотип', 'Marker', 'Трактовка', ''])}<div class="rows">${cat}</div></section></div></div>
    </div>
  </div>`;
}

/* ---------- Supplements ---------- */
const TIMES = [['Утро', 'натощак', 'cool'], ['День', 'с едой', 'cool'], ['Вечер', '', 'violet'], ['Ночь', 'за 40–60 мин до сна', 'violet']];
function suppRow(s, archived) {
  return `<div class="row r-supp${archived ? ' dim' : ''}" data-item data-sid="${s.id}">
    <div><div class="t">${s.name}</div>${s.contra && !archived ? `<div class="flag">${ic('warn')}${s.contra}</div>` : ''}${s.note && !archived ? `<div class="m">${s.note}</div>` : ''}</div>
    <span class="v">${s.dose}</span>${s.ev ? dot(s.ev === 'A' ? 'good' : s.ev === 'B' ? 'cool' : '', `Tier ${s.ev}`) : '<span></span>'}
    <span class="acts"><button class="ibtn" data-supp-edit aria-label="Редактировать">${ic('edit')}</button><button class="ibtn" data-archive aria-label="${archived ? 'Восстановить' : 'В архив'}">${ic(archived ? 'sync' : 'archive')}</button><button class="ibtn" data-del aria-label="Удалить">${ic('trash')}</button></span></div>`;
}
function scrSupplements(ctx) {
  const on = SUPPS.filter(s => s.on), off = SUPPS.filter(s => !s.on);
  const groups = TIMES.map(([t, sub, tone]) => { const items = on.filter(s => s.timing === t);
    return `<section class="sec tgrp">${secH(`${dot(tone, '').replace('badge', 'dotonly')}${t}`, sub ? `<span class="meta">${sub}</span>` : '')}<div class="rows">${items.length ? items.map(s => suppRow(s)).join('') : '<div class="row"><span class="m">Нет активных добавок на этот тайминг</span></div>'}</div></section>`; }).join('');
  const form = formPanel('supp-form', 'Новая добавка', `
    ${fld('Название', inp('name', { ph: 'например, Креатин моногидрат' }))}
    ${g2(fld('Доза', inp('dose', { ph: 'например, 5 г или 1 капсула' })), fld('Тайминг', inp('timing', { ph: 'Утро, День, Вечер…' })))}
    ${fldd('Доказательность', optsH([['', '—'], ['A', 'Tier A'], ['B', 'Tier B'], ['C', 'Tier C']], { on: '' }))}
    ${fldd('Статус', optsH([['on', 'Активна']], { multi: true, on: ['on'] }))}
    ${fld('Противопоказания', area('contra', 'например, не сочетать с…'))}
    ${fld('Заметка', inp('note', { ph: '…' }))}
    <div class="form-acts">${saveBtn('Сохранить', 'Добавка сохранена', { cls: 'btn grow', shut: 'supp-form' })}<button type="button" class="ghost" data-shut="supp-form">Отмена</button></div>`);
  return `
  ${head('supplements', ctx, { h1: 'Добавки', acts: [act('plus', 'Новая добавка', 'data-open="supp-form"')], figs: [[on.length, 'Активные'], [SUPPS.length, 'Всего']] })}
  ${form}
  ${groups}
  <section class="sec"><div class="acc" data-acc><div class="acc-h arch-h" role="button" tabindex="0" data-acc-h>${ic('archive')}<h2>Архив <span class="m num">(${off.length})</span></h2>${caret}</div>
    <div class="collapse"><div><div class="rows arch">${off.map(s => suppRow(s, true)).join('')}</div></div></div></div></section>`;
}

/* ---------- Skincare ---------- */
const DAYS7 = [[1, 'Пн'], [2, 'Вт'], [3, 'Ср'], [4, 'Чт'], [5, 'Пт'], [6, 'Сб'], [0, 'Вс']];
const TIME_LBL = { morning: ['Утро', 'cool'], evening: ['Вечер', 'violet'], both: ['Утро + вечер', 'good'] };
function scrSkincare(ctx) {
  const P = SKIN.products, on = P.filter(p => p.on), todayDow = TODAY.getDay();
  const cell = (d, part) => { const l = on.filter(p => p.days.includes(d) && (p.time === part || p.time === 'both')); return l.length ? l.map(p => `<div class="pn">${p.name}</div>`).join('') : '<span class="m">—</span>'; };
  const sched = `<div class="sched"><table><thead><tr><th></th>${DAYS7.map(([d, n]) => `<th class="${d === todayDow ? 'now' : ''}">${n}</th>`).join('')}</tr></thead><tbody>
    ${[['morning', 'Утро', 'today'], ['evening', 'Вечер', 'pulse']].map(([k, l, ico]) => `<tr><td class="lbl">${ic(ico)}${l}</td>${DAYS7.map(([d]) => `<td class="${d === todayDow ? 'now' : ''}">${cell(d, k)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const schedM = `<div class="sched-m"><div class="opts" data-daypick>${DAYS7.map(([d, n]) => `<button class="opt${d === todayDow ? ' on' : ''}${d === todayDow ? ' today' : ''}" data-day-k="${d}">${n}</button>`).join('')}</div>
    ${DAYS7.map(([d]) => `<div class="day-pane" data-day-pane="${d}"${d === todayDow ? '' : ' hidden'}>${[['morning', 'Утро', 'today'], ['evening', 'Вечер', 'pulse']].map(([k, l, ico]) => `<div class="row" style="grid-template-columns:22px 1fr"><span class="mi">${ic(ico)}</span><div><div class="t">${l}</div><div class="m">${on.filter(p => p.days.includes(d) && (p.time === k || p.time === 'both')).map(p => p.name).join(' · ') || '—'}</div></div></div>`).join('')}</div>`).join('')}</div>`;
  const prods = P.map(p => `<div class="prod" data-item><div class="row prod-h" style="grid-template-columns:minmax(0,1fr) auto"><div><div class="t">${p.name}</div>${p.ing ? `<div class="m">Актив: ${p.ing}</div>` : ''}</div><span class="acts"><button class="ibtn" data-open="skin-form" aria-label="Редактировать">${ic('edit')}</button><button class="ibtn" data-del aria-label="Удалить">${ic('trash')}</button></span></div>
    <div class="prod-b"><div class="prod-tags">${dot('', p.type)}${dot(TIME_LBL[p.time][1], TIME_LBL[p.time][0])}<span class="m">Дни: ${p.days.length ? DAYS7.filter(([d]) => p.days.includes(d)).map(([, n]) => n).join(', ') : 'Нет'}</span></div>
    ${p.desc ? `<p class="prod-d">${p.desc}</p>` : ''}${p.use ? `<p class="m use">${ic('doc')}${p.use}</p>` : ''}</div></div>`).join('');
  const rules = SKIN.rules.map(r => `<div class="alert ${r.sev === 'block' ? 'block' : 'warn'}">${ic(r.hard ? 'block' : 'warn')}<div><b>${r.kind}</b><br>${r.msg}</div></div>`).join('');
  const logs = SKIN.logs.map(l => `<div class="row" data-item style="grid-template-columns:minmax(0,1fr) auto"><div><div class="t num">${dLong(l.date)}</div><div class="m">${l.acts.join(' · ')}${l.note ? `<br>${l.note}` : ''}</div></div><button class="ibtn" data-del aria-label="Удалить">${ic('trash')}</button></div>`).join('');
  const obs = SKIN.obs.map(o => `<div class="row" data-item style="grid-template-columns:minmax(0,1fr) auto"><div><div class="t num">${dLong(o.date)}</div><div class="m">Воспаление ${o.inf}/5 · Пигментация ${o.pih}/5 · Зона: ${o.zone}${o.note ? `<br>${o.note}` : ''}</div></div><button class="ibtn" data-del aria-label="Удалить">${ic('trash')}</button></div>`).join('');
  const days = [['1', 'Пн'], ['2', 'Вт'], ['3', 'Ср'], ['4', 'Чт'], ['5', 'Пт'], ['6', 'Сб'], ['0', 'Вс']];
  const form = formPanel('skin-form', 'Новое средство', `
    ${fld('Название', inp('name', { ph: 'например, Дифферин (Ретиноид)' }))}
    ${g2(fld('Тип / Категория', inp('type', { ph: 'Ретиноид, Пилинг…' })), fld('Действующее вещество', inp('ing', { ph: 'Адапален 0.1%' })))}
    ${fldd('Время нанесения', optsH([['m', 'Утро'], ['e', 'Вечер'], ['b', 'Утро + вечер']], { on: 'e' }))}
    ${fldd('Дни применения', optsH(days, { multi: true }))}
    ${fldd('Статус', optsH([['on', 'Активно']], { multi: true, on: ['on'] }))}
    ${fld('Описание (действие)', area('desc', '…'))}
    ${fld('Инструкции по применению', area('use', '…'))}
    <div class="form-acts">${saveBtn('Сохранить', 'Средство сохранено', { cls: 'btn grow', shut: 'skin-form' })}<button type="button" class="ghost" data-shut="skin-form">Отмена</button></div>`);
  return `
  ${head('skincare', ctx, { h1: 'Уход за кожей', title: 'Кожа', acts: [act('plus', 'Добавить средство', 'data-open="skin-form"')], figs: [[on.length, 'Активные средства'], [P.length, 'Средства']] })}
  ${form}
  <section class="sec">${secH('Схема ухода по дням недели', '<span class="meta">текущий день подсвечен</span>')}${sched}${schedM}</section>
  <div class="grid">
    <div class="c7"><section class="sec o1">${secH('Активные компоненты и средства', '<span class="meta">детали по применяемым продуктам</span>')}<div class="prods">${prods}</div></section></div>
    <div class="c5"><section class="sec o2">${secH('Правила безопасности', '<span class="meta">требования при работе с активами</span>')}
      <div class="alerts">${rules}<div class="alert">${ic('drop')}<div><b>Увлажнение и барьер кожи</b><br>Наносите крем через 15–20 минут после ретиноида. Если кожа «горит», шелушится или стянута — пауза 2–3 дня во всех активах, оставив только увлажнение.</div></div></div></section></div>
  </div>
  <div class="grid">
    <div class="c7"><section class="sec o3">${secH('Дневник ухода', '<span class="meta">одна запись на день — что реально нанесено</span>')}<div class="rows">${logs}</div></section></div>
    <div class="c5"><section class="sec o4">${secH('Наблюдения по коже', '<span class="meta">оценка состояния во времени</span>')}<div class="skinmap">${faceMap({ 'подбородок': 3, 'щёки': 2, 'лоб': 2 })}</div><div class="rows">${obs}</div></section></div>
  </div>`;
}

/* ---------- Interactions ---------- */
function ruleRow(r) {
  const tl = r.type === 'hard' ? 'Жёсткий блок' : r.type === 'timing' ? 'Разнесение по времени' : 'Мягкое предупреждение';
  return `<div class="row rule${r.firing ? ' firing' : ''}" data-item data-dom-a="${r.a}" data-dom-b="${r.b}" data-sev="${r.sev}">
    <div><div class="rl-h">${dot(r.sev === 'block' ? 'bad' : r.sev === 'warn' ? 'warn' : 'cool', tl)}${r.type === 'timing' ? `<span class="m">разнести на ${r.h} ч.</span>` : ''}${r.firing ? dot('bad', 'Срабатывает сейчас') : ''}</div>
      <p class="rl-m">${r.msg}</p>
      <div class="rl-t"><span class="m">${DOM_RU[r.a]} ↔ ${DOM_RU[r.b]}</span>${dot(r.ev === 'A' ? 'good' : r.ev === 'B' ? 'cool' : '', `Доказательность ${r.ev}`)}${r.src ? `<span class="m">Источник: ${r.src}</span>` : ''}</div></div>
    ${optsH([['on', r.on ? 'Включено' : 'Выключено']], { multi: true, on: r.on ? ['on'] : [] }).replace('class="opts"', 'class="opts tg"')}</div>`;
}
function scrInteractions(ctx) {
  const cats = Object.keys(CAT_RU).filter(c => RULES.some(r => r.cat === c));
  const doms = ['weight', 'glp1', 'workouts', 'garmin', 'labs', 'skincare', 'supplements', 'genetics', 'nutrition'];
  return `
  ${head('interactions', ctx, { h1: 'Взаимодействия', figs: [[RULES.length, 'Правил'], [RULES.filter(r => r.firing).length, 'Срабатывает сейчас', '', 'bad']] })}
  <div class="fgroup"><div class="flabel">Область</div><div class="filters" data-rf="dom"><button class="filter on" data-rf-k="all">Все</button>${doms.map(d => `<button class="filter" data-rf-k="${d}">${DOM_RU[d]}</button>`).join('')}</div></div>
  <div class="fgroup"><div class="flabel">Важность</div><div class="filters" data-rf="sev"><button class="filter on" data-rf-k="all">Все</button><button class="filter" data-rf-k="block">Блок</button><button class="filter" data-rf-k="warn">Предупреждение</button><button class="filter" data-rf-k="info">Инфо</button></div></div>
  <div data-rules>${cats.map(c => `<section class="sec rgrp" data-cat="${c}">${secH(CAT_RU[c], `<span class="meta num" data-cnt>${RULES.filter(r => r.cat === c).length}</span>`)}<div class="rows">${RULES.filter(r => r.cat === c).map(ruleRow).join('')}</div></section>`).join('')}</div>
  <div class="empty" data-rules-empty hidden>${ic('info')}<p>Нет правил под этот фильтр.</p></div>`;
}

/* ---------- Signals ---------- */
function scrSignals(ctx) {
  const mx = Math.max(...SIGFREQ.map(f => f.n));
  const freq = SIGFREQ.map(f => `<div class="row freq"><div><div class="t key">${f.key}</div>${f.alias.length ? `<div class="m key" title="Сохранено под этим ключом, схлопывается при чтении.">← ${f.alias.join(', ')}</div>` : ''}</div>
    <div class="fbar"><i style="width:${f.n / mx * 100}%"></i></div><span class="v num">${f.n}</span>
    <div class="fex m">${f.ex.length ? f.ex.map(e => `<div>${e}</div>`).join('') : '—'}</div></div>`).join('');
  const days = [...new Set(SIGNALS.map(s => s.d.getTime()))].map(t => new Date(t));
  const KIND = { state: ['Состояние', ''], symptom: ['Симптом', 'bad'], exposure: ['Воздействие', ''] };
  const feed = days.map(d => `<div class="tl-day"><div class="d num">${dShort(d)}</div><div class="tl-list">${SIGNALS.filter(s => s.d.getTime() === d.getTime()).map(s => `<div class="tl-ev" data-item><i class="tk" style="background:var(--violet)"></i><div><div class="ev-h">${dot(KIND[s.kind][1], KIND[s.kind][0])}<span class="t key">${s.key}</span>${s.raw !== s.key ? `<span class="m key" title="Сохранено под этим ключом, схлопывается при чтении.">← ${s.raw}</span>` : ''}${s.v != null ? `<span class="m num">${s.v}${s.unit ? ' ' + s.unit : ''}</span>` : ''}<span class="m num">${s.t}</span>${s.mis ? dot('bad', 'не то') : ''}</div>${s.note ? `<div class="m">${s.note}</div>` : ''}</div><button class="ibtn" data-del aria-label="Удалить">${ic('trash')}</button></div>`).join('')}</div></div>`).join('');
  return `
  ${head('signals', ctx, { h1: 'Сигналы', figs: [[SIGNALS.length, 'Записей'], [SIGFREQ.length, 'Ключей'], [SIGNALS.filter(s => s.mis).length, 'Промахи']] })}
  <p class="sub lede">Всё, что сказано боту мимоходом — сонливость, голова, кофе в 22 — разобрано в строки. Это тот слой, который объясняет цифры Garmin.</p>
  <section class="sec">${secH('Частота ключей')}<p class="sub" style="margin:-4px 0 6px;max-width:64ch">Что модель пишет на самом деле, вместе с ошибками — материал, по которому потом собирается реестр ключей.</p>
    ${thead('freq', ['Ключ', '', 'Раз', 'Как это было сказано'])}<div class="rows">${freq}</div></section>
  <section class="sec">${secH('Лента')}<div class="tl">${feed}</div></section>`;
}

/* ==========================================================================
   Added screens — Journal and System
   ========================================================================== */

/* ---------- Timeline ---------- */
function tlEvent(e) {
  const [kl, kt] = TL_KIND[e.kind] || ['Заметка', ''];
  return `<div class="tl-ev" data-item data-dom="${e.dom}"><i class="tk ${e.tone || kt}"></i><div>
    <div class="ev-h">${dot('', kl, 'plain')}<span class="ev-dom">${ic(DOM_ICON[e.dom] || 'timeline')}${DOM_RU[e.dom] || 'Хронология'}</span>${e.end ? `<span class="m num">→ ${dShort(e.end)}</span>` : ''}</div>
    <div class="t">${e.title}</div>${e.detail ? `<div class="m">${e.detail}</div>` : ''}</div>
    ${e.manual ? `<button class="ibtn" data-del aria-label="Удалить событие">${ic('trash')}</button>` : '<span></span>'}</div>`;
}
function scrTimeline(ctx) {
  const empty = VIEW === 'empty', list = empty ? [] : TL;
  const days = [...new Set(list.map(e => e.d.getTime()))].map(t => new Date(t));
  const doms = [...new Set(TL.map(e => e.dom))];
  const feed = days.map(d => `<div class="tl-day" data-tlday><div class="d num">${dW(d)}</div><div class="tl-list">${list.filter(e => e.d.getTime() === d.getTime()).map(tlEvent).join('')}</div></div>`).join('');
  const form = formPanel('tl-form', 'Новое событие', `
    ${fld('Название', inp('title', { ph: 'например, поездка в Грузию' }))}
    ${g2(fld('Дата', inp('date', { type: 'date', val: '2026-09-29' })), fld('Дата окончания', inp('end', { type: 'date' }), 'Оставьте пустым для события в один день.'))}
    ${g2(fld('Тип', sel('kind', Object.entries(TL_KIND).filter(([k]) => !['milestone', 'photo', 'side_effect'].includes(k)).map(([k, [t]]) => [k, t]), 'life_event')), fld('Относится к', sel('dom', Object.keys(DOM_ICON).map(k => [k, DOM_RU[k] || k]), 'timeline')))}
    ${fld('Заметка', area('note', 'Детали, ощущения…'))}
    <div class="form-acts">${saveBtn('Сохранить событие', 'Событие добавлено', { cls: 'btn grow', shut: 'tl-form' })}<button type="button" class="ghost" data-shut="tl-form">Отмена</button></div>`, { open: !!ctx.st.tlNew });
  return `
  ${head('timeline', ctx, { h1: 'Хронология', acts: [act('plus', 'Добавить событие', 'data-open="tl-form"')],
    figs: [[list.length, 'Событий'], [list.filter(e => e.manual).length, 'Вручную']] })}
  <p class="sub lede">Все заметные события — залогированные автоматически или добавленные вручную — в одной ленте, и флажками на графиках.</p>
  ${form}
  ${empty ? emptyH({ icon: 'timeline', line: 'Пока нет событий.', act: `<button class="ghost" data-open="tl-form">${ic('plus')}Добавить событие</button>` }) : `
  <div class="filters" data-tlf><button class="filter on" data-tlf-k="all">Все</button>${doms.map(d => `<button class="filter" data-tlf-k="${d}">${DOM_RU[d]}</button>`).join('')}</div>
  <section class="sec tl-sec"><div class="tl">${feed}</div></section>`}`;
}

/* ---------- Reports ---------- */
const DOM_TONE = { weight: 'good', labs: 'cool', garmin: 'violet' };
function goalRow(g) {
  const p = (g.start - g.current) / (g.start - g.target) * 100;
  const left = Math.abs(g.current - g.target), d = g.target % 1 || g.current % 1 ? 1 : 0;
  return `<div class="goal" data-item>
    <div class="goal-h"><div><div class="t">${g.name}</div><div class="m">${dot(DOM_TONE[g.dom] || '', DOM_RU[g.dom])}<span class="num"> · дедлайн ${dShort(g.deadline)} · ${g.left} дн.</span></div></div>
      <div class="v">${fmt(g.current, d)}<span class="u">/ ${fmt(g.target, d)} ${g.unit}</span></div>
      <button class="ibtn" data-del aria-label="Удалить цель">${ic('trash')}</button></div>
    <div class="meter"><i style="width:${clamp(p, 0, 100)}%"></i><span class="tick" style="left:25%"></span><span class="tick" style="left:50%"></span><span class="tick" style="left:75%"></span></div>
    <div class="goal-scale"><span>${fmt(g.start, 0)}</span><span>сейчас ${fmt(g.current, d)} · осталось ${fmt(left, d)} ${g.unit}</span><span>${fmt(g.target, d)}</span></div>
  </div>`;
}
function archRow(g) {
  const ok = g.status === 'achieved';
  const when = ok ? `взята ${dShort(g.closed)} · ${g.margin > 0 ? `на ${g.margin} дн. раньше дедлайна` : g.margin < 0 ? `на ${-g.margin} дн. позже дедлайна` : 'день в день с дедлайном'}` : `не взята · до цели не хватило ${-g.margin}`;
  return `<div class="row arch-g${ok ? ' ok' : ' dim-soft'}" style="grid-template-columns:22px minmax(0,1fr) auto">${ic(ok ? 'check' : 'x')}<div><div class="t">${g.name}</div><div class="m num">${when}</div></div>${ok ? `<div class="v good">${fmt(g.current, g.current % 1 ? 1 : 0)}<span class="u">${g.unit}</span></div>` : '<span></span>'}</div>`;
}
function scrReports(ctx) {
  const empty = VIEW === 'empty';
  const goalForm = formPanel('goal-form', 'Новая цель', `
    ${fld('Название', inp('name', { ph: 'Дойти до 82 кг' }))}
    ${g2(fld('Домен', sel('dom', ['weight', 'labs', 'garmin', 'nutrition', 'workouts'].map(k => [k, DOM_RU[k]]), 'weight')), fld('Дедлайн', inp('deadline', { type: 'date' })))}
    ${g2(fld('Цель', inp('target', { mode: 'decimal', ph: '82' })), fld('Ед.', inp('unit', { ph: 'кг' })))}
    <div class="form-acts">${saveBtn('Создать цель', 'Цель создана', { cls: 'btn grow', shut: 'goal-form' })}<button type="button" class="ghost" data-shut="goal-form">Отмена</button></div>`);
  const older = DIGEST.older.map(([d, t]) => `<div class="row" style="grid-template-columns:72px minmax(0,1fr)"><span class="m num">${dShort(d)}</span><span class="dg-old">${t}</span></div>`).join('');
  return `
  ${head('reports', ctx, { h1: 'Отчёты', figs: [[empty ? 0 : GOALS.active.length, 'Активные цели'], [empty ? 0 : DIGEST.count, 'Дайджесты'], [empty ? '—' : dShort(DIGEST.date), 'Последний дайджест']] })}
  <p class="sub lede">ИИ-дайджесты по неделям и отслеживание долгосрочных целей по всем доменам.</p>
  <div class="grid">
    <div class="c5">
      <section class="sec o1">${secH('Цели', `<button class="ghost" data-open="goal-form">${ic('plus')}Цель</button>`)}${goalForm}
        ${empty ? emptyH({ icon: 'chart', line: 'Целей пока нет' }) : `<div class="goals">${GOALS.active.map(goalRow).join('')}</div>`}</section>
      ${empty ? '' : `<section class="sec o2">${secH('Архив целей', `<span class="meta">${GOALS.closed.length}</span>`)}<div class="rows">${GOALS.closed.map(archRow).join('')}</div></section>`}
    </div>
    <div class="c7">
      <section class="sec o3">${secH('Еженедельный разбор', empty ? '' : `<span class="meta num">${dLong(DIGEST.date)} · ${DIGEST.model}</span>`)}
        <div class="dg-bar">${optsH([['1', 'За 1 день'], ['3', 'За 3 дня'], ['7', 'За 7 дней'], ['30', 'За 30 дней']], { on: '7' })}${saveBtn('Собрать сейчас', 'Разбор сгенерирован.', { cls: 'ghost', icon: 'sync' })}</div>
        ${empty ? emptyH({ icon: 'doc', line: 'Разборов ещё нет. Они собираются раз в неделю или по кнопке «Собрать сейчас».' }) : `<article class="digest">${DIGEST.html}</article>
        <div class="acc dg-prev" data-acc><div class="acc-h" role="button" tabindex="0" data-acc-h>${caret}<span>Предыдущие разборы <span class="m num">(${DIGEST.older.length})</span></span></div>
          <div class="collapse"><div><div class="rows">${older}</div></div></div></div>`}
      </section>
      <section class="sec o4">${secH('Утренний бриф', empty ? '' : `<span class="meta num">${dLong(BRIEF.date)} · ${BRIEF.model}</span>`)}
        <p class="sub" style="margin:-4px 0 12px">Бот присылает его в 11:00. «Собрать» — только показать здесь, ничего не отправляя.</p>
        <div class="row-acts"><button class="ghost" data-brief="build">${ic('sync')}Собрать бриф</button><button class="ghost" data-brief="test">${ic('signals')}Отправить тестовое</button></div>
        <div class="brief-out" data-brief-out></div>
        ${empty ? emptyH({ icon: 'signals', line: 'Брифов ещё нет. Они приходят в 11:00 или по кнопке «Собрать бриф».' }) : `<div class="brief">${BRIEF.text.split('\n').map(l => `<p>${l}</p>`).join('')}</div>`}
      </section>
    </div>
  </div>`;
}
const BRIEF_OUT = {
  build: [['info', 'check', 'Бриф собран — ниже. Не отправлен.'], ['', 'info', 'Пустой день: нет свежих данных Garmin. Бот в такое утро молчит.'], ['warn', 'warn', 'Не удалось собрать бриф. Проверьте баланс/ключ OpenRouter и логи.']],
  test: [['info', 'check', 'Тестовое сообщение отправлено в Telegram.'], ['warn', 'warn', '<b>Бот не подключён.</b> Telegram-бот не настроен: нужны VITALS_TELEGRAM_BOT_TOKEN и VITALS_TELEGRAM_CHAT_ID.']],
};

/* ---------- Charts ---------- */
// Older nights for the gallery: the recent 21 are real rows, the rest are drawn from the same seed; the cold of 27–30 Aug shows.
function nightSeries(key, span) {
  const out = [];
  for (let k = span - 1; k >= 0; k--) {
    const d = addDays(TODAY, -k), n = nightsAll[k], q = rngW(1300 + k);
    const ill = d >= dt(8, 27) && d <= dt(8, 30);
    let v;
    if (key === 'sleep') v = n ? n.score : Math.round(78 + (q() - .5) * 12 - (ill ? 12 : 0));
    else if (key === 'hrv') v = n ? n.hrv : Math.round(54 + (q() - .5) * 8 - (ill ? 11 : 0));
    else v = k < 14 ? DATA.nights[13 - k].rhr : Math.round(51 + (q() - .5) * 4 + (ill ? 6 : 0));
    out.push([d.getTime(), v]);
  }
  return out;
}
function chartSeries(key, span) {
  const from = addDays(TODAY, -span).getTime();
  if (key === 'ma') return DATA.weightMA.filter(p => p.date.getTime() >= from).map(p => [p.date.getTime(), +p.w.toFixed(2)]);
  if (key === 'sleep' || key === 'hrv' || key === 'rhr') return nightSeries(key, span);
  if (key === 'bench') return HEVY.progress.bench.pts.map(p => [p[0].getTime(), p[1]]);
  if (key === 'protein' || key === 'cal') return [...nutrHist].reverse().filter(d => d.k > 0 && d.date.getTime() >= from).map(d => [d.date.getTime(), key === 'cal' ? d.cal : d.p]);
  return [];
}
function customChart(box, c, { phone, intro }) {
  const series = c.series.map((s, i) => {
    let pts = chartSeries(s.k, c.span);
    if (c.norm && pts.length) { const b = pts[0][1]; pts = pts.map(p => [p[0], +(p[1] / b * 100).toFixed(1)]); }
    return { pts, color: s.tone, w: i ? 1.6 : 2, dots: s.k === 'bench', r: 3, smooth: s.k === 'ma' };
  });
  const xs = series.flatMap(s => s.pts.map(p => p[0])), x0 = Math.min(...xs), x1 = Math.max(...xs);
  const n = phone ? 3 : 4, xt = Array.from({ length: n + 1 }, (_, i) => { const t = x0 + (x1 - x0) * i / n; return [t, dShort(new Date(t))]; });
  const flags = (c.flags || []).filter(([d]) => d.getTime() >= x0 && d.getTime() <= x1).map(([d, l]) => [d.getTime(), l]);
  lineChart(box, { series, x0, x1, xt, flags, phone, intro, now: true, h: phone ? 180 : 210, yFmt: c.norm ? (v) => fmt(v, 0) : undefined });
}
function scrCharts(ctx) {
  const empty = VIEW === 'empty';
  const catOpts = [['', 'Выберите домен'], ...Object.entries(CHART_CAT).map(([k, v]) => [k, v.label])];
  const srow = (i) => `<div class="srow" data-srow><span class="flabel">Ряд ${i}</span><div class="srow-f">${sel('dom', catOpts, '')}<select class="input" name="metric" disabled><option>Выберите метрику</option></select><select class="input" name="param" hidden><option>Выберите параметр</option></select></div><button class="ibtn" data-rm-series aria-label="Удалить">${ic('x')}</button></div>`;
  const form = formPanel('chart-form', 'Новый график', `
    ${fld('Название графика', inp('name', { ph: 'Вес и сон' }))}
    <div class="srows" data-srows>${srow(1)}</div>
    <button type="button" class="ghost" data-add-series>${ic('plus')}Добавить метрику</button>
    ${optsH([['norm', 'Нормализовать (индекс = 100 в начале)']], { multi: true })}
    <div class="alert warn" data-chart-err hidden>${ic('warn')}<div>Не удалось сохранить — проверьте выбор.</div></div>
    <div class="form-acts"><button type="button" class="btn grow" data-chart-save>Сохранить график</button><button type="button" class="ghost" data-shut="chart-form">Отмена</button></div>`, { open: empty });
  const gallery = CHARTS.map((c, i) => `<section class="sec cg o${i + 1}" data-item>${secH(c.name, `<span class="acts"><button class="ghost" data-del>${ic('trash')}Удалить</button></span>`)}${c.norm ? '<p class="meta cg-note">индекс = 100 в начале</p>' : ''}
    <div class="panel bare"><div class="chart" data-chart="custom" data-cc="${c.id}"></div>
    <div class="legend">${c.series.map(s => `<span><i style="background:${s.tone}"></i>${s.label}</span>`).join('')}${c.flags.length ? '<span><i class="band"></i>события хронологии</span>' : ''}<span><i class="now"></i>сейчас</span></div></div></section>`).join('');
  return `
  ${head('charts', ctx, { h1: 'Графики', acts: [act('plus', 'Новый график', 'data-open="chart-form"')], figs: [[empty ? 0 : CHARTS.length, 'Графиков']] })}
  ${form}
  ${empty ? emptyH({ icon: 'chart', line: 'Пока нет кастомных графиков.', sub: 'Соберите первый: до восьми рядов на одном графике.' }) : `<div class="cgal">${gallery}</div>`}`;
}

/* ---------- For the doctor ---------- */
function shareRow(s) {
  const dead = s.state !== 'live';
  const exp = s.state === 'revoked' ? dot('', 'отозван') : s.state === 'expired' ? dot('', 'истёк') : `<span class="m num">до ${dShort(s.exp)}</span>`;
  return `<div class="row r-share${dead ? ' dim-soft' : ''}" data-item>
    <div><div class="t">${s.title}</div><div class="m">${s.doms.join(' · ')}</div></div>
    <div class="sh-meta"><span class="m num">${dShort(s.from)} — ${dShort(s.to)}</span>${exp}<span class="m num">${s.opened ? `открывали ${s.opened}× · ${dShort(s.last)}` : 'ещё не открывали'}</span></div>
    <span class="acts"><button class="ibtn" data-noop aria-label="Скачать файл">${ic('download')}</button>${dead ? `<button class="ibtn" data-del aria-label="Убрать из списка">${ic('trash')}</button>` : `<button class="ghost danger" data-revoke>Отозвать</button>`}</span></div>`;
}
function scrShare(ctx) {
  const empty = VIEW === 'empty', P = SHARE.presets, def = P.gp;
  const made = `<div class="collapse" data-collapse="share-made"><div><div class="panel made">
    <div class="panel-h"><h3>${ic('check')}Ссылка готова</h3></div>
    <div class="made-r"><span class="flabel">Ссылка</span><input class="input mono" readonly value="vitals.local/r/k7Qm2xVb9"><button class="ghost" data-copy="Скопировано">${ic('copy')}Копировать</button></div>
    <div class="made-r"><span class="flabel">Пароль</span><input class="input mono" readonly value="tulip-4829-orbit"><button class="ghost" data-copy="Скопировано">${ic('copy')}Копировать</button></div>
    <p class="fhint">Пароль показывается один раз и не восстанавливается — скопируй сейчас.</p></div></div></div>`;
  const form = `<div class="panel fpanel share-form"><div class="panel-h"><h3>Новый отчёт</h3></div><div class="form">
    ${fld('Название', inp('title', { ph: 'Эндокринолог, август' }))}
    ${fldd('Пресет', `<div data-presets>${optsH(Object.entries(P).map(([k, [t]]) => [k, t]), { on: 'gp' })}</div>`)}
    ${fldd('Что войдёт', `<div data-sections>${optsH(SHARE.sections, { multi: true, on: def[1] })}</div>`)}
    ${fldd('Период отчёта', `<div data-reveal="share-range" data-reveal-k="custom">${optsH([['30', '30 дней'], ['90', '90 дней'], ['180', '180 дней'], ['365', '365 дней'], ['all', 'Всё время'], ['custom', 'Точный диапазон']], { on: '90' })}</div>`)}
    <div class="collapse" data-collapse="share-range"><div>${g2(fld('С', inp('from', { type: 'date', val: '2026-07-01' })), fld('По', inp('to', { type: 'date', val: '2026-09-29' })))}</div></div>
    ${fldd('Ссылка живёт', optsH([['7', '7 дней'], ['14', '14 дней'], ['30', '30 дней']], { on: '14' }))}
    <div data-flagged>${optsH([['flag', 'Только маркеры вне нормы']], { multi: true, on: def[2] ? ['flag'] : [] })}</div>
    ${fld('От меня', area('note', 'О чём хочу спросить…', 3))}
    <button type="button" class="btn w" data-share-make>${ic('link')}Создать ссылку</button>
  </div></div>`;
  return `
  ${head('share', ctx, { h1: 'Для врача', crumb: 'Система' })}
  <p class="sub lede">Отчёт — снимок: после создания он не меняется.</p>
  <div class="grid">
    <div class="c7"><section class="sec o1">${made}${form}</section></div>
    <div class="c5"><section class="sec o2">${secH('Созданные отчёты', empty ? '' : `<span class="meta">${SHARE.list.length}</span>`)}
      ${empty ? emptyH({ icon: 'clipboard', line: 'Отчётов пока нет.' }) : `<div class="rows">${SHARE.list.map(shareRow).join('')}</div>`}
      <button class="link-row" data-go="report" data-push>${ic('doc')}<span><b>Как отчёт видит врач</b><small>открыть пример документа</small></span>${chev}</button></section></div>
  </div>`;
}

/* ---------- Settings ---------- */
const SET_TABS = [['main', 'Основное'], ['conn', 'Подключения'], ['pro', 'Проактивный слой'], ['data', 'Данные'], ['login', 'Вход']];
const secret = (on) => on ? dot('good', 'установлен') : dot('', 'не задан');
const setSave = (label, msg) => `<div class="set-save">${saveBtn(label, msg, { cls: 'ghost', icon: 'check' })}</div>`;
function setSec(title, desc, body, cls = '') { return `<section class="sec set-sec ${cls}">${secH(title)}${desc ? `<p class="sub set-d">${desc}</p>` : ''}<div class="form">${body}</div></section>`; }
function scrSettings(ctx) {
  const tab = ctx.st.setTab || 'main';
  const pane = (id, html) => `<div data-pane="${id}"${id === tab ? '' : ' hidden'}>${html}</div>`;
  const mods = RUBRICS.map(r => {
    const items = r.items.map(([id, t]) => { const core = SET.core.some(c => t.startsWith(c)); return `<button type="button" class="opt on${core ? ' lock' : ''}" data-k="${id}"${core ? ' title="Базовый модуль — отключение недоступно"' : ''}>${t}${core ? `<span class="hint">базовый</span>` : ''}</button>`; }).join('');
    return `<div class="mod-g"><span class="flabel">${r.name}</span><div class="opts" data-multi>${items}</div></div>`;
  }).join('') + `<div class="mod-g"><span class="flabel">Вес</span><div class="opts" data-multi><button type="button" class="opt on" data-k="body_comp">Состав тела</button></div></div>`;
  const main = `<div class="grid">
    <div class="c5">
      ${setSec('Язык', 'Язык интерфейса и AI-отчётов.', `<div class="seg" data-seg-local><i class="pill"></i><button class="on">Русский</button><button>English</button></div>${setSave('Сохранить язык', 'Язык изменён.')}`)}
      ${setSec('Модули дашборда', 'Включай только нужные разделы — лишние сразу скрываются из навигации, без перезагрузки. Базовые модули выключить нельзя.', mods + setSave('Сохранить модули', 'Модули обновлены'))}
    </div>
    <div class="c7">
      ${setSec('Профиль пользователя', 'Используется в расчёте состава тела (Navy-формула) и передаётся в AI-отчёты как контекст.', `
        <div class="g3 w3">${fld('Рост (см)', inp('h', { mode: 'numeric', val: '186' }))}${fld('Возраст', inp('age', { mode: 'numeric', val: '34' }))}${fld('Пол', sel('sex', [['m', 'Мужской'], ['f', 'Женский']], 'm'))}</div>
        ${fld('Часовой пояс', sel('tz', ['Europe/Moscow', 'Europe/Chisinau', 'Europe/Berlin', 'UTC'], 'Europe/Berlin'), 'Все «сегодня» считаются по нему')}
        ${fld('Текущая программа', inp('program', { val: 'рекомпозиция тела на протоколе GLP-1' }), 'Короткое описание для AI-отчётов')}
        ${fld('Цели (через запятую)', inp('goals', { val: 'снижение жира, сохранение мышц' }), 'Список целей — каждая отдельным словом через запятую')}
        ${setSave('Сохранить профиль', 'Профиль сохранён. Перезапусти контейнер для полного применения.')}`)}
      ${setSec('Цели питания', 'Дневные цели по макронутриентам для дашборда питания', `<div class="g3">${fld('Белок (г/день)', inp('p', { mode: 'numeric', val: '150' }))}${fld('Калории мин.', inp('cmin', { mode: 'numeric', val: '1900' }))}${fld('Калории макс.', inp('cmax', { mode: 'numeric', val: '2100' }))}</div>${setSave('Сохранить цели', 'Профиль сохранён. Перезапусти контейнер для полного применения.')}`)}
    </div></div>`;
  const conn = `<div class="grid">
    <div class="c6">
      ${setSec('AI — OpenRouter', 'Ключ и модели для генерации еженедельных дайджестов и распознавания анализов (PDF/фото).', `
        ${fld(`API-ключ OpenRouter ${secret(true)}`, inp('key', { type: 'password', ph: '•••••••• (уже задан — оставьте пустым, чтобы не менять)' }))}
        ${fld('Модель для дайджестов', inp('dm', { val: 'anthropic/claude-sonnet-4.6' }), 'Аналитический нарратив, нужна мощная модель')}
        ${fld('Модель для анализов', inp('pm', { val: 'google/gemini-2.5-flash' }), 'Распознавание PDF / фото анализов, нужна vision')}
        ${fld('Модель брифа', inp('bm', { ph: 'пусто = модель дайджеста' }), 'Работает каждый день по готовым числам — подойдёт модель попроще.')}
        ${fld('Base URL (необязательно)', inp('url', { ph: 'https://…' }))}
        ${setSave('Сохранить AI', 'Настройки AI сохранены. Перезапусти контейнер для полного применения.')}`)}
      ${setSec('Hevy — тренировки', 'Ключ API из приложения Hevy: Профиль → Настройки → API. Без ключа раздел тренировок работает, кнопка синхронизации заблокирована.', `${fld(`API-ключ Hevy ${secret(false)}`, inp('hevy', { type: 'password' }))}${setSave('Сохранить Hevy', 'Ключ Hevy сохранён. Перезапусти контейнер для полного применения.')}`)}
    </div>
    <div class="c6">
      ${setSec('Garmin Connect', 'Логин и пароль от аккаунта Garmin Connect. Без них раздел организма не будет синхронизироваться.', `
        ${g2(fld('Email', inp('gm', { type: 'email', val: 'demo@example.com' })), fld(`Пароль ${secret(true)}`, inp('gp', { type: 'password', ph: '•••••••• (оставьте пустым, чтобы не менять)' })))}
        ${setSave('Сохранить реквизиты', 'Изменения реквизитов Garmin сохранены и уже действуют; перезапуск не нужен.')}
        <div class="sub-sec"><span class="flabel">Отправлять свежий локальный вес в Garmin</span>
          <div data-toggle-msg="Экспорт веса включён. Перезапуск не нужен.|Экспорт веса выключен. Новые локальные измерения отправляться не будут.">${optsH([['on', 'Включено']], { multi: true, on: ['on'] })}</div>
          <p class="fhint">Экспорт включается явно и использует неофициальную сессию Garmin Connect. Отправляется только последнее подходящее прямое измерение — без переноса истории и без обратной отправки импорта Garmin.</p>
          <div class="alert info">${ic('check')}<div>Garmin актуален: 86,1 кг за 29 сентября.<span class="ev">Следующая безопасная проверка: 08:44</span></div></div>
          <div><button class="ghost" data-sync="Последний подходящий вес безопасно сверен с Garmin.">${ic('upload')}Отправить сейчас</button></div></div>`)}
      ${setSec('Claude.ai MCP Connector', 'Настройки для подключения веб-версии Claude.ai к вашему Vitals через защищённый протокол MCP.', `${fld('Client ID', inp('cid', { val: 'vitals-demo-client' }))}${fld(`Client Secret ${secret(true)}`, inp('cs', { type: 'password', ph: 'секретный ключ' }))}${setSave('Сохранить настройки MCP', 'Настройки Claude.ai MCP сохранены. Перезапусти контейнер для полного применения.')}`)}
    </div></div>`;
  const wk = SET.weekdays.map((d, i) => `<div class="wk-r"><span class="m">${d}</span>${sel('w' + i, SET.where, i < 5 ? 'В офисе' : 'Дома')}${sel('g' + i, SET.gym, [0, 2, 4].includes(i) ? 'Зал' : 'Отдых')}${sel('l' + i, SET.load, [0, 2, 4].includes(i) ? 'Обычная' : 'Лёгкая')}</div>`).join('');
  const pro = setSec('Проактивный слой', 'Когда бот заговаривает первым, когда обязан молчать и насколько свежие данные за этим стоят. Сохраняется здесь и применяется сразу — без перезапуска.', `
    <div class="g4">${fld('Утренний бриф', inp('bt', { type: 'time', val: '11:00' }), 'Сначала синкает Garmin.')}${fld('Вечерний блок', inp('et', { type: 'time', val: '21:30' }), 'До полуночи.')}${fld('Тишина с', inp('qs', { type: 'time', val: '23:00' }))}${fld('Тишина до', inp('qe', { type: 'time', val: '08:00' }))}</div>
    ${fld('Сообщений в сутки', inp('budget', { mode: 'numeric', val: '4', cls: 'sm' }), 'Считается только то, что бот начинает сам — бриф, вечерний блок, нуджи. Ответы тебе не считаются никогда.')}
    ${fldd('Нуджи', optsH([['a', 'Активность — к вечеру мало шагов'], ['n', 'Питание — белок не добит, а день ещё открыт'], ['d', 'Данные — Garmin замолчал']], { multi: true, on: ['n', 'd'] }), 'Приходят только когда условие реально выполнилось. Про уколы, добавки и протокол — ничего.')}
    ${fldd('Шаблон недели', `<div class="wk"><div class="wk-r wk-h"><span></span><span>Где</span><span>Зал</span><span>Нагрузка</span></div>${wk}</div>`, 'Каким день считается, пока не сказано иначе. Тип дня здесь не задаётся — про него спрашивает вечерний блок.')}
    ${fldd('Опрос Garmin', `<div class="g3">${fld('Полный синк, раз в N часов', inp('sh', { mode: 'numeric', val: '4' }))}${fld('Экспорт веса, раз в N минут', inp('wm', { mode: 'numeric', val: '30' }))}${fld('Окно свежести веса (дни)', inp('wd', { mode: 'numeric', val: '2' }))}${fld('Лёгкий пульс, раз в N секунд', inp('ps', { mode: 'numeric', val: '900' }))}${fld('Пульс активен с (час)', inp('p0', { mode: 'numeric', val: '8' }))}${fld('Пульс активен до (час)', inp('p1', { mode: 'numeric', val: '22' }))}</div>`, 'Читать данные бесплатно; лимит у Garmin висит на входе в аккаунт — а входы рационирует предохранитель ниже.')}
    <div class="alert">${ic('info')}<div>Предохранитель входа: израсходовано 1 из 5 логинов за сутки.</div></div>
    ${setSave('Сохранить проактивный слой', 'Настройки сохранены — расписание пересобрано, перезапуск не нужен.')}`, 'narrow');
  const data = setSec('Управление данными', 'Бэкап и восстановление всей базы, плюс отдельный чистый экспорт для вставки в чат с ИИ.', `
    <span class="flabel">Экспорт</span>
    <div class="row-acts"><button class="ghost" data-sync="Готовим ваш экспорт…">${ic('download')}Полный бэкап (.json)</button><button class="ghost" data-sync="Готовим ваш экспорт…">${ic('download')}Экспорт для ИИ (.json)</button></div>
    <p class="fhint">Полный бэкап содержит всю историю (без паролей и без файлов фото). Экспорт для ИИ — чистый плоский файл, его можно скопировать прямо в чат Claude или ChatGPT.</p>
    <span class="flabel" style="margin-top:12px">Импорт (восстановление)</span>
    <div class="alert warn">${ic('warn')}<div>Импорт полностью заменяет все текущие данные содержимым файла. Сделайте бэкап перед этим.</div></div>
    <button type="button" class="drop" data-pick="vitals-backup-2026-09-28.json"><span class="ico">${ic('upload')}</span><span><b>Выберите файл бэкапа или перетащите сюда</b><small>Файл бэкапа Vitals (.json)</small></span></button>
    <div><button type="button" class="ghost danger" data-restore>${ic('sync')}Загрузить и восстановить</button></div>
    <div class="alert info" data-restore-ok hidden>${ic('check')}<div><b>Восстановлено: 14 разделов, 3 812 записей.</b> Откройте дашборды, чтобы увидеть восстановленные данные.</div></div>`, 'narrow');
  const login = `<div class="grid">
    <div class="c6">${setSec('Пароль', '', `${fld('Текущий пароль', inp('cp', { type: 'password' }))}${fld('Новый пароль', inp('np', { type: 'password', ph: 'мин. 8 символов' }))}${fld('Повтор нового пароля', inp('rp', { type: 'password' }))}${setSave('Сменить пароль', 'Пароль успешно изменён.')}`)}</div>
    <div class="c6">${setSec('Двухфакторная защита', 'Код из приложения-аутентификатора в дополнение к паролю.', `<div class="tfa" data-tfa="off">
      <div class="tfa-s" data-tfa-s="off"><div class="tfa-l">${dot('', 'Выключена')}</div><button type="button" class="ghost" data-tfa-go="setup">${ic('lock')}Включить</button></div>
      <div class="tfa-s" data-tfa-s="setup"><div class="tfa-setup"><div class="qr">${fakeQR()}</div><div class="tfa-key"><span class="flabel">Ключ, если камера не нужна</span><div class="key num">JBSW Y3DP EHPK 3PXP K4ZT 2MQX</div>
        <div class="row-acts"><button class="ghost" data-copy="Скопировано">${ic('copy')}Скопировать ключ</button><button class="ghost touch-only" data-noop>${ic('link')}Открыть в приложении</button></div></div></div>
        ${fld('Код', inp('code', { mode: 'numeric', ph: '000000', cls: 'code-in' }))}
        <div class="row-acts"><button type="button" class="ghost" data-tfa-go="on">${ic('check')}Подтвердить</button><button type="button" class="ghost" data-tfa-go="off">Отменить</button></div></div>
      <div class="tfa-s" data-tfa-s="on"><div class="tfa-l">${dot('good', 'Включена')}</div><button type="button" class="ghost danger" data-tfa-go="disable">Выключить</button></div>
      <div class="tfa-s" data-tfa-s="disable">${fld('Код из приложения, чтобы выключить', inp('dcode', { mode: 'numeric', ph: '000000', cls: 'code-in' }))}<div class="row-acts"><button type="button" class="ghost danger" data-tfa-go="off">Выключить</button><button type="button" class="ghost" data-tfa-go="on">Отменить</button></div></div>
    </div>`)}</div></div>`;
  return `
  ${head('settings', ctx, { h1: 'Настройки', crumb: 'Система', acts: [act('sync', 'Перезапустить контейнер', 'data-restart')], sub: paneTabs(SET_TABS, tab) })}
  <p class="sub lede">Конфигурация сохраняется в .env. Настройки, которые можно применить безопасно, вступают в силу сразу; для остальных интерфейс подскажет, когда нужен перезапуск.</p>
  ${pane('main', main)}${pane('conn', conn)}${pane('pro', pro)}${pane('data', data)}${pane('login', login)}`;
}

/* ==========================================================================
   Pages the server renders on its own — no rail, no bar
   ========================================================================== */
const CLAUDE_MARK = '<svg viewBox="0 0 24 24" width="22" height="22" fill="#D97757" aria-hidden="true"><path d="M4.709 15.955l4.72-2.647.08-.23-.08-.128H9.2l-.79-.048-2.698-.073-2.339-.097-2.266-.122-.571-.121L0 11.784l.055-.352.48-.321.686.06 1.52.103 2.278.158 1.652.097 2.449.255h.389l.055-.157-.134-.098-.103-.097-2.358-1.596-2.552-1.688-1.336-.972-.724-.491-.364-.462-.158-1.008.656-.722.881.06.225.061.893.686 1.908 1.476 2.491 1.833.365.304.145-.103.019-.073-.164-.274-1.355-2.446-1.446-2.49-.644-1.032-.17-.619a2.97 2.97 0 01-.104-.729L6.283.134 6.696 0l.996.134.42.364.62 1.414 1.002 2.229 1.555 3.03.456.898.243.832.091.255h.158V9.01l.128-1.706.237-2.095.23-2.695.08-.76.376-.91.747-.492.584.28.48.685-.067.444-.286 1.851-.559 2.903-.364 1.942h.212l.243-.242.985-1.306 1.652-2.064.73-.82.85-.904.547-.431h1.033l.76 1.129-.34 1.166-1.064 1.347-.881 1.142-1.264 1.7-.79 1.36.073.11.188-.02 2.856-.606 1.543-.28 1.841-.315.833.388.091.395-.328.807-1.969.486-2.309.462-3.439.813-.042.03.049.061 1.549.146.662.036h1.622l3.02.225.79.522.474.638-.079.485-1.215.62-1.64-.389-3.829-.91-1.312-.329h-.182v.11l1.093 1.068 2.006 1.81 2.509 2.33.127.578-.322.455-.34-.049-2.205-1.657-.851-.747-1.926-1.62h-.128v.17l.444.649 2.345 3.521.122 1.08-.17.353-.608.213-.668-.122-1.374-1.925-1.415-2.167-1.143-1.943-.14.08-.674 7.254-.316.37-.729.28-.607-.461-.322-.747.322-1.476.389-1.924.315-1.53.286-1.9.17-.632-.012-.042-.14.018-1.434 1.967-2.18 2.945-1.726 1.845-.414.164-.717-.37.067-.662.401-.589 2.388-3.036 1.44-1.882.93-1.086-.006-.158h-.055L4.132 18.56l-1.13.146-.487-.456.061-.746.231-.243 1.908-1.312-.006.006z"/></svg>';
const bare = (inner, cls = '') => `<div class="bare-pg ${cls}"><div class="bare-in">${inner}</div></div>`;
const wordmark = '<div class="bare-brand">Vitals</div>';

function scrLogin() {
  return bare(`${wordmark}
    <h1 class="bare-h">С возвращением</h1>
    <form class="lg" data-lg onsubmit="return false">
      <label class="lg-f"><span>Имя пользователя</span><input name="u" autocomplete="username" value="demo"></label>
      <label class="lg-f"><span>Пароль</span><input name="p" type="password" autocomplete="current-password" data-lg-pw><button type="button" class="lg-eye" data-reveal-pw>Показать</button></label>
      <p class="lg-err" data-lg-err hidden>${ic('block')}Неверное имя пользователя или пароль.</p>
      <button class="btn w" data-login>Войти в кабинет</button>
    </form>
    <p class="bare-note">Пустой пароль покажет ошибку, любой другой — ведёт ко второму шагу.</p>`);
}
function scrTwofa() {
  return bare(`${wordmark}
    <h1 class="bare-h">Ещё один шаг</h1>
    <form class="lg" onsubmit="return false">
      <label class="lg-f code"><span>Код из приложения</span><input name="c" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="000 000" data-otp></label>
      <p class="lg-err" data-lg-err hidden>${ic('block')}Код не подошёл.</p>
      <button class="btn w" data-otp-go>Подтвердить</button>
    </form>
    <button class="ghost bare-back" data-go="login">${ic('chevL')}Назад ко входу</button>
    <p class="bare-note">Шестая цифра отправляет сама. 000000 — неверный код.</p>`);
}
function scrOauth() {
  const err = VIEW === 'error';
  const perms = ['Истории изменения веса и состава тела', 'Показателям сна, пульса и стресса Garmin', 'Логам силовых тренировок из профиля Hevy', 'Дневнику питания, калорийности и приемов пищи', 'Терапевтическим фазам протокола GLP-1', 'Данным ДНК-теста и импортированным анализам', 'Оценке лекарственной совместимости и бадов'];
  return bare(`<div class="pair"><span class="bare-brand">Vitals</span><span class="pair-x">${ic('link')}</span><span class="pair-c">${CLAUDE_MARK}Claude</span></div>
    <h1 class="bare-h">Разрешение доступа</h1>
    ${err ? `<div class="alert block">${ic('block')}<div><b>Неверный client_id</b><span class="ev">Запрос отклонён. Закрой окно и подключи коннектор заново.</span></div></div>
      <div class="bare-acts"><button class="btn" data-noop>Закрыть</button></div>` : `
    <p class="bare-p">Приложение <b>Claude.ai</b> запрашивает безопасное подключение к вашей системе здоровья Vitals.</p>
    <div class="perm-h">Интеграция получит доступ к:</div>
    <ul class="perms">${perms.map(p => `<li>${ic('check')}${p}</li>`).join('')}</ul>
    <p class="bare-note">Подключение позволяет читать показатели здоровья и вносить записи в дневник питания. Вы будете перенаправлены на: <b>claude.ai</b></p>
    <div class="bare-acts"><button class="ghost" data-noop>Отмена</button><button class="btn" data-sync="Доступ разрешён · возвращаем в Claude">Разрешить</button></div>`}`);
}
function scrReportPw() {
  return bare(`${wordmark}<span class="bare-ic">${ic('lock')}</span>
    <h1 class="bare-h">Документ под паролем</h1>
    <p class="bare-p">Ссылка защищена паролем. Пароль передан вам отдельно.</p>
    <form class="lg" onsubmit="return false">
      <label class="lg-f"><span>Пароль</span><input type="password" name="pw" value="••••••••"></label>
      <p class="lg-err" data-lg-err hidden>${ic('block')}Неверный пароль.</p>
      <button class="btn w" data-pw>Открыть</button>
    </form>
    <p class="bare-note">Первая попытка — неверный пароль, вторая открывает документ.</p>`);
}
function scrGone() {
  return bare(`${wordmark}<span class="bare-ic">${ic('link')}</span>
    <h1 class="bare-h">Ссылка недоступна</h1>
    <p class="bare-p">Эта ссылка больше не работает. Попросите новую.</p>`);
}
function scrNotFound() {
  return bare(`${wordmark}
    <p class="bare-k num">404 · Маршрут не найден</p>
    <h1 class="bare-h">Эта страница ушла на внеплановый чекап.</h1>
    <p class="bare-p">Ссылка может быть устаревшей, модуль выключен или адрес набран с ошибкой.</p>
    <div class="bare-acts"><button class="btn" data-go="today">На главную</button><button class="ghost" data-go="today">${ic('chevL')}Назад</button></div>
    <p class="bare-note num">/weight/progress-old</p>`);
}
function scrOffline() {
  return bare(`${wordmark}<span class="bare-ic">${ic('wifiOff')}</span>
    <h1 class="bare-h">Нет подключения</h1>
    <p class="bare-p">Проверь подключение к интернету и попробуй ещё раз. Vitals нужна сеть, чтобы загрузить данные.</p>
    <div class="bare-acts"><button class="btn" data-sync="Сеть всё ещё недоступна">${ic('sync')}Обновить</button></div>`);
}

/* ---------- The report the doctor opens: paper, meant to be printed ---------- */
function scrReport() {
  const labs = DATA.labs.map(m => { const prev = m.hist.length > 1 ? m.hist[m.hist.length - 2][1] : null, out = m.status !== 'ok';
    return `<tr class="${out ? 'out' : ''}"><td>${m.name}</td><td class="n">${fmt(m.v, m.d || 0)} ${m.unit}${out ? ' <b>↓</b>' : ''}</td><td class="n">${fmt(m.lo, m.d || 0)}–${fmt(m.hi, m.d || 0)}</td><td class="n">${prev != null ? fmt(prev, m.d || 0) : '—'}</td></tr>`; }).join('');
  const gar = [['Сон', '7,4 ч', '(7,2)'], ['Качество сна (0–100)', '81', '(79)'], ['Пульс покоя', '52 уд/мин', '(51)'], ['Вариабельность пульса', '49 мс', '(54)'], ['Шаги', '9 480', '(8 910)']];
  const t = (head, rows) => `<table><thead><tr>${head.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>`;
  return `<div class="doc">
    <header class="doc-h"><div class="doc-brand">Vitals</div><h1>Выписка о состоянии здоровья</h1>
      <dl><div><dt>Пациент</dt><dd>34 года · мужской · рост 186 см</dd></div><div><dt>Период</dt><dd class="n">1 июля — 29 сентября 2026</dd></div><div><dt>Составлено</dt><dd class="n">29 сентября 2026</dd></div><div><dt>Разделы</dt><dd>Вес, Анализы, Препараты ГПП-1, Добавки, Сон и активность, Тренировки, Питание, Кожа, Генетика, Симптомы</dd></div></dl></header>
    <section><h2>Коротко</h2><ul><li>Вес 94,0 → 86,1 кг (−7,9 кг)</li><li>Принимает сейчас: семаглутид 0,5 мг раз в неделю; витамин D3 2000 МЕ; омега-3 2 г; магний глицинат 400 мг</li><li>Вне референсных значений: витамин D (25-OH) 28 нг/мл</li></ul></section>
    <section><h2>Со слов пациента</h2><p class="doc-note">Хочу обсудить витамин D: принимаю добавку три месяца, а уровень всё ещё ниже нормы. И стоит ли менять дозу семаглутида — вес последние две недели идёт медленнее.</p></section>
    <section><h2>Препараты и протоколы</h2>
      <h3>Препараты ГПП-1</h3><p>Семаглутид, 0,5 мг раз в неделю, сейчас · 0,25 мг с 5 июля, 0,5 мг с 2 августа.</p>
      ${t(['Дата', 'Что', 'Доза'], DATA.injections.slice(0, 4).map(j => `<tr><td class="n">${dLong(j.date)}</td><td>Семаглутид · ${j.site}</td><td class="n">${fmt(j.dose, j.dose < .5 ? 2 : 1)} мг</td></tr>`).join(''))}
      <h3>Добавки</h3><p>Витамин D3 2000 МЕ утром · Омега-3 2 г днём · Магний глицинат 400 мг на ночь.</p></section>
    <section><h2>Анализы</h2><p class="doc-sub">Сдано 6 сентября 2026</p>${t(['Показатель', 'Значение', 'Норма', 'Раньше'], labs)}</section>
    <section><h2>Вес</h2><p>94,0 → 86,1 кг за период (−7,9 кг), измерений: 71</p>
      <h3>Состав тела</h3><p>InBody 770, 12 сентября: жир 18,4 %, скелетно-мышечная масса 39,2 кг, висцеральный жир — уровень 7.</p></section>
    <section><h2>Побочные эффекты и симптомы</h2>${t(['Дата', 'Что', 'Выраженность'], [...DATA.sideEffects.map(e => [e.date, e.name, e.sev]), [dt(9, 28), 'Головная боль', 3]].map(([d, n, s]) => `<tr><td class="n">${dLong(d)}</td><td>${n}</td><td class="n">${s} из 5</td></tr>`).join(''))}</section>
    <section><h2>Сон и дневная активность</h2><p class="doc-sub">Средние за сутки по периоду, измерено наручным трекером. В скобках — то же среднее за предыдущий отрезок такой же длины.</p>${t(['Показатель', 'Среднее', ''], gar.map(([a, b, c]) => `<tr><td>${a}</td><td class="n">${b}</td><td class="n muted">${c}</td></tr>`).join(''))}<p class="doc-sub">Измерено за 90 дней</p></section>
    <section><h2>Силовые тренировки</h2><p>26 тренировок за период · в среднем раз в 3,5 дня · 6 420 кг поднято за тренировку</p></section>
    <section><h2>Питание</h2><p>1 980 ккал и 136 г белка в сутки в среднем · еда записана за 74 дня</p></section>
    <section><h2>Кожа</h2><p>4 средства в текущем уходе · воспаления 1 из 5, пигментация 2 из 5 (27 сентября)</p></section>
    <section><h2>Генетика</h2>${t(['Ген', 'Генотип', 'Что это значит'], VARIANTS.filter(v => v.marker).map(v => `<tr><td>${v.gene} <span class="muted n">${v.rsid}</span></td><td class="n">${v.gt}</td><td>${v.impact}</td></tr>`).join(''))}</section>
    <footer class="doc-f">Составлено пациентом по записям, которые он ведёт сам. Не является медицинским документом и не является диагнозом.</footer>
  </div>`;
}

/* ==========================================================================
   Empty, switched-off and failed states — one mechanism for every screen
   ========================================================================== */
const EMPTY = {
  today: { icon: 'today', line: 'Данных за сегодня пока нет. Запиши вес — день начнётся с него.', act: ['Записать вес', 'log:weight'] },
  weight: { icon: 'scale', line: 'Записей веса пока нет — добавьте первую, чтобы видеть тренды.', act: ['Записать вес', 'log:weight'] },
  measures: { icon: 'ruler', line: 'Замеров пока нет.', act: ['Новый замер', 'log:measure'] },
  recovery: { icon: 'pulse', line: 'Нет данных. Синхронизируйте Garmin.', act: ['Синхронизировать', 'sync'] },
  sleep: { icon: 'pulse', line: 'По этой ночи деталей нет.', act: ['К списку ночей', 'go:nights'] },
  nights: { icon: 'pulse', line: 'Нет данных. Синхронизируйте Garmin.', act: ['Синхронизировать', 'sync'] },
  activities: { icon: 'dumbbell', line: 'Нет активностей.', act: ['Синхронизировать', 'sync'] },
  workouts: { icon: 'dumbbell', line: 'Нет тренировок. Нажмите «Синхронизировать».', act: ['Синхронизировать', 'sync'] },
  nutrition: { icon: 'bowl', line: 'Сегодня приёмов пока нет.', act: ['Записать еду', 'log:meal'] },
  glp1: { icon: 'syringe', line: 'Пока нет инъекций.', act: ['Записать инъекцию', 'log:dose'] },
  hrt: { icon: 'hrt', line: 'Активного курса нет.', act: ['Новый курс', 'none'] },
  labs: { icon: 'flask', line: 'Нет данных. Загрузите анализ или введите вручную.', act: ['Загрузить бланк', 'upload'] },
  genetics: { icon: 'dna', line: 'Данные не найдены', sub: 'Генетические варианты ещё не загружены.', act: ['Импорт VCF', 'none'] },
  supplements: { icon: 'pill', line: 'Нет активных добавок.', act: ['Новая добавка', 'none'] },
  skincare: { icon: 'skincare', line: 'Нет средств в каталоге. Добавьте первое кнопкой сверху.', act: ['Добавить средство', 'none'] },
  interactions: { icon: 'interactions', line: 'Нет правил под этот фильтр.', act: ['Показать все', 'none'] },
  signals: { icon: 'signals', line: 'Записей пока нет. Напиши боту — появятся здесь.' },
};
// Screens that keep their form or controls when empty draw the empty state themselves.
const SELF_EMPTY = new Set(['timeline', 'reports', 'charts', 'share', 'settings', 'more', ...BARE]);
// Base modules cannot be switched off (the settings say the same).
const CORE = new Set(['today', 'more', 'weight', 'measures', 'recovery', 'sleep', 'nights', 'activities', 'labs', 'reports', 'charts', 'share', 'settings', ...BARE]);
const H1 = { sleep: 'Ночь', nights: 'Сон', activities: 'Активности', skincare: 'Уход за кожей' };
const SUBS = { measures: () => subtabs(WEIGHT_TABS, 'measures'), recovery: () => subtabs(GARMIN_TABS, 'recovery'), sleep: () => subtabs(GARMIN_TABS, 'nights'), nights: () => subtabs(GARMIN_TABS, 'nights'), activities: () => subtabs(GARMIN_TABS, 'activities') };
function stateAct(spec, ghost = true) {
  if (!spec) return '';
  const [label, what] = spec, [k, v] = what.split(':');
  const attr = k === 'log' ? `data-log="${v}"` : k === 'go' ? `data-go="${v}"` : k === 'sync' ? 'data-sync' : k === 'upload' ? 'data-upload' : k === 'retry' ? 'data-retry' : 'data-noop';
  const icon = k === 'log' ? 'plus' : k === 'go' ? 'chevR' : k === 'sync' || k === 'retry' ? 'sync' : k === 'upload' ? 'upload' : 'plus';
  return `<button class="${ghost ? 'ghost' : 'btn'}" ${attr}>${ic(icon)}${label}</button>`;
}
function stateHead(id, ctx) {
  if (id === 'today') return `${topbar('Сегодня')}<div class="today-top"><div class="kicker">Вторник, 29 сентября <span class="sep"></span> <span class="num">${DATA.now}</span></div></div><h1 class="h1 st-h1">Сегодня</h1>`;
  return head(id, ctx, { h1: H1[id] || TITLE[id], title: id === 'activities' ? H1[id] : null, sub: SUBS[id] ? SUBS[id]() : '' });
}
function scrEmpty(id, ctx) {
  const e = EMPTY[id]; if (!e) return SCREENS[id](ctx);
  return `${stateHead(id, ctx)}<div class="st-body">${emptyH({ icon: e.icon, line: e.line, sub: e.sub, act: stateAct(e.act) })}</div>`;
}
function scrOff(id, ctx) {
  const t = H1[id] || TITLE[id], r = rubricOf(id), icn = r ? r.items.find(i => i[0] === navId(id))[2] : 'grid';
  return `${stateHead(id, ctx)}<div class="st-body">${emptyH({ icon: icn, line: `Модуль «${t}» выключен.`, sub: 'Раздел скрыт из навигации, записи сохранены.', act: `<button class="ghost" data-go="settings" data-push>${ic('sliders')}Включить в настройках</button>` })}</div>`;
}
function scrError(id, ctx) {
  return `${stateHead(id, ctx)}<div class="st-body">${emptyH({ icon: 'warn', tone: 'warn', line: 'Не удалось загрузить', sub: 'Сервер не ответил. То, что уже на устройстве, не пострадало.', act: stateAct(['Повторить', 'retry:1']) })}</div>`;
}

/* ---------- Charts the added screens hydrate ---------- */
const xTicks = (x0, x1, n) => Array.from({ length: n + 1 }, (_, i) => { const t = x0 + (x1 - x0) * i / n; return [t, dShort(new Date(t))]; });
// Body fat from two sources on one chart: Navy by tape as a line, InBody scans as labelled points.
function fatChart(box, { phone, intro }) {
  const navy = [...MEAS.navy].reverse().map(r => [r[0].getTime(), r[3]]), bia = MEAS.bia.map(([d, v]) => [d.getTime(), v]);
  const x0 = navy[0][0], x1 = TODAY.getTime();
  lineChart(box, { series: [{ pts: navy, color: '#F4F0F6', smooth: true }, { pts: bia, color: '#BCA4DC', line: false, dots: true, r: 4, labels: true, lblFmt: (v) => fmt(v) }],
    x0, x1, xt: xTicks(x0, x1, phone ? 3 : 5), phone, intro, now: true, h: phone ? 190 : 250, tipVal: (v) => fmt(v) + ' %' });
}
// Working weight of one exercise, session by session.
function hevyChart(box, id, { phone, intro }) {
  const p = HEVY.progress[id]; if (!p || p.pts.length < 2) return;
  const pts = p.pts.map(q => [q[0].getTime(), q[1]]), x0 = pts[0][0], x1 = pts[pts.length - 1][0];
  lineChart(box, { series: [{ pts, color: '#F4F0F6', dots: true, r: 3.4, labels: !phone || pts.length < 6, lblFmt: (v) => fmt(v, v % 1 ? 1 : 0) }],
    x0, x1, xt: xTicks(x0, x1, phone ? 2 : 4), phone, intro, now: true, h: phone ? 180 : 220,
    tipVal: (v) => { const q = p.pts.find(z => z[1] === v); return `${fmt(v, v % 1 ? 1 : 0)} кг × ${q ? q[2] : ''}`; } });
}
// What the dose log implies about active hormone: an estimate drawn from the record, not a plan.
function hrtChart(box, { phone, intro }) {
  const rel = hrtRelease(), pts = rel.map(([d, v]) => [d.getTime(), +v.toFixed(1)]);
  const marks = HRT.doses.filter(d => d.name.startsWith('Тест')).map(d => d.date.getTime()).filter(t => t >= pts[0][0]);
  lineChart(box, { series: [{ pts, color: '#BCA4DC', smooth: true }], area: true, now: true, marks, yMin: 0,
    x0: pts[0][0], x1: pts[pts.length - 1][0], xt: xTicks(pts[0][0], pts[pts.length - 1][0], phone ? 3 : 4), phone, intro, h: phone ? 150 : 180, tipVal: (v) => fmt(v) + ' мг' });
  const peak = box.closest('.mrow')?.querySelector('[data-peak]'); if (peak) peak.textContent = fmt(Math.max(...pts.map(p => p[1])));
}

const SCREENS = { today: scrToday, weight: scrWeight, recovery: scrRecovery, glp1: scrGlp, labs: scrLabs, more: scrMore,
  measures: scrMeasures, sleep: scrSleep, nights: scrNights, activities: scrActivities, workouts: scrWorkouts, nutrition: scrNutrition,
  hrt: scrHrt, genetics: scrGenetics, supplements: scrSupplements, skincare: scrSkincare, interactions: scrInteractions, signals: scrSignals,
  timeline: scrTimeline, reports: scrReports, charts: scrCharts, share: scrShare, settings: scrSettings,
  login: scrLogin, twofa: scrTwofa, oauth: scrOauth, report: scrReport, reportpw: scrReportPw, gone: scrGone, notfound: scrNotFound, offline: scrOffline };

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
    <div class="rail-foot"><a href="#" data-go="share" data-nav="share">${ic('clipboard')}Для врача</a><a href="#" data-go="settings" data-nav="settings">${ic('sliders')}Настройки</a></div>
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
  CID++; el.innerHTML = railHTML() + `<div class="stage"><div class="screen-shade"></div></div>` + bnavHTML() + sheetHTML() + `<div class="toasts" aria-live="polite"></div>`
    + `<div class="net-pill" hidden>${ic('wifiOff')}Нет сети — сохраню, когда появится</div><div class="lightbox" hidden data-lb><button class="ibtn" data-lb-x aria-label="Закрыть">${ic('x')}</button><div class="lb-im"></div><div class="lb-cap num"></div></div>`;
  host.appendChild(el);
  const stage = el.querySelector('.stage'), shade = stage.querySelector('.screen-shade');
  const st = { stack: [], els: {}, range: '3m', labSel: 'vitd', introDone: false, busy: false, logTab: 'weight',
    night: 0, nDay: 0, hevyEx: 'bench', sleepGroup: 'pulse', view: 'data', tlNew: false, setTab: 'main' };
  const app = { el, st, go, openSheet, closeSheet, replay, toast, reset, setView, closeLb };
  INSTANCES.push(app);

  const isDesk = () => el.clientWidth >= 768;
  const scaleOf = () => el.getBoundingClientRect().width / el.offsetWidth || 1;
  const anim = (node, kf, o) => node.animate(kf, { fill: 'both', easing: EASE_SHEET, ...o, duration: RM ? 1 : o.duration });

  /* ---------- Screens ---------- */
  function build(id, { intro = false, back = null } = {}) {
    const s = document.createElement('section');
    s.className = 'screen'; s.dataset.id = id;
    const ctx = { intro, back: isDesk() ? null : back, st };
    VIEW = st.view;
    const v = st.view;
    const html = v === 'empty' && !SELF_EMPTY.has(id) ? scrEmpty(id, ctx)
      : v === 'off' && !CORE.has(id) ? scrOff(id, ctx)
      : v === 'error' && !BARE.has(id) ? scrError(id, ctx)
      : SCREENS[id](ctx);
    VIEW = 'data';
    if (BARE.has(id)) { s.classList.add('bare'); if (id === 'report') s.classList.add('paper'); s.innerHTML = html; }
    else s.innerHTML = `<div class="page">${html}</div>`;
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
      if (k === 'fat') fatChart(box, { phone, intro });
      if (k === 'nhyp') { const n = nightsAll[st.night]; hypChart(box, { intro, data: n.hyp, start: n.start }); }
      if (k === 'ncurves') sleepCurves(box, nightsAll[st.night], st.sleepGroup, phone, intro);
      if (k === 'hevy') hevyChart(box, box.dataset.exid, { phone, intro });
      if (k === 'hrt') hrtChart(box, { phone, intro });
      if (k === 'bars') dayBars(box, Array.from({ length: 30 }, (_, i) => dayAt(29 - i)), { phone, sel: st.nDay, min: NUTR.calMin, max: NUTR.calMax });
      if (k === 'custom') customChart(box, CHARTS.find(c => c.id === +box.dataset.cc), { phone, intro });
      bindScrub(box);
    });
    s.querySelectorAll('[data-compo]').forEach(c => c.classList.toggle('intro', intro));
    if (st.view === 'refresh') { const k = s.querySelector('.kicker'); if (k && !k.querySelector('.sync-live')) k.insertAdjacentHTML('beforeend', `<span class="sync-live">${ic('sync')}обновляю…</span>`); }
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
    const cur = current(), root = st.stack[0], nid = navId(cur);
    el.classList.toggle('bare', BARE.has(cur));
    el.querySelectorAll('.rail-ink, .bnav .ink').forEach(n => { n.style.transition = instant ? 'none' : ''; });
    // rail — a screen one level down keeps its parent lit
    el.querySelectorAll('.rail-a, .rail-foot a').forEach(a => a.classList.toggle('on', a.dataset.nav === nid));
    const on = el.querySelector(`.rail-a[data-nav="${nid}"]`), ink = el.querySelector('.rail-ink');
    if (on && ink) { ink.style.opacity = 1; ink.style.height = on.offsetHeight + 'px'; ink.style.transform = `translateY(${on.offsetTop}px)`; }
    else if (ink) ink.style.opacity = 0;
    // bottom bar — the root's tab stays lit while you are deeper in it
    const tab = tabOf(root);
    el.querySelectorAll('.bnav a').forEach(a => { const onA = a.dataset.tab === tab; a.classList.toggle('on', onA); if (onA) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    const ta = el.querySelector(`.bnav a[data-tab="${tab}"]`), bi = el.querySelector('.bnav .ink');
    if (ta && bi) bi.style.transform = `translateX(${ta.offsetLeft + ta.offsetWidth / 2 - 10}px)`;
    if (instant) requestAnimationFrame(() => el.querySelectorAll('.rail-ink, .bnav .ink').forEach(n => { n.offsetHeight; n.style.transition = ''; }));
    onNav && onNav(cur);
  }

  /* ---------- Navigation ---------- */
  async function go(id, { mode, shared, force } = {}) {
    if (!BUILT.has(id)) { toast(`«${TITLE[id]}» в макет не входит`, { icon: 'info' }); return; }
    if (id === 'more' && isDesk()) { id = 'today'; }
    if (st.busy) return;
    if (id === current() && !force) { scrollTop(); return; }
    if (id === current()) return rerender();
    // Already deeper in the stack: go back to it instead of stacking a copy
    if (st.stack.includes(id) && !isDesk()) { while (st.stack.length > st.stack.indexOf(id) + 2) { const x = st.stack.splice(st.stack.length - 2, 1)[0]; st.els[x]?.remove(); delete st.els[x]; } return pop(); }
    st.busy = true;
    const from = current(), fromEl = st.els[from];
    if (BARE.has(id) || BARE.has(from)) mode = 'fade';
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

  /* ---------- The added screens: redraw, states, forms, lists ---------- */
  // Same screen, new state (another night, another day): the crossfade of a tab change.
  async function rerender({ keepScroll = true } = {}) {
    if (st.busy) return;
    st.busy = true;
    const id = current(), old = st.els[id];
    const s = build(id, { back: st.stack.length > 1 ? TITLE[st.stack[st.stack.length - 2]] : null });
    st.els[id] = s; hydrate(s, { intro: true }); syncNav(true);
    if (keepScroll && old) s.scrollTop = old.scrollTop;
    await fade(old, s);
    old?.remove(); st.busy = false;
  }
  // The viewer's "State" switch: the same screen drawn empty, switched off, offline, failed or refreshing.
  function setView(v) {
    st.view = v;
    el.querySelector('.net-pill').hidden = v !== 'offline';
    if (v === 'off' && CORE.has(current())) toast('Базовый модуль — отключение недоступно', { icon: 'info' });
    if (!st.busy) rerender();
  }
  const enter = (node) => { if (!node || RM) return; anim(node, [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: 320, easing: EASE_OUT }).finished.then(() => node.getAnimations().forEach(a => a.cancel())); };
  function showRow(r, show, i) {
    if (show && r.hidden) { r.hidden = false; if (!RM) anim(r, [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: 320, delay: Math.min(i, 8) * 25, easing: EASE_OUT }).finished.then(() => r.getAnimations().forEach(a => a.cancel())); }
    else if (!show) r.hidden = true;
  }
  async function busyThen(btn, fn, ms = 620) {
    if (btn.dataset.busy) return;
    btn.dataset.busy = '1';
    const svg = btn.querySelector('svg'), isBtn = btn.classList.contains('btn'), label = btn.innerHTML;
    if (isBtn) { btn.style.width = btn.offsetWidth + 'px'; btn.innerHTML = '<span class="spinner"></span>'; }
    else if (svg) svg.style.animation = 'spin 900ms linear infinite';
    await wait(RM ? 0 : ms);
    if (isBtn) { btn.innerHTML = label; btn.style.width = ''; } else if (svg) svg.style.animation = '';
    delete btn.dataset.busy;
    fn();
  }
  function switchPane(btn) {
    const group = btn.closest('[data-panegroup]') || st.els[current()], key = btn.dataset.paneBtn;
    btn.parentElement.querySelectorAll('[data-pane-btn]').forEach(b => b.classList.toggle('on', b === btn));
    group.querySelectorAll('[data-pane]').forEach(p => { if (p.closest('[data-panegroup]') !== btn.closest('[data-panegroup]')) return; const on = p.dataset.pane === key; p.hidden = !on; if (on) enter(p); });
    if (current() === 'settings' && !btn.closest('[data-panegroup]')) st.setTab = key;
    placeInks(btn.parentElement.parentElement);
  }
  function openForm(id, forceOpen = false) {
    const c = st.els[current()].querySelector(`[data-collapse="${id}"]`); if (!c) return;
    if (c.classList.contains('open') && !forceOpen) return shutForm(id);
    c.classList.add('open');
    setTimeout(() => { c.scrollIntoView({ behavior: RM ? 'auto' : 'smooth', block: 'nearest' }); c.querySelector('input:not([type="date"]):not([readonly]), textarea, select')?.focus({ preventScroll: true }); }, RM ? 0 : 200);
  }
  function shutForm(id) { st.els[current()].querySelector(`[data-collapse="${id}"]`)?.classList.remove('open'); if (id === 'tl-form') st.tlNew = false; }
  async function fsave(btn) {
    if (btn.dataset.busy) return;
    btn.dataset.busy = '1';
    const scr = st.els[current()], label = btn.innerHTML, isBtn = btn.classList.contains('btn'), svg = btn.querySelector('svg');
    btn.style.width = btn.offsetWidth + 'px';
    if (isBtn) btn.innerHTML = '<span class="spinner"></span>'; else if (svg) svg.style.animation = 'spin 900ms linear infinite';
    await wait(RM ? 0 : 520);
    if (isBtn) { btn.dataset.state = 'done'; btn.innerHTML = ic('check') + 'Записано'; await wait(RM ? 0 : 520); }
    else if (svg) svg.style.animation = '';
    toast(st.view === 'offline' ? 'Сохранено на устройстве — отправлю, когда появится сеть' : btn.dataset.fsave);
    if (btn.dataset.roll) setOdo(scr.querySelector('[data-navy] .odo'), btn.dataset.roll);
    if (btn.dataset.fshut) shutForm(btn.dataset.fshut);
    if (btn.hasAttribute('data-bs-save')) { scr.querySelector('[data-bs-pre]').hidden = true; scr.querySelector('[data-bs-up]').hidden = false; }
    setTimeout(() => { btn.dataset.state = ''; btn.innerHTML = label; btn.style.width = ''; delete btn.dataset.busy; }, isBtn ? 700 : 0);
  }
  // Delete (or archive) a row: it leaves, and the toast can bring it back.
  function removeItem(btn, msg) {
    const item = btn.closest('[data-item]') || btn.closest('.row'); if (!item) return;
    const done = () => { item.hidden = true; };
    if (RM) done(); else anim(item, [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateX(-12px)' }], { duration: 220, easing: 'ease-in' }).finished.then(() => { done(); item.getAnimations().forEach(a => a.cancel()); });
    toast(msg, { undo: () => { item.hidden = false; enter(item); } });
  }
  function pickExercise(id, fromWorkout) {
    const scr = st.els[current()];
    st.hevyEx = id;
    scr.querySelectorAll('[data-hevy-cat] .pick').forEach(r => r.classList.toggle('sel', r.dataset.ex === id));
    const box = scr.querySelector('[data-hevy-progress]');
    box.innerHTML = hevyProgress(id); enter(box);
    const ch = box.querySelector('[data-chart]'); if (ch) { ch.dataset.cid = ++CID; hevyChart(ch, id, { phone: !isDesk(), intro: true }); bindScrub(ch); }
    if (fromWorkout || !isDesk()) setTimeout(() => box.scrollIntoView({ behavior: RM ? 'auto' : 'smooth', block: 'center' }), 40);
  }
  function filterRules(btn) {
    const scr = st.els[current()];
    btn.parentElement.querySelectorAll('.filter').forEach(b => b.classList.toggle('on', b === btn));
    const dom = scr.querySelector('[data-rf="dom"] .on').dataset.rfK, sev = scr.querySelector('[data-rf="sev"] .on').dataset.rfK;
    let any = 0;
    scr.querySelectorAll('[data-rules] .rgrp').forEach(g => {
      let n = 0;
      g.querySelectorAll('.rule').forEach((r, i) => { const ok = (dom === 'all' || r.dataset.domA === dom || r.dataset.domB === dom) && (sev === 'all' || r.dataset.sev === sev); showRow(r, ok, i); n += ok; });
      g.hidden = !n; g.querySelector('[data-cnt]').textContent = n; any += n;
    });
    const em = scr.querySelector('[data-rules-empty]'); em.hidden = !!any; if (!any) enter(em);
  }
  function openLb(tile) {
    const lb = el.querySelector('[data-lb]');
    lb.querySelector('.lb-im').innerHTML = tile.querySelector('.im').innerHTML;
    lb.querySelector('.lb-cap').textContent = dLong(new Date(+tile.dataset.photo));
    lb.hidden = false;
    anim(lb, [{ opacity: 0 }, { opacity: 1 }], { duration: 240, easing: EASE_OUT });
    anim(lb.querySelector('.lb-im'), [{ transform: 'scale(.94)' }, { transform: 'none' }], { duration: 420 });
  }
  function closeLb() { const lb = el.querySelector('[data-lb]'); if (lb.hidden) return; anim(lb, [{ opacity: 1 }, { opacity: 0 }], { duration: 180, easing: 'ease-in' }).finished.then(() => { lb.hidden = true; lb.getAnimations().forEach(a => a.cancel()); }); }
  // Editing a tape measurement reuses the form above; a tag says which date is being changed.
  function editMeasure(row) {
    const scr = st.els[current()], pane = scr.querySelector('[data-pane="measure"]'), tag = scr.querySelector('[data-edit-tag]');
    const seg = scr.querySelector('[data-pane-btn="measure"]'); if (seg && !seg.classList.contains('on')) switchPane(seg);
    pane.querySelector('[name="neck"]').value = row ? fmt(+row.dataset.neck) : '';
    pane.querySelector('[name="waist"]').value = row ? fmt(+row.dataset.waist) : '';
    pane.querySelector('[name="date"]').value = row ? row.dataset.date : '2026-09-29';
    tag.hidden = !row; pane.querySelector('[data-cancel-edit]').hidden = !row;
    if (row) { tag.querySelector('[data-edit-date]').textContent = dLong(new Date(row.dataset.date + 'T12:00')); enter(tag); pane.closest('.panel').scrollIntoView({ behavior: RM ? 'auto' : 'smooth', block: 'nearest' }); }
  }
  function checkOtp(form) {
    const i = form.querySelector('[data-otp]'), v = i.value.replace(/\D/g, ''), err = form.querySelector('[data-lg-err]');
    if (v.length < 6) { i.focus(); return; }
    if (v === '000000') { err.hidden = false; enter(err); i.select(); return; }
    err.hidden = true; i.blur(); go('today');
  }
  function applyPreset(k, form) {
    const [, secs, flag] = SHARE.presets[k];
    form.querySelectorAll('[data-sections] .opt').forEach(o => o.classList.toggle('on', secs.includes(o.dataset.k)));
    form.querySelector('[data-flagged] .opt').classList.toggle('on', flag);
  }
  // One grammar for every choice: single → the capsule moves; multi (data-multi) → each capsule toggles.
  function pickOpt(n) {
    const box = n.parentElement;
    if (n.classList.contains('lock')) return toast('Базовый модуль — отключение недоступно', { icon: 'info' });
    if (box.hasAttribute('data-multi')) {
      n.classList.toggle('on');
      if (/^(Включено|Выключено)/.test(n.textContent)) n.firstChild.nodeValue = n.classList.contains('on') ? 'Включено' : 'Выключено';
      const tm = n.closest('[data-toggle-msg]'); if (tm) toast(tm.dataset.toggleMsg.split('|')[n.classList.contains('on') ? 0 : 1]);
    } else box.querySelectorAll('.opt').forEach(o => o.classList.toggle('on', o === n));
    if (n.dataset.hint) { const h = n.closest('.field')?.querySelector('.fhint'); if (h) h.textContent = n.dataset.hint; }
    const pr = n.closest('[data-presets]'); if (pr) applyPreset(n.dataset.k, pr.closest('.form'));
    const rv = n.closest('[data-reveal]'); if (rv) rv.closest('.form').querySelector(`[data-collapse="${rv.dataset.reveal}"]`)?.classList.toggle('open', n.dataset.k === rv.dataset.revealK);
  }
  // The chart builder: a domain fills the metric list, a metric that needs one shows its parameter.
  el.addEventListener('change', (e) => {
    const s = e.target; if (!s.closest('[data-srow]')) return;
    const row = s.closest('[data-srow]'), met = row.querySelector('[name="metric"]'), par = row.querySelector('[name="param"]');
    if (s.name === 'dom') {
      const c = CHART_CAT[s.value];
      met.innerHTML = '<option value="">Выберите метрику</option>' + (c ? c.metrics.map(([k, t, u, p]) => `<option value="${k}" data-p="${p || ''}">${t}${u ? ', ' + u : ''}</option>`).join('') : '');
      met.disabled = !c; par.hidden = true;
    }
    if (s.name === 'metric') {
      const p = s.selectedOptions[0]?.dataset.p;
      par.hidden = !p;
      if (p) par.innerHTML = '<option value="">Выберите параметр</option>' + CHART_PARAMS[p].map(x => `<option>${x}</option>`).join('');
    }
    row.closest('.form').querySelector('[data-chart-err]').hidden = true;
  });
  // The second factor sends itself on the sixth digit.
  el.addEventListener('input', (e) => {
    const i = e.target; if (!i.matches('[data-otp]')) return;
    i.value = i.value.replace(/\D/g, '').slice(0, 6);
    if (i.value.length === 6) checkOtp(i.closest('form'));
  });

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
    if ((n = t.closest('[data-lb-x]')) || t.matches('[data-lb]')) return closeLb();
    if ((n = t.closest('[data-tab]'))) {
      const tab = n.dataset.tab, root = TAB_ROOT[tab];
      if (tabOf(st.stack[0]) === tab) { if (st.stack.length > 1) return popToRoot(); return scrollTop(); }
      return go(root, { mode: 'tab' });
    }
    if ((n = t.closest('[data-night-i]'))) st.night = +n.dataset.nightI;
    if ((n = t.closest('[data-go]'))) {
      const id = n.dataset.go;
      if (n.hasAttribute('data-chip')) return go(id, { mode: 'replace' });
      if (n.hasAttribute('data-push')) return go(id, { mode: 'push' });
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
      const svg = n.querySelector('svg'), msg = n.dataset.sync;
      n.classList.add('busy', 'spin'); if (svg) svg.style.animation = 'spin 900ms linear infinite';
      setTimeout(() => { n.classList.remove('busy', 'spin'); if (svg) svg.style.animation = ''; toast(msg || 'Garmin: новых данных нет · 08:14', msg && /недоступ/.test(msg) ? { icon: 'info' } : {}); }, 1400);
      return;
    }
    if ((n = t.closest('[data-upload]'))) return toast('Выбор файла — в макете не подключён', { icon: 'info' });
    if ((n = t.closest('[data-soon]'))) return toast(`«${n.dataset.soon}» в макет не входит`, { icon: 'info' });
    if ((n = t.closest('[data-noop]'))) return toast('В макете не подключено', { icon: 'info' });

    /* ----- the added screens ----- */
    const scr = st.els[current()];
    if ((n = t.closest('[data-pane-btn]'))) return switchPane(n);
    if ((n = t.closest('[data-open]'))) return openForm(n.dataset.open);
    if ((n = t.closest('[data-shut]'))) return shutForm(n.dataset.shut);
    if ((n = t.closest('[data-fsave]'))) return fsave(n);
    if ((n = t.closest('[data-del]'))) return removeItem(n, 'Удалено');
    if ((n = t.closest('[data-archive]'))) return removeItem(n, n.closest('.arch') ? 'Возвращено в активные' : 'Перенесено в архив');
    if ((n = t.closest('[data-copy]'))) return toast(n.dataset.copy, { icon: 'copy' });
    if ((n = t.closest('[data-night]'))) { if (n.disabled) return; st.night = clamp(st.night + +n.dataset.night, 0, nightsAll.length - 1); return rerender({ keepScroll: false }); }
    if ((n = t.closest('[data-sgroup]'))) {
      st.sleepGroup = n.dataset.sgroup;
      n.parentElement.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === n)); placeInks(n.parentElement.parentElement);
      const box = scr.querySelector('[data-chart="ncurves"]'); sleepCurves(box, nightsAll[st.night], st.sleepGroup, !isDesk(), true); return;
    }
    if ((n = t.closest('[data-nday]'))) { if (n.disabled) return; st.nDay = clamp(st.nDay + +n.dataset.nday, 0, 29); return rerender(); }
    if ((n = t.closest('[data-nday-today]'))) { st.nDay = 0; return rerender(); }
    if ((n = t.closest('[data-day]'))) { st.nDay = +n.dataset.day; return rerender(); }
    if ((n = t.closest('[data-more]'))) { n.previousElementSibling.classList.add('all'); n.hidden = true; return; }
    if ((n = t.closest('[data-ex]'))) return pickExercise(n.dataset.ex, !!n.closest('.ex'));
    if ((n = t.closest('[data-acc-h]'))) { const acc = n.closest('[data-acc]'); acc.classList.toggle('open'); acc.querySelector(':scope > .collapse')?.classList.toggle('open', acc.classList.contains('open')); return; }
    if ((n = t.closest('[data-gf]'))) {
      n.parentElement.querySelectorAll('.filter').forEach(b => b.classList.toggle('on', b === n));
      scr.querySelectorAll('[data-vars] > [data-g]').forEach((r, i) => showRow(r, n.dataset.gf === 'all' || r.dataset.g === n.dataset.gf, i)); return;
    }
    if ((n = t.closest('[data-rf-k]'))) return filterRules(n);
    if ((n = t.closest('[data-tlf-k]'))) {
      n.parentElement.querySelectorAll('.filter').forEach(b => b.classList.toggle('on', b === n));
      const k = n.dataset.tlfK;
      scr.querySelectorAll('.tl-ev').forEach((r, i) => showRow(r, k === 'all' || r.dataset.dom === k, i));
      scr.querySelectorAll('[data-tlday]').forEach(d => d.hidden = !d.querySelector('.tl-ev:not([hidden])')); return;
    }
    if ((n = t.closest('[data-photo]'))) return openLb(n);
    if ((n = t.closest('[data-pick]'))) { const b = n.querySelector('b'), sm = n.querySelector('small'); b.textContent = n.dataset.pick; sm.textContent = 'готово к загрузке'; n.classList.add('picked'); return; }
    if ((n = t.closest('[data-bs-scan]'))) return busyThen(n, () => { scr.querySelector('[data-bs-up]').hidden = true; const p = scr.querySelector('[data-bs-pre]'); p.hidden = false; enter(p); });
    if ((n = t.closest('[data-bs-cancel]'))) { scr.querySelector('[data-bs-pre]').hidden = true; scr.querySelector('[data-bs-up]').hidden = false; return; }
    if ((n = t.closest('[data-add-row]'))) { const pv = n.previousElementSibling; pv.insertAdjacentHTML('beforeend', `<div class="pv-r"><input class="input sm" placeholder="Метрика"><input class="input sm num" inputmode="decimal" placeholder="0"><input class="input sm" placeholder="ед."><button class="ibtn" data-rm-row aria-label="Удалить строку">${ic('x')}</button></div>`); enter(pv.lastElementChild); pv.lastElementChild.querySelector('input').focus(); return; }
    if ((n = t.closest('[data-rm-row]'))) { n.closest('.pv-r').remove(); return; }
    if ((n = t.closest('[data-edit-m]'))) return editMeasure(n.closest('[data-mrow]'));
    if ((n = t.closest('[data-cancel-edit]'))) return editMeasure(null);
    if ((n = t.closest('[data-supp-edit]'))) {
      const r = n.closest('[data-sid]'), s = SUPPS.find(x => x.id === +r.dataset.sid), f = scr.querySelector('[data-collapse="supp-form"]');
      f.querySelector('h3').textContent = 'Изменить: ' + s.name; f.querySelector('[name="name"]').value = s.name; f.querySelector('[name="dose"]').value = s.dose; f.querySelector('[name="timing"]').value = s.timing;
      return openForm('supp-form', true);
    }
    if ((n = t.closest('[data-vcf]'))) return busyThen(n, () => { const a2 = scr.querySelector('[data-imp-ok]'); a2.hidden = false; enter(a2); scr.scrollTo({ top: 0, behavior: RM ? 'auto' : 'smooth' }); toast('Загружено вариантов: 14'); });
    if ((n = t.closest('[data-day-k]'))) { n.parentElement.querySelectorAll('.opt').forEach(o => o.classList.toggle('on', o === n)); scr.querySelectorAll('[data-day-pane]').forEach(p => { p.hidden = p.dataset.dayPane !== n.dataset.dayK; if (!p.hidden) enter(p); }); return; }
    if ((n = t.closest('[data-brief]'))) {
      const kind = n.dataset.brief, list = BRIEF_OUT[kind], k = st['brief_' + kind] = ((st['brief_' + kind] ?? -1) + 1) % list.length, [tone, icon, msg] = list[k];
      return busyThen(n, () => { const out = scr.querySelector('[data-brief-out]'); out.innerHTML = `<div class="alert ${tone}">${ic(icon)}<div>${msg}</div></div>`; enter(out.firstChild); });
    }
    if ((n = t.closest('[data-tfa-go]'))) {
      const box = n.closest('[data-tfa]'), from = box.dataset.tfa, to = n.dataset.tfaGo; box.dataset.tfa = to; enter(box.querySelector(`[data-tfa-s="${to}"]`));
      if (to === 'on' && from === 'setup') toast('Двухфакторная защита включена.');
      if (to === 'off' && from === 'disable') toast('Двухфакторная защита выключена.');
      return;
    }
    if ((n = t.closest('[data-restart]'))) {
      if (n.classList.contains('busy')) return; n.classList.add('busy', 'spin');
      toast('Перезапускаем приложение… Ждём, пока оно поднимется.', { icon: 'sync' });
      setTimeout(() => { n.classList.remove('busy', 'spin'); toast('Контейнер успешно перезапущен. Все настройки вступили в силу!'); }, 2200); return;
    }
    if ((n = t.closest('[data-restore]'))) return busyThen(n, () => { const a2 = scr.querySelector('[data-restore-ok]'); a2.hidden = false; enter(a2); });
    if ((n = t.closest('[data-share-make]'))) return busyThen(n, () => { const c = scr.querySelector('[data-collapse="share-made"]'); c.classList.add('open'); setTimeout(() => c.scrollIntoView({ behavior: RM ? 'auto' : 'smooth', block: 'start' }), 60); toast('Ссылка создана · действует 14 дней'); });
    if ((n = t.closest('[data-revoke]'))) {
      const r = n.closest('.row'); r.classList.add('dim-soft');
      n.replaceWith(Object.assign(document.createElement('span'), { className: 'm', textContent: 'отозван' }));
      return toast('Ссылка отозвана — документ больше не открывается');
    }
    if ((n = t.closest('[data-chart-save]'))) {
      const f = n.closest('.form'), err = f.querySelector('[data-chart-err]');
      const okSel = [...f.querySelectorAll('[data-srow]')].every(r => r.querySelector('[name="dom"]').value && !r.querySelector('[name="metric"]').disabled);
      if (!okSel) { err.hidden = false; enter(err); return; }
      err.hidden = true; n.dataset.fsave = 'График сохранён'; n.dataset.fshut = 'chart-form'; return fsave(n);
    }
    if ((n = t.closest('[data-add-series]'))) {
      const box = n.previousElementSibling, k = box.children.length; if (k >= 8) return toast('Не больше восьми рядов', { icon: 'info' });
      const c = box.firstElementChild.cloneNode(true);
      c.querySelectorAll('select').forEach((s, i) => { s.selectedIndex = 0; if (i === 1) { s.disabled = true; s.innerHTML = '<option>Выберите метрику</option>'; } if (i === 2) s.hidden = true; });
      c.querySelector('.flabel').textContent = 'Ряд ' + (k + 1); box.appendChild(c); enter(c); return;
    }
    if ((n = t.closest('[data-rm-series]'))) { const box = n.closest('[data-srows]'); if (box.children.length > 1) n.closest('[data-srow]').remove(); [...box.children].forEach((c, i) => c.querySelector('.flabel').textContent = 'Ряд ' + (i + 1)); return; }
    if ((n = t.closest('[data-reveal-pw]'))) { const i = n.parentElement.querySelector('input'), show = i.type === 'password'; i.type = show ? 'text' : 'password'; n.textContent = show ? 'Скрыть' : 'Показать'; return; }
    if ((n = t.closest('[data-login]'))) {
      const f = n.closest('form'), pwi = f.querySelector('[data-lg-pw]'), err = f.querySelector('[data-lg-err]');
      if (!pwi.value) { err.hidden = false; enter(err); pwi.focus(); return; }
      err.hidden = true; n.textContent = 'Проверяем…'; n.disabled = true; setTimeout(() => go('twofa'), RM ? 0 : 700); return;
    }
    if ((n = t.closest('[data-otp-go]'))) return checkOtp(n.closest('form'));
    if ((n = t.closest('[data-pw]'))) { const f = n.closest('form'); if (!st.pwTry) { st.pwTry = 1; const e2 = f.querySelector('[data-lg-err]'); e2.hidden = false; enter(e2); return; } st.pwTry = 0; return go('report'); }
    if ((n = t.closest('[data-retry]'))) return busyThen(n, () => { st.view = 'data'; rerender(); }, 900);
    if ((n = t.closest('[data-seg-local] button'))) { n.parentElement.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === n)); placeInks(n.parentElement.parentElement); return; }
    if ((n = t.closest('.opt'))) return pickOpt(n);
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
  if ((e.key === 'n' || e.key === 'т') && !e.metaKey && !e.ctrlKey && !desk.el.classList.contains('bare')) { desk.openSheet('weight'); }
  if (e.key === 'Escape') INSTANCES.forEach(i => { i.closeSheet(); i.closeLb(); });
});
