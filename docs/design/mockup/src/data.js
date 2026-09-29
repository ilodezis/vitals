/* Demo data — one realistic morning: Tue 29 Sep 2026, 08:14.
   Deterministic (seeded) so the mockup reads the same every time. */

const TODAY = new Date(2026, 8, 29);
const DAY = 864e5;

function rng(seed) { return () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646; }
const r = rng(42);
const noise = (a) => (r() - .5) * 2 * a;

const d0 = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getTime() + n * DAY);
const daysBetween = (a, b) => Math.round((d0(b) - d0(a)) / DAY);

const MONTHS_G = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const MONTHS_S = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const WD = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
const WD_L = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'];

const fmt = (n, d = 1) => (n < 0 ? '−' : '') + Math.abs(n).toFixed(d).replace('.', ',');
const fmtS = (n, d = 1) => (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(d).replace('.', ',');
const fmtI = (n) => Math.round(n).toLocaleString('ru-RU').replace(/\s/g, ' ');
const dShort = (d) => `${d.getDate()} ${MONTHS_S[d.getMonth()]}`;
const dLong = (d) => `${d.getDate()} ${MONTHS_G[d.getMonth()]}`;
function dRel(d) {
  const k = daysBetween(d, TODAY);
  if (k === 0) return 'Сегодня';
  if (k === 1) return 'Вчера';
  if (k < 7) return `${WD[d.getDay()]}, ${dShort(d)}`;
  return dShort(d);
}

/* ---------- Weight: 1 Apr → 29 Sep ---------- */
const PHASES = [
  { from: new Date(2026, 6, 5), to: new Date(2026, 7, 1), dose: 0.25, label: '0,25 мг' },
  { from: new Date(2026, 7, 2), to: TODAY, dose: 0.5, label: '0,5 мг' },
];
const W_KNOTS = [
  [new Date(2026, 3, 1), 96.4], [new Date(2026, 5, 29), 94.0], [new Date(2026, 6, 19), 92.6],
  [new Date(2026, 7, 3), 90.8], [new Date(2026, 8, 1), 88.5], [TODAY, 86.1],
];
function baseW(d) {
  for (let i = 1; i < W_KNOTS.length; i++) {
    const [a, wa] = W_KNOTS[i - 1], [b, wb] = W_KNOTS[i];
    if (d <= b) { const t = (d - a) / (b - a); const e = t * t * (3 - 2 * t) * .35 + t * .65; return wa + (wb - wa) * e; }
  }
  return 86.1;
}
const weights = [];
for (let d = new Date(2026, 3, 1); d <= TODAY; d = addDays(d, 1)) {
  const k = daysBetween(d, TODAY);
  if (k > 0 && r() < (k < 40 ? .28 : .5)) continue;   // not weighed every day
  let w = baseW(d) + noise(.38);
  if (k === 0) w = 86.1;
  weights.push({ date: new Date(d), w: +w.toFixed(1) });
}
// 7-day moving average on calendar days
function maAt(d) {
  const pts = weights.filter(p => { const k = daysBetween(p.date, d); return k >= 0 && k < 7; });
  return pts.length ? pts.reduce((s, p) => s + p.w, 0) / pts.length : null;
}
const weightMA = [];
for (let d = new Date(2026, 3, 1); d <= TODAY; d = addDays(d, 1)) { const v = maAt(d); if (v) weightMA.push({ date: new Date(d), w: v }); }

const lastW = weights[weights.length - 1];
const ma7 = maAt(TODAY);
const weekAgo = weightMA.find(p => daysBetween(p.date, TODAY) === 7).w;

// History list: manual + scans + superseded Garmin rows (product truth: priority)
const weightHistory = [
  { date: TODAY, time: '07:55', w: 86.1, src: 'manual' },
  { date: addDays(TODAY, -1), time: '08:02', w: 86.4, src: 'manual' },
  { date: addDays(TODAY, -1), time: '07:40', w: 86.9, src: 'garmin', superseded: true },
  { date: addDays(TODAY, -3), time: '08:10', w: 86.3, src: 'manual' },
  { date: addDays(TODAY, -4), time: '07:48', w: 86.8, src: 'garmin' },
  { date: addDays(TODAY, -6), time: '08:21', w: 86.9, src: 'manual' },
  { date: addDays(TODAY, -8), time: '09:05', w: 87.2, src: 'manual' },
  { date: addDays(TODAY, -17), time: '10:30', w: 88.0, src: 'bia', note: 'InBody · жир 18,4 %' },
  { date: addDays(TODAY, -17), time: '07:50', w: 88.3, src: 'garmin', superseded: true },
  { date: addDays(TODAY, -19), time: '08:00', w: 88.2, src: 'manual' },
];

/* ---------- Recovery: 14 nights ---------- */
const nights = [];
for (let i = 13; i >= 0; i--) {
  const d = addDays(TODAY, -i);
  const late = i <= 2;
  nights.push({
    date: d,
    sleep: Math.round(i === 0 ? 82 : 76 + noise(9) + (i < 7 ? 3 : 0)),
    hrv: Math.round(i === 0 ? 46 : late ? 45 + noise(2) : 54 + noise(4)),
    rhr: Math.round(i === 0 ? 52 : late ? 53 + noise(1) : 50 + noise(2)),
    stress: Math.round(i === 0 ? 23 : 26 + noise(7)),
    steps: Math.round(i === 0 ? 1715 : 8200 + noise(3600)),
    bb: Math.round(i === 0 ? 94 : 82 + noise(10)),
  });
}
const NORMS = {
  sleep: { lo: 72, hi: 88, better: 1, label: 'Сон', unit: '' },
  hrv: { lo: 50, hi: 58, better: 1, label: 'HRV', unit: 'мс' },
  rhr: { lo: 48, hi: 53, better: -1, label: 'Пульс покоя', unit: 'уд/мин' },
  stress: { lo: 18, hi: 32, better: -1, label: 'Стресс', unit: '' },
  steps: { lo: 7000, hi: 11000, better: 1, label: 'Шаги', unit: '' },
  bb: { lo: 70, hi: 92, better: 1, label: 'Body Battery', unit: '' },
};

// Hypnogram 23:40 → 07:14, 5-min blocks. 0 awake, 1 REM, 2 light, 3 deep
const HYP_START = { h: 23, m: 40 };
const hyp = (() => {
  const plan = [
    [2, 3], [3, 6], [2, 3], [3, 5], [2, 4], [1, 2], [0, 1],
    [2, 4], [3, 4], [2, 5], [1, 4], [2, 4], [3, 2], [2, 5], [1, 5], [0, 1],
    [2, 6], [1, 5], [2, 4], [0, 1], [2, 3], [1, 6], [2, 2], [0, 1],
  ];
  const out = []; plan.forEach(([s, n]) => { for (let i = 0; i < n; i++) out.push(s); });
  return out; // 91 blocks ≈ 7h35m
})();
const stageMin = [0, 0, 0, 0]; hyp.forEach(s => stageMin[s] += 5);

/* ---------- GLP-1 ---------- */
const injections = [
  { date: new Date(2026, 8, 27), site: 'Бедро Л', dose: 0.5 },
  { date: new Date(2026, 8, 20), site: 'Живот П', dose: 0.5 },
  { date: new Date(2026, 8, 13), site: 'Бедро П', dose: 0.5 },
  { date: new Date(2026, 8, 6), site: 'Живот Л', dose: 0.5 },
  { date: new Date(2026, 7, 30), site: 'Бедро Л', dose: 0.5 },
  { date: new Date(2026, 7, 23), site: 'Живот П', dose: 0.5 },
  { date: new Date(2026, 7, 16), site: 'Плечо П', dose: 0.5 },
  { date: new Date(2026, 7, 9), site: 'Живот Л', dose: 0.5 },
];
const sideEffects = [
  { date: new Date(2026, 7, 13), name: 'Запор', sev: 3 },
  { date: new Date(2026, 7, 6), name: 'Тошнота', sev: 2 },
  { date: new Date(2026, 6, 23), name: 'Изжога', sev: 1 },
];
const nextInj = new Date(2026, 9, 4);

/* ---------- Labs (6 Sep) ---------- */
const LAB_DATE = new Date(2026, 8, 6);
const labs = [
  { id: 'vitd', name: 'Витамин D (25-OH)', group: 'Витамины', unit: 'нг/мл', v: 28, lo: 30, hi: 100, min: 0, max: 120, hist: [[new Date(2026, 2, 12), 19], [new Date(2026, 5, 4), 24], [LAB_DATE, 28]] },
  { id: 'tg', name: 'Триглицериды', group: 'Метаболизм', unit: 'мг/дл', v: 128, lo: 0, hi: 150, min: 0, max: 250, hist: [[new Date(2026, 2, 12), 164], [new Date(2026, 5, 4), 141], [LAB_DATE, 128]] },
  { id: 'hba1c', name: 'HbA1c', group: 'Метаболизм', unit: '%', v: 5.3, lo: 4.0, hi: 5.7, min: 3.5, max: 7, d: 1, hist: [[new Date(2026, 2, 12), 5.6], [new Date(2026, 5, 4), 5.4], [LAB_DATE, 5.3]] },
  { id: 'glu', name: 'Глюкоза натощак', group: 'Метаболизм', unit: 'ммоль/л', v: 5.1, lo: 3.9, hi: 5.8, min: 3, max: 7.5, d: 1, hist: [[new Date(2026, 2, 12), 5.6], [new Date(2026, 5, 4), 5.3], [LAB_DATE, 5.1]] },
  { id: 'ins', name: 'Инсулин натощак', group: 'Метаболизм', unit: 'мкЕд/мл', v: 8.3, lo: 2.6, hi: 24.9, min: 0, max: 30, d: 1, hist: [[new Date(2026, 2, 12), 14.2], [new Date(2026, 5, 4), 10.9], [LAB_DATE, 8.3]] },
  { id: 'tsh', name: 'ТТГ', group: 'Гормоны', unit: 'мМЕ/л', v: 2.1, lo: 0.4, hi: 4.0, min: 0, max: 5, d: 1, hist: [[new Date(2026, 2, 12), 2.4], [new Date(2026, 5, 4), 2.2], [LAB_DATE, 2.1]] },
  { id: 'tt', name: 'Тестостерон общий', group: 'Гормоны', unit: 'нмоль/л', v: 21.4, lo: 8.6, hi: 29.0, min: 0, max: 35, d: 1, hist: [[new Date(2026, 2, 12), 17.9], [new Date(2026, 5, 4), 19.6], [LAB_DATE, 21.4]] },
  { id: 'fer', name: 'Ферритин', group: 'Витамины', unit: 'нг/мл', v: 96, lo: 30, hi: 400, min: 0, max: 450, hist: [[new Date(2026, 2, 12), 88], [new Date(2026, 5, 4), 101], [LAB_DATE, 96]] },
];
labs.forEach(m => { m.status = m.v < m.lo ? 'low' : m.v > m.hi ? 'high' : 'ok'; });

/* ---------- Today composition ---------- */
const DATA = {
  TODAY, now: '08:14',
  weights, weightMA, lastW, ma7, weekAgo, weightHistory, PHASES,
  goal: { start: 94.0, target: 80, deadline: new Date(2026, 11, 27) },
  bodyFat: 17.8,
  nights, NORMS, hyp, HYP_START, stageMin,
  injections, sideEffects, nextInj,
  labs, LAB_DATE,
  eaten: 420, kcalTarget: 2100,
  feed: [
    { time: '07:02', dot: 'cool', text: 'Garmin синхронизирован', detail: 'сон 82 · 7 ч 34 мин · HRV 46 мс' },
    { time: '07:40', dot: 'accent', text: 'Утренний бриф отправлен', detail: 'проактивный слой · Telegram' },
    { time: '07:55', dot: 'good', text: 'Вес 86,1 кг', detail: 'вручную' },
    { time: '08:05', dot: 'good', text: 'Завтрак · 420 ккал', detail: 'овсянка, яйца, кофе · белок 31 г' },
  ],
};
DATA.trendWeek = -0.6;
// Display figures agree across screens (Today, Weight, rail)
DATA.ma7 = 86.2; DATA.weekAgo = 87.0;
DATA.weekChanges = [
  { key: 'weight', name: 'Вес', unit: 'кг', from: 87.0, to: 86.2, lo: 80, hi: 80, min: 84.5, max: 88.5, better: -1, go: 'weight' },
  { key: 'sleep', name: 'Сон', unit: '', from: 81.6, to: 84.2, lo: 72, hi: 88, min: 65, max: 95, better: 1, go: 'recovery' },
  { key: 'hrv', name: 'HRV', unit: 'мс', from: 53.8, to: 47.5, lo: 50, hi: 58, min: 40, max: 64, better: 1, go: 'recovery' },
  { key: 'bb', name: 'Body Battery', unit: '', from: 86.1, to: 90.8, lo: 70, hi: 92, min: 60, max: 100, better: 1, go: 'recovery' },
];

/* ==========================================================================
   Demo data for the rest of the screens. Synthetic, deterministic.
   ========================================================================== */
// Seeded streams for the added data: neighbouring seeds of the plain generator move in step, so scatter the seed first.
const rngW = (seed) => rng(Math.floor((Math.sin(seed * 12.9898) * 43758.5453 % 1 + 1) % 1 * 2147483645) + 1);
const dt = (m, d, y = 2026) => new Date(y, m - 1, d);
const fmtHM = (min) => `${Math.floor(min / 60)} ч ${String(min % 60).padStart(2, '0')}`;
const clock = (min) => `${String(Math.floor(min / 60) % 24).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`;

/* ---------- Nights: 21 of them, each with its own hypnogram and curves ---------- */
function hypPlan(i) {
  if (i === 0) return hyp;
  const q = rngW(900 + i * 17), out = [];
  const push = (s, n) => { for (let k = 0; k < n; k++) out.push(s); };
  for (let c = 0; c < 5; c++) {
    push(2, 3 + Math.floor(q() * 4));
    if (c < 3) push(3, 3 + Math.floor(q() * 5));
    push(2, 2 + Math.floor(q() * 3));
    push(1, 2 + c + Math.floor(q() * 3));
    if (q() < .55) push(0, 1);
  }
  return out;
}
const nightsAll = [];
for (let i = 0; i < 21; i++) {
  const h = hypPlan(i), m = [0, 0, 0, 0];           // minutes: awake, REM, light, deep
  h.forEach(s => { m[s] += 5; });
  const q = rngW(300 + i);
  const startMin = i === 0 ? 23 * 60 + 40 : 23 * 60 + 40 + Math.round((q() - .5) * 60 / 5) * 5;
  const inBed = h.length * 5;
  nightsAll.push({
    i, date: addDays(TODAY, -i), hyp: h, stageMin: m,
    start: startMin, end: i === 0 ? 7 * 60 + 14 : startMin + inBed,
    sleepMin: i === 0 ? 454 : inBed - m[0],
    score: i < 14 ? nights[13 - i].sleep : Math.round(76 + (q() - .5) * 16),
    hrv: i < 14 ? nights[13 - i].hrv : Math.round(52 + (q() - .5) * 8),
    awake: i === 0 ? 3 : 1 + Math.floor(q() * 4),
    restless: i === 0 ? 14 : 6 + Math.floor(q() * 20),
    bbChange: i === 0 ? 58 : Math.round(44 + (q() - .5) * 26),
    sleepHr: i === 0 ? 51 : Math.round(51 + (q() - .5) * 5),
    spo2: i === 0 ? 92 : Math.round(93 + q() * 3),
    need: 8 * 60,
    breath: i === 0 || q() < .15,
  });
}
function nightCurves(n) {
  const q = rngW(700 + n.i * 11), len = n.hyp.length, o = { pulse: [], hrv: [], spo2: [], resp: [], stress: [], bb: [], move: [] };
  const bb0 = n.i === 0 ? 36 : Math.round(34 + q() * 10), bb1 = bb0 + n.bbChange;
  const dPulse = { 0: 9, 1: 2, 2: 0, 3: -3 }, dHrv = { 0: -8, 1: -5, 2: 0, 3: 10 };
  const dip = Math.floor(q() * len * .6 + len * .2);
  for (let k = 0; k < len; k++) {
    const s = n.hyp[k], t = k / (len - 1);
    o.pulse.push(+(n.sleepHr + dPulse[s] + Math.sin(k / 5) * 1.6 + (q() - .5) * 2).toFixed(1));
    o.hrv.push(+(n.hrv + dHrv[s] + (q() - .5) * 7).toFixed(1));
    o.spo2.push(Math.abs(k - dip) < 2 ? n.spo2 : +(95.4 + (q() - .5) * 2.2).toFixed(1));
    o.resp.push(+((s === 3 ? 13.2 : 14.6) + (q() - .5) * 1.2).toFixed(1));
    o.stress.push(Math.max(4, Math.round(30 - t * 20 + (s === 0 ? 14 : 0) + (q() - .5) * 8)));
    o.bb.push(Math.round(bb0 + (bb1 - bb0) * Math.pow(t, .85)));
    o.move.push(s === 0 ? +(3 + q() * 4).toFixed(1) : +(q() * 1.3).toFixed(1));
  }
  return o;
}

/* ---------- Garmin activities ---------- */
const activities = [
  { name: 'Силовая · верх', type: 'Силовая тренировка', at: new Date(2026, 8, 24, 18, 30), min: 62, km: null, kcal: 468, avg: 118, max: 151, teA: 3.1, teN: 1.4, elev: null, power: null, zones: [[1, 9], [2, 21], [3, 19], [4, 11], [5, 2]], splits: null },
  { name: 'Утренняя ходьба', type: 'Ходьба', at: new Date(2026, 8, 27, 8, 5), min: 48, km: 4.12, kcal: 236, avg: 104, max: 121, teA: 1.2, teN: 0, elev: 34, power: null, zones: [[1, 14], [2, 32], [3, 2], [4, 0], [5, 0]], splits: [[1, 1.0, 707, 101], [2, 1.0, 702, 103], [3, 1.0, 688, 106], [4, 1.0, 712, 104]] },
  { name: 'Бег · интервалы', type: 'Бег', at: new Date(2026, 8, 26, 7, 30), min: 41, km: 6.31, kcal: 512, avg: 152, max: 174, teA: 3.8, teN: 2.1, elev: 58, power: 236, zones: [[1, 3], [2, 7], [3, 15], [4, 13], [5, 3]], splits: [[1, 1.0, 372, 141], [2, 1.0, 358, 152], [3, 1.0, 341, 161], [4, 1.0, 349, 158], [5, 1.0, 336, 166], [6, 1.0, 344, 163]] },
  { name: 'Силовая · ноги', type: 'Силовая тренировка', at: new Date(2026, 8, 22, 18, 10), min: 71, km: null, kcal: 522, avg: 121, max: 158, teA: 3.4, teN: 1.9, elev: null, power: null, zones: [[1, 8], [2, 24], [3, 26], [4, 11], [5, 2]], splits: null },
  { name: 'Велопрогулка', type: 'Велосипед', at: new Date(2026, 8, 20, 10, 15), min: 92, km: 28.4, kcal: 720, avg: 131, max: 158, teA: 2.9, teN: 0.3, elev: 210, power: 168, zones: [[1, 6], [2, 38], [3, 41], [4, 7], [5, 0]], splits: [[1, 10.0, 1980, 128], [2, 10.0, 1860, 134], [3, 8.4, 1680, 131]] },
  { name: 'Ходьба', type: 'Ходьба', at: new Date(2026, 8, 18, 19, 40), min: 35, km: 3.02, kcal: 168, avg: 98, max: 112, teA: null, teN: null, elev: null, power: null, zones: null, splits: null },
  { name: 'Йога', type: 'Йога', at: new Date(2026, 8, 15, 7, 50), min: 30, km: null, kcal: 84, avg: 84, max: 99, teA: null, teN: null, elev: null, power: null, zones: null, splits: null },
];

/* ---------- Hevy ---------- */
const HEVY = {
  count: 41, last: dt(9, 24), lastSync: 'вс, 27 сен',
  catalog: [
    { id: 'bench', title: 'Жим лёжа', sessions: 14, last: dt(9, 24) },
    { id: 'squat', title: 'Присед со штангой', sessions: 12, last: dt(9, 22) },
    { id: 'row', title: 'Тяга штанги в наклоне', sessions: 11, last: dt(9, 24) },
    { id: 'ohp', title: 'Жим стоя', sessions: 9, last: dt(9, 17) },
    { id: 'rdl', title: 'Румынская тяга', sessions: 8, last: dt(9, 22) },
    { id: 'curl', title: 'Подъём на бицепс', sessions: 13, last: dt(9, 24) },
    { id: 'pullup', title: 'Подтягивания', sessions: 1, last: dt(9, 24) },
    { id: 'skull', title: 'Французский жим', sessions: 6, last: dt(9, 17) },
  ],
  workouts: [
    { date: dt(9, 24), title: 'Верх A', program: 'PPL', min: 62, ex: [
      { id: 'bench', title: 'Жим лёжа', sets: [['w', 40, 10], ['w', 60, 5], ['', 80, 8], ['', 80, 8], ['', 80, 7], ['f', 80, 6]] },
      { id: 'row', title: 'Тяга штанги в наклоне', sets: [['', 70, 10], ['', 70, 10], ['', 70, 9]] },
      { id: 'pullup', title: 'Подтягивания', sets: [['', 5, 8], ['', 5, 7], ['', 5, 6]] },
      { id: 'curl', title: 'Подъём на бицепс', sets: [['', 16, 12], ['', 16, 11], ['d', 12, 12]] },
    ] },
    { date: dt(9, 22), title: 'Ноги', program: 'PPL', min: 71, ex: [
      { id: 'squat', title: 'Присед со штангой', sets: [['w', 60, 8], ['', 100, 6], ['', 100, 6], ['', 100, 5]] },
      { id: 'rdl', title: 'Румынская тяга', sets: [['', 90, 8], ['', 90, 8], ['', 90, 7]] },
    ] },
    { date: dt(9, 17), title: 'Верх B', program: 'PPL', min: 58, ex: [
      { id: 'ohp', title: 'Жим стоя', sets: [['w', 30, 8], ['', 45, 8], ['', 45, 7], ['', 45, 6]] },
      { id: 'skull', title: 'Французский жим', sets: [['', 25, 10], ['', 25, 10], ['', 25, 9]] },
    ] },
    { date: dt(9, 15), title: 'Ноги', program: 'PPL', min: 66, ex: [
      { id: 'squat', title: 'Присед со штангой', sets: [['', 97.5, 6], ['', 97.5, 6], ['', 97.5, 5]] },
    ] },
    { date: dt(9, 10), title: 'Верх A', program: 'PPL', min: 60, ex: [
      { id: 'bench', title: 'Жим лёжа', sets: [['', 77.5, 8], ['', 77.5, 8], ['', 77.5, 7]] },
    ] },
  ],
  progress: {
    bench: { title: 'Жим лёжа', pts: [[dt(8, 13), 72.5, 8], [dt(8, 20), 72.5, 9], [dt(8, 27), 75, 8], [dt(9, 3), 75, 8], [dt(9, 10), 77.5, 8], [dt(9, 17), 77.5, 9], [dt(9, 24), 80, 8]], verdict: { tone: 'good', msg: 'Рабочий вес растёт: +7,5 кг за 6 недель' }, note: 'Лопатки сведены, пауза на груди 1 с' },
    squat: { title: 'Присед со штангой', pts: [[dt(8, 18), 90, 6], [dt(8, 25), 92.5, 6], [dt(9, 1), 95, 6], [dt(9, 8), 95, 5], [dt(9, 15), 97.5, 6], [dt(9, 22), 100, 6]], verdict: { tone: 'good', msg: 'Рабочий вес растёт: +10 кг за 5 недель' }, note: '' },
    row: { title: 'Тяга штанги в наклоне', pts: [[dt(8, 20), 65, 10], [dt(9, 3), 67.5, 10], [dt(9, 10), 67.5, 9], [dt(9, 24), 70, 10]], verdict: null, note: '' },
    ohp: { title: 'Жим стоя', pts: [[dt(8, 26), 42.5, 8], [dt(9, 3), 45, 7], [dt(9, 17), 45, 8]], verdict: { tone: '', msg: 'Плато: 45 кг уже три сессии' }, note: '' },
    rdl: { title: 'Румынская тяга', pts: [[dt(9, 1), 85, 8], [dt(9, 22), 90, 8]], verdict: null, note: '' },
    curl: { title: 'Подъём на бицепс', pts: [[dt(8, 20), 14, 12], [dt(9, 3), 15, 12], [dt(9, 24), 16, 12]], verdict: null, note: '' },
    pullup: { title: 'Подтягивания', pts: [[dt(9, 24), 5, 8]], verdict: null, note: '' },
    skull: { title: 'Французский жим', pts: [[dt(8, 27), 22.5, 10], [dt(9, 3), 22.5, 10], [dt(9, 10), 25, 9], [dt(9, 17), 25, 10]], verdict: null, note: '' },
  },
};

/* ---------- Nutrition ---------- */
const NUTR = { calMin: 1900, calMax: 2100, protein: 150 };
const MEAL_POOL = [
  ['Овсянка, яйца, кофе', .22], ['Гречка с курицей, салат', .34], ['Творог с ягодами', .12], ['Рыба на гриле, рис, овощи', .32],
];
const nutrHist = [];
for (let k = 0; k < 30; k++) {
  const q = rngW(50 + k * 7);
  if (k === 0) { nutrHist.push({ k, date: TODAY, cal: 420, p: 31, f: 13, c: 45, meals: 1 }); continue; }
  if (k === 9 || k === 17) continue;                        // days nothing was logged
  const cal = Math.round((1880 + q() * 480) / 5) * 5, p = Math.round(112 + q() * 52);
  nutrHist.push({ k, date: addDays(TODAY, -k), cal, p, f: Math.round(cal * .28 / 9), c: Math.round((cal - p * 4 - cal * .28) / 4), meals: 3 + Math.floor(q() * 3) });
}
function mealsFor(day) {
  if (day.k === 0) return [{ id: 1, time: '08:05', name: 'Овсянка, яйца, кофе', cal: 420, p: 31, f: 13, c: 45 }];
  const times = ['08:10', '13:20', '16:40', '20:05', '22:00'];
  return MEAL_POOL.slice(0, Math.min(day.meals, 4)).map(([name, share], i) => ({
    id: 10 * day.k + i, time: times[i], name, cal: Math.round(day.cal * share / 5) * 5,
    p: Math.round(day.p * share), f: Math.round(day.f * share), c: Math.round(day.c * share),
  }));
}

/* ---------- HRT: a log of what was taken, nothing more ---------- */
const HRT = {
  catalog: 4,
  last: { name: 'Тестостерон ципионат', date: dt(9, 26) },
  cycle: { kind: 'Курс', name: 'ТРТ · поддерживающий', start: dt(8, 3), end: dt(10, 26), week: 9, weeks: 12, cadence: 90 },
  items: [
    { id: 1, name: 'Тестостерон ципионат', dose: 100, unit: 'мг', every: 7, from: 1 },
    { id: 2, name: 'ХГЧ', dose: 500, unit: 'МЕ', every: 3.5, from: 3 },
  ],
  planned: [[dt(10, 1), 'ХГЧ', '500 МЕ'], [dt(10, 3), 'Тестостерон ципионат', '100 мг'], [dt(10, 4), 'ХГЧ', '500 МЕ'], [dt(10, 8), 'ХГЧ', '500 МЕ']],
  doses: [
    { date: dt(9, 26), name: 'Тестостерон ципионат', dose: '100 мг', ml: '0,5', brand: 'Cyp-200', lab: 'Lab A', batch: 'B-2207', site: 'ventroglute_left' },
    { date: dt(9, 24), name: 'ХГЧ', dose: '500 МЕ', ml: '', brand: '', lab: '', batch: '', site: '' },
    { date: dt(9, 19), name: 'Тестостерон ципионат', dose: '100 мг', ml: '0,5', brand: 'Cyp-200', lab: 'Lab A', batch: 'B-2207', site: 'ventroglute_right' },
    { date: dt(9, 17), name: 'ХГЧ', dose: '500 МЕ', ml: '', brand: '', lab: '', batch: '', site: '' },
    { date: dt(9, 12), name: 'Тестостерон ципионат', dose: '100 мг', ml: '0,5', brand: 'Cyp-200', lab: 'Lab A', batch: 'B-2207', site: 'quad_right' },
    { date: dt(9, 5), name: 'Тестостерон ципионат', dose: '100 мг', ml: '0,5', brand: 'Cyp-200', lab: 'Lab A', batch: 'B-2207', site: 'glute_left' },
    { date: dt(8, 29), name: 'Тестостерон ципионат', dose: '100 мг', ml: '0,5', brand: 'Cyp-200', lab: 'Lab A', batch: 'B-2113', site: 'quad_left' },
    { date: dt(8, 22), name: 'Тестостерон ципионат', dose: '100 мг', ml: '0,5', brand: 'Cyp-200', lab: 'Lab A', batch: 'B-2113', site: 'glute_right' },
  ],
  siteLabels: { glute_left: 'Ягодица Л', glute_right: 'Ягодица П', ventroglute_left: 'Вентроглютеал Л', ventroglute_right: 'Вентроглютеал П', delt_left: 'Дельта Л', delt_right: 'Дельта П', quad_left: 'Квадрицепс Л', quad_right: 'Квадрицепс П', vastus_lateralis_left: 'Латеральная Л', vastus_lateralis_right: 'Латеральная П' },
  sideEffects: [{ date: dt(9, 14), name: 'Акне', sev: 2 }, { date: dt(8, 25), name: 'Задержка воды', sev: 2 }],
  templates: [
    { name: 'ТРТ · поддерживающий', kind: 'Курс', items: [['Тестостерон ципионат', 0], ['ХГЧ', 3]] },
    { name: 'ТРТ · без ХГЧ', kind: 'Курс', items: [['Тестостерон ципионат', 0]] },
  ],
  compounds: [['Тестостерон', ['Тестостерон ципионат · ципионат (мг)', 'Тестостерон энантат · энантат (мг)']], ['Вспомогательные', ['ХГЧ (МЕ)', 'Анастрозол (мг)']]],
};
function hrtRelease() {
  // a schematic estimate of active mg over the last 60 days: what the log implies, not a forecast
  const doses = HRT.doses.filter(d => d.name.startsWith('Тест')).map(d => d.date), days = [];
  const ke = Math.LN2 / 8, ka = Math.LN2 / 1.6;
  for (let t = -60; t <= 0; t++) {
    const now = addDays(TODAY, t); let a = 0;
    doses.forEach(d => { const tau = (now - d) / DAY; if (tau >= 0) a += 100 * .62 * ka / (ka - ke) * (Math.exp(-ke * tau) - Math.exp(-ka * tau)); });
    days.push([now, a]);
  }
  return days;
}

/* ---------- Genetics ---------- */
const VARIANTS = [
  { gene: 'HFE', rsid: 'rs1800562', gt: 'A/G', marker: 'hemochromatosis_carrier', impact: 'Накопление железа', interp: 'Один аллель C282Y: носитель. Риск перегрузки железом при избыточном поступлении.', action: 'Добавки с железом — только при подтверждённом дефиците по ферритину и насыщению трансферрина.', dom: 'supplements' },
  { gene: 'MTHFR', rsid: 'rs1801133', gt: 'C/T', marker: 'mthfr_reduced', impact: 'Сниженная активность фермента (около 65 %)', interp: 'Гетерозиготный вариант C677T: фолатный цикл работает медленнее среднего.', action: 'При подборе добавок учитывать форму фолата; следить за гомоцистеином.', dom: 'supplements' },
  { gene: 'CYP1A2', rsid: 'rs762551', gt: 'A/C', marker: 'caffeine_slow', impact: 'Медленный метаболизм кофеина', interp: 'Кофеин дольше остаётся в крови, поздние порции заметнее влияют на сон.', action: 'Сверять кофеин после 15:00 с оценкой сна.', dom: 'supplements' },
  { gene: 'SLCO1B1', rsid: 'rs4149056', gt: 'T/C', marker: 'statin_myopathy', impact: 'Повышенный риск миопатии на статинах', interp: 'Транспортёр печени работает хуже, выше концентрация статина в крови.', action: 'Сообщить врачу перед назначением статинов.', dom: 'labs' },
  { gene: 'VDR', rsid: 'rs2228570', gt: 'A/G', marker: '', impact: 'Умеренно сниженный ответ на витамин D', interp: 'Рецептор витамина D чуть менее чувствителен.', action: '', dom: 'supplements' },
  { gene: 'FADS1', rsid: 'rs174547', gt: 'T/C', marker: '', impact: 'Сниженная конверсия ALA → EPA', interp: 'Растительные омега-3 превращаются хуже, важнее готовые EPA и DHA.', action: '', dom: 'supplements' },
  { gene: 'FTO', rsid: 'rs9939609', gt: 'A/T', marker: '', impact: 'Склонность к набору веса', interp: 'Один рисковый аллель: чуть выше аппетит и слабее насыщение.', action: '', dom: 'weight' },
  { gene: 'PPARG', rsid: 'rs1801282', gt: 'C/G', marker: '', impact: 'Слегка выше чувствительность к жирам в рационе', interp: 'Эффект небольшой, значим вместе с другими вариантами.', action: '', dom: 'weight' },
  { gene: 'GLP1R', rsid: 'rs6923761', gt: 'G/A', marker: '', impact: 'Возможный вариант ответа на GLP-1', interp: 'Данные ограниченные; наблюдать по динамике веса.', action: '', dom: 'glp1' },
  { gene: 'ACTN3', rsid: 'rs1815739', gt: 'C/T', marker: '', impact: 'Смешанный тип мышечных волокон', interp: 'Подходят и силовая работа, и выносливость.', action: '', dom: 'workouts' },
  { gene: 'APOE', rsid: 'rs429358', gt: 'T/T', marker: '', impact: 'Вариант ε3/ε3: стандартный риск', interp: 'Без отклонений по липидному обмену.', action: '', dom: 'labs' },
  { gene: 'LCT', rsid: 'rs4988235', gt: 'G/G', marker: '', impact: 'Непереносимость лактозы во взрослом возрасте', interp: 'Фермент лактаза почти не вырабатывается после детства.', action: '', dom: 'system' },
  { gene: 'COMT', rsid: 'rs4680', gt: 'A/G', marker: '', impact: 'Средняя скорость распада катехоламинов', interp: 'Промежуточный вариант между «воином» и «мыслителем».', action: '', dom: 'system' },
  { gene: 'MC1R', rsid: 'rs1805007', gt: 'C/T', marker: '', impact: 'Светлая кожа, чувствительность к УФ', interp: 'Выше риск солнечных ожогов, SPF нужен ежедневно.', action: '', dom: 'skincare' },
];
const VGROUP = { supplements: 'sup', workouts: 'sport', weight: 'sport', glp1: 'sport', system: 'health', labs: 'health', skincare: 'health' };

/* ---------- Supplements ---------- */
const SUPPS = [
  { id: 1, name: 'Витамин D3', dose: '2000 МЕ', timing: 'Утро', ev: 'A', on: true, contra: '', note: 'С жирной едой' },
  { id: 2, name: 'Омега-3', dose: '2 г', timing: 'День', ev: 'A', on: true, contra: '', note: 'С едой' },
  { id: 3, name: 'Магний глицинат', dose: '400 мг', timing: 'Ночь', ev: 'B', on: true, contra: 'При почечной недостаточности не применять.', note: '' },
  { id: 4, name: 'Креатин моногидрат', dose: '5 г', timing: 'Утро', ev: 'A', on: false, contra: '', note: 'Пауза на время анализов' },
  { id: 5, name: 'Ашваганда', dose: '300 мг', timing: 'Вечер', ev: 'C', on: false, contra: 'Тиреотоксикоз; сочетание с гормонами щитовидной железы.', note: 'Курс закончен' },
];

/* ---------- Skincare ---------- */
const SKIN = {
  products: [
    { id: 1, name: 'Дифферин', type: 'Ретиноид', ing: 'Адапален 0,1 %', time: 'evening', days: [1, 3, 5], desc: 'Ускоряет обновление клеток, работает по акне и постакне.', use: 'На сухую кожу тонким слоем; крем — через 15–20 минут.', on: true },
    { id: 2, name: 'Азелаиновая 15 %', type: 'Азелаиновая', ing: 'Азелаиновая кислота 15 %', time: 'morning', days: [2, 4, 6], desc: 'Выравнивает тон, снимает покраснения.', use: 'После умывания, до SPF.', on: true },
    { id: 3, name: 'Ниацинамид + SPF 50', type: 'Ниацинамид / SPF', ing: 'Ниацинамид 4 %', time: 'morning', days: [1, 2, 3, 4, 5, 6, 0], desc: 'Дневная защита и контроль себума.', use: 'Не менее двух пальцев на лицо и шею.', on: true },
    { id: 4, name: 'Увлажняющий крем', type: 'Увлажнение', ing: '', time: 'both', days: [1, 2, 3, 4, 5, 6, 0], desc: 'Восстанавливает барьер кожи.', use: '', on: true },
    { id: 5, name: 'BHA-пилинг 2 %', type: 'Пилинг', ing: 'Салициловая кислота 2 %', time: 'evening', days: [0], desc: 'Очищает поры.', use: 'Не в те же вечера, что и ретиноид.', on: false },
  ],
  rules: [
    { sev: 'block', hard: true, kind: 'Сочетаемость активов', msg: 'Ретиноид и кислотный пилинг в один вечер не сочетать.' },
    { sev: 'warn', hard: false, kind: 'Сочетаемость активов', msg: 'Азелаиновая и ретиноид в один вечер — риск раздражения, разнесите по времени суток.' },
    { sev: 'warn', hard: false, kind: 'Препараты и уход', msg: 'Ретиноид и высокие дозы витамина A из добавок дают суммарную нагрузку.' },
  ],
  logs: [
    { date: dt(9, 28), acts: ['Ретиноид', 'Увлажнение'], note: 'Кожа спокойная' },
    { date: dt(9, 27), acts: ['Азелаиновая', 'Ниацинамид / SPF', 'Увлажнение'], note: '' },
    { date: dt(9, 25), acts: ['Ретиноид', 'Увлажнение'], note: 'Лёгкое шелушение на подбородке' },
    { date: dt(9, 23), acts: ['Ниацинамид / SPF', 'Увлажнение'], note: '' },
  ],
  obs: [
    { date: dt(9, 27), inf: 1, pih: 2, zone: 'подбородок', note: 'Меньше воспалений, следы остаются' },
    { date: dt(9, 20), inf: 2, pih: 2, zone: 'щёки', note: '' },
    { date: dt(9, 13), inf: 3, pih: 3, zone: 'подбородок', note: 'После поездки' },
    { date: dt(9, 6), inf: 2, pih: 3, zone: 'лоб', note: '' },
  ],
};

/* ---------- Interactions ---------- */
const RULES = [
  { id: 1, cat: 'absorption', sev: 'warn', type: 'timing', msg: 'Магний и цинк конкурируют за усвоение: принимать с разницей минимум в 2 часа.', a: 'supplements', b: 'supplements', ev: 'B', src: 'Обзор минерального обмена, 2019', h: 2, on: true },
  { id: 2, cat: 'absorption', sev: 'info', type: 'timing', msg: 'Кальций и железо лучше разносить на 2 часа.', a: 'supplements', b: 'supplements', ev: 'A', src: '', h: 2, on: true },
  { id: 3, cat: 'absorption', sev: 'info', type: 'soft', msg: 'Омега-3 усваиваются лучше с жирной едой.', a: 'supplements', b: 'nutrition', ev: 'B', src: '', on: true },
  { id: 4, cat: 'pharmacogenomics', sev: 'block', type: 'hard', msg: 'Носитель HFE C282Y: добавки с железом без подтверждённого дефицита не сочетать.', a: 'genetics', b: 'supplements', ev: 'A', src: 'Клинические рекомендации по гемохроматозу', on: true },
  { id: 5, cat: 'pharmacogenomics', sev: 'info', type: 'soft', msg: 'Медленный CYP1A2: кофеин после 15:00 сильнее влияет на сон.', a: 'genetics', b: 'garmin', ev: 'C', src: '', on: true },
  { id: 6, cat: 'dermatology', sev: 'block', type: 'hard', msg: 'Ретиноид и кислотный пилинг в один вечер не сочетать.', a: 'skincare', b: 'skincare', ev: 'B', src: '', on: true },
  { id: 7, cat: 'dermatology', sev: 'warn', type: 'soft', msg: 'Азелаиновая и ретиноид в один вечер: риск раздражения.', a: 'skincare', b: 'skincare', ev: 'C', src: '', on: true },
  { id: 8, cat: 'lab_safety', sev: 'warn', type: 'soft', msg: '25-OH витамин D ниже нормы при приёме добавки: пересдать через 8–12 недель.', a: 'supplements', b: 'labs', ev: 'A', src: 'Эндокринное общество, 2011', firing: true, on: true },
  { id: 9, cat: 'lab_safety', sev: 'warn', type: 'soft', msg: 'Ферритин ниже 30 нг/мл: перед добавками железа подтвердить дефицит.', a: 'labs', b: 'supplements', ev: 'B', src: '', on: true },
  { id: 10, cat: 'glp1', sev: 'warn', type: 'soft', msg: 'На GLP-1 падает аппетит: белок ниже 100 г в сутки повышает риск потери мышц.', a: 'glp1', b: 'nutrition', ev: 'B', src: '', on: true },
  { id: 11, cat: 'glp1', sev: 'info', type: 'soft', msg: 'Плато веса дольше трёх недель на одной дозе: обсудить с врачом.', a: 'glp1', b: 'weight', ev: 'C', src: '', on: false },
  { id: 12, cat: 'contraindication', sev: 'block', type: 'hard', msg: 'Ашваганда и тиреотоксикоз: противопоказание.', a: 'supplements', b: 'labs', ev: 'B', src: '', on: true },
  { id: 13, cat: 'other', sev: 'block', type: 'hard', msg: 'Скачок веса больше 1,5 кг за сутки: запись блокируется до подтверждения.', a: 'weight', b: 'weight', ev: 'A', src: '', on: true },
];
const DOM_RU = { weight: 'Вес', glp1: 'GLP-1', workouts: 'Тренировки', garmin: 'Garmin', labs: 'Анализы', skincare: 'Кожа', supplements: 'Добавки', genetics: 'Генетика', nutrition: 'Питание', hrt: 'ГЗТ / TRT', timeline: 'Общее', signals: 'Сигналы', body_comp: 'Состав тела' };
const CAT_RU = { absorption: 'Усвоение', pharmacogenomics: 'Фармакогенетика', dermatology: 'Дерматология', lab_safety: 'Безопасность анализов', glp1: 'GLP-1', contraindication: 'Противопоказание', other: 'Прочее' };

/* ---------- Signals ---------- */
const SIGNALS = [
  { d: dt(9, 29), t: '07:41', kind: 'state', key: 'sleepy', raw: 'sleepy', note: 'Проснулся разбитым', v: null },
  { d: dt(9, 28), t: '22:10', kind: 'exposure', key: 'coffee_late', raw: 'кофе_вечером', note: 'Флэт уайт в 21:30', v: 1, unit: 'чашка' },
  { d: dt(9, 28), t: '16:20', kind: 'symptom', key: 'headache', raw: 'headache', note: '', v: 3, unit: 'из 5' },
  { d: dt(9, 27), t: '21:00', kind: 'state', key: 'stress_high', raw: 'stress_high', note: 'Сдача проекта', v: null },
  { d: dt(9, 26), t: '09:12', kind: 'symptom', key: 'headache', raw: 'голова болит', note: 'С утра', v: 2, unit: 'из 5', mis: true },
  { d: dt(9, 24), t: '23:05', kind: 'exposure', key: 'alcohol', raw: 'alcohol', note: 'Бокал вина', v: 1, unit: 'порция' },
  { d: dt(9, 24), t: '07:30', kind: 'state', key: 'sleepy', raw: 'сонливость', note: '', v: null },
  { d: dt(9, 22), t: '18:44', kind: 'symptom', key: 'nausea', raw: 'nausea', note: 'После инъекции, два дня', v: 2, unit: 'из 5' },
  { d: dt(9, 21), t: '13:00', kind: 'state', key: 'good_mood', raw: 'good_mood', note: '', v: null },
  { d: dt(9, 19), t: '22:30', kind: 'exposure', key: 'coffee_late', raw: 'coffee_late', note: '', v: 2, unit: 'чашки' },
  { d: dt(9, 18), t: '10:02', kind: 'symptom', key: 'headache', raw: 'мигрень?', note: 'Не мигрень, по описанию', v: 4, unit: 'из 5', mis: true },
];
const SIGFREQ = [
  { key: 'headache', n: 5, alias: ['голова болит', 'мигрень?'], ex: ['голова болит с утра', 'опять голова', 'мигрень? нет, просто тупая боль'] },
  { key: 'sleepy', n: 4, alias: ['сонливость'], ex: ['проснулся разбитым', 'весь день сонный'] },
  { key: 'coffee_late', n: 4, alias: ['кофе_вечером'], ex: ['флэт уайт в 21:30', 'ещё один кофе вечером'] },
  { key: 'stress_high', n: 3, alias: [], ex: ['сдача проекта'] },
  { key: 'nausea', n: 2, alias: [], ex: ['после инъекции, два дня'] },
  { key: 'alcohol', n: 2, alias: [], ex: ['бокал вина'] },
  { key: 'good_mood', n: 2, alias: [], ex: [] },
];

/* ---------- Timeline ---------- */
const TL = [
  { d: dt(9, 29), kind: 'note', dom: 'timeline', tone: '', title: 'Утренний бриф отправлен', detail: 'проактивный слой · Telegram' },
  { d: dt(9, 27), kind: 'protocol_change', dom: 'glp1', tone: '', title: 'Инъекция GLP-1: семаглутид 0,5 мг', detail: 'Бедро Л' },
  { d: dt(9, 22), kind: 'note', dom: 'weight', tone: 'warn', title: 'Шумный период: соль, ужин в ресторане', detail: '' },
  { d: dt(9, 19), end: dt(9, 21), kind: 'travel', dom: 'workouts', tone: '', title: 'Поездка в горы', detail: 'Ходьба по 12–15 км в день', manual: true },
  { d: dt(9, 12), kind: 'photo', dom: 'weight', tone: '', title: 'Фото прогресса', detail: '' },
  { d: dt(9, 12), kind: 'note', dom: 'body_comp', tone: '', title: 'BIA-скан (InBody 770)', detail: '18,4 %' },
  { d: dt(9, 6), kind: 'note', dom: 'labs', tone: '', title: 'Анализы: 8 маркеров', detail: 'вне нормы: витамин D' },
  { d: dt(9, 2), kind: 'protocol_change', dom: 'workouts', tone: '', title: 'Новая программа тренировок: PPL', detail: 'Три силовых в неделю', manual: true },
  { d: dt(8, 27), end: dt(8, 30), kind: 'illness', dom: 'garmin', tone: 'bad', title: 'Простуда', detail: 'Пульс покоя +6, HRV ниже нормы', manual: true },
  { d: dt(8, 22), kind: 'milestone', dom: 'weight', tone: 'good', title: 'Цель достигнута: 90 кг', detail: '' },
  { d: dt(8, 14), kind: 'side_effect', dom: 'glp1', tone: 'bad', title: 'Запор [3/5]', detail: '' },
  { d: dt(8, 3), kind: 'protocol_change', dom: 'hrt', tone: '', title: 'Начат курс: ТРТ · поддерживающий', detail: '' },
  { d: dt(8, 2), kind: 'protocol_change', dom: 'glp1', tone: '', title: 'Смена дозы GLP-1: семаглутид 0,5 мг', detail: '' },
  { d: dt(7, 12), end: dt(7, 19), kind: 'travel', dom: 'nutrition', tone: '', title: 'Отпуск', detail: 'Питание без записей', manual: true },
  { d: dt(7, 5), kind: 'protocol_change', dom: 'glp1', tone: '', title: 'Начало терапии GLP-1: семаглутид 0,25 мг', detail: '' },
  { d: dt(6, 29), kind: 'note', dom: 'supplements', tone: '', title: 'Начат приём: Витамин D3', detail: '' },
  { d: dt(6, 4), kind: 'note', dom: 'labs', tone: '', title: 'Анализы: 8 маркеров', detail: '' },
  { d: dt(4, 1), kind: 'life_event', dom: 'weight', tone: 'good', title: 'Старт: 96,4 кг', detail: 'Первое взвешивание в Vitals', manual: true },
];
const TL_KIND = { life_event: ['Событие', 'good'], illness: ['Болезнь', 'bad'], travel: ['Поездка', 'cool'], protocol_change: ['Смена протокола', 'violet'], note: ['Заметка', ''], side_effect: ['Побочный эффект', 'bad'], milestone: ['Цель', 'cool'], photo: ['Фото', ''] };
const DOM_ICON = { timeline: 'timeline', weight: 'scale', glp1: 'syringe', garmin: 'pulse', workouts: 'dumbbell', labs: 'flask', nutrition: 'bowl', skincare: 'skincare', supplements: 'pill', genetics: 'dna', body_comp: 'scale', hrt: 'hrt' };

/* ---------- Reports ---------- */
const GOALS = {
  active: [
    { name: 'Дойти до 80 кг', dom: 'weight', status: 'active', target: 80, unit: 'кг', start: 94, current: 86.1, deadline: dt(12, 27), left: 89 },
    { name: 'Витамин D не ниже 40 нг/мл', dom: 'labs', status: 'active', target: 40, unit: 'нг/мл', start: 19, current: 28, deadline: dt(11, 30), left: 62 },
  ],
  closed: [
    { name: 'Дойти до 90 кг', dom: 'weight', status: 'achieved', target: 90, unit: 'кг', current: 90.4, closed: dt(8, 22), margin: 6 },
    { name: 'HbA1c ниже 5,5 %', dom: 'labs', status: 'achieved', target: 5.5, unit: '%', current: 5.3, closed: dt(9, 6), margin: 0 },
    { name: 'Сон в среднем 80+ за неделю', dom: 'garmin', status: 'missed', target: 80, unit: '', margin: -4 },
  ],
};
const DIGEST = {
  date: dt(9, 28), model: 'anthropic/claude-sonnet-4.6', count: 6,
  html: `<h3>Неделя 22–28 сентября</h3>
<p>Вес ушёл с <b>87,0 до 86,2 кг</b> по скользящему среднему за 7 дней: минус 0,8 кг при белке в среднем 128 г в сутки. Темп чуть выше недельной нормы на текущей дозе.</p>
<h4>Сон и восстановление</h4>
<ul><li>Оценка сна в среднем <b>81</b>, ночь на 29-е — лучшая за две недели (82).</li><li>HRV три ночи подряд ниже коридора 50–58 мс, пульс покоя держится на верхней границе.</li><li>Поздний кофе в четверг и вторник совпал с двумя самыми короткими ночами.</li></ul>
<blockquote>Восстановление отстаёт от нагрузки: шесть силовых за две недели плюс поход.</blockquote>
<h4>Цифры недели</h4>
<table><thead><tr><th>Показатель</th><th>Неделя</th><th>Раньше</th></tr></thead><tbody><tr><td>Вес, кг</td><td>86,2</td><td>87,0</td></tr><tr><td>Сон</td><td>81</td><td>79</td></tr><tr><td>HRV, мс</td><td>47</td><td>54</td></tr><tr><td>Белок, г</td><td>128</td><td>121</td></tr></tbody></table>
<p>Ближайшая инъекция по графику — <code>4 октября</code>.</p>`,
  older: [[dt(9, 21), 'Вес минус 0,7 кг за неделю. Сон 79, шаги выше нормы после поездки в горы.'], [dt(9, 14), 'Вес минус 0,5 кг. Ночи короче обычного, восстановление ниже нормы три дня.'], [dt(9, 7), 'Вес минус 0,6 кг. Анализы от 6 сентября: витамин D 28 нг/мл, остальное в норме.'], [dt(8, 31), 'Простуда закончилась, показатели восстановления вернулись к норме.'], [dt(8, 24), 'Цель 90 кг достигнута на шесть дней раньше срока.']],
};
const BRIEF = { date: dt(9, 29), model: 'google/gemini-2.5-flash', text: `Доброе утро. Вес 86,1 кг, среднее за неделю 86,2 (−0,8).\nСон 82 балла, 7 ч 34 мин. HRV 46 мс, третью ночь ниже твоего коридора 50–58.\nВитамин D по анализу от 6 сентября 28 нг/мл, ниже референса.\nИнъекция по графику в воскресенье, 4 октября.` };

/* ---------- Charts ---------- */
const CHART_CAT = {
  weight: { label: 'Вес', metrics: [['weight', 'Вес', 'кг'], ['ma7', 'Среднее за 7 дней', 'кг'], ['bf', 'Процент жира (Navy)', '%'], ['waist', 'Талия', 'см']] },
  garmin: { label: 'Garmin', metrics: [['sleep', 'Оценка сна', ''], ['hrv', 'HRV', 'мс'], ['rhr', 'Пульс покоя', 'уд/мин'], ['steps', 'Шаги', ''], ['bb', 'Body Battery', ''], ['stress', 'Стресс', '']] },
  nutrition: { label: 'Питание', metrics: [['cal', 'Калории', 'ккал'], ['protein', 'Белок', 'г']] },
  workouts: { label: 'Тренировки', metrics: [['work_weight', 'Рабочий вес', 'кг', 'exercise']] },
  labs: { label: 'Анализы', metrics: [['marker', 'Значение маркера', '', 'marker']] },
  glp1: { label: 'GLP-1', metrics: [['dose', 'Доза', 'мг']] },
};
const CHART_PARAMS = { exercise: ['Жим лёжа', 'Присед со штангой', 'Тяга штанги в наклоне'], marker: ['Витамин D (25-OH)', 'Триглицериды', 'HbA1c', 'Глюкоза натощак', 'ТТГ'] };
const CHARTS = [
  { id: 1, name: 'Вес и сон', norm: true, series: [{ k: 'ma', label: 'Вес, среднее 7 дней', tone: '#F4F0F6' }, { k: 'sleep', label: 'Оценка сна', tone: '#6FB6C9' }], span: 60, flags: [[dt(8, 27), 'Простуда'], [dt(9, 2), 'Новая программа']] },
  { id: 2, name: 'HRV и пульс покоя', norm: false, series: [{ k: 'hrv', label: 'HRV, мс', tone: '#BCA4DC' }, { k: 'rhr', label: 'Пульс покоя, уд/мин', tone: '#F4F0F6' }], span: 45, flags: [[dt(8, 27), 'Простуда']] },
  { id: 3, name: 'Жим лёжа: рабочий вес', norm: false, series: [{ k: 'bench', label: 'Рабочий вес, кг', tone: '#F4F0F6' }], span: 47, flags: [[dt(9, 2), 'Новая программа']] },
  { id: 4, name: 'Белок и калории', norm: true, series: [{ k: 'protein', label: 'Белок', tone: '#6FC58E' }, { k: 'cal', label: 'Калории', tone: '#BCA4DC' }], span: 30, flags: [] },
];

/* ---------- Measures ---------- */
const MEAS = {
  navy: [
    [dt(9, 27), 39.0, 84.5, 17.8, 70.8], [dt(9, 20), 39.0, 85.0, 18.0, 70.6], [dt(9, 13), 39.2, 85.6, 18.3, 70.3], [dt(9, 6), 39.0, 86.1, 18.6, 70.0],
    [dt(8, 30), 39.4, 86.8, 19.0, 69.8], [dt(8, 16), 39.5, 87.9, 19.5, 69.4], [dt(8, 2), 39.4, 89.2, 20.2, 68.5], [dt(7, 19), 39.6, 90.6, 20.8, 68.0],
    [dt(6, 29), 39.8, 92.4, 21.4, 66.9], [dt(6, 1), 40.0, 93.8, 22.0, 66.6], [dt(4, 12), 40.2, 96.0, 22.9, 65.7], [dt(4, 1), 40.2, 96.6, 23.2, 65.2],
  ],
  bia: [[dt(6, 12), 20.6], [dt(8, 8), 19.4], [dt(9, 12), 18.4]],
  scans: [
    { date: dt(9, 12), dev: 'InBody 770', n: 24, cats: [
      ['Состав', [['Вес', '88,0', 'кг', ''], ['Скелетно-мышечная масса', '39,2', 'кг', '33,1–40,4'], ['Жировая масса', '16,2', 'кг', '7,9–15,7'], ['Процент жира', '18,4', '%', '10,0–20,0'], ['Безжировая масса', '71,8', 'кг', ''], ['Уровень висцерального жира', '7', '', '1–9']]],
      ['Вода', [['Общая жидкость организма', '53,1', 'л', '43,4–53,0'], ['Внутриклеточная жидкость', '33,0', 'л', '26,6–32,5'], ['Внеклеточная жидкость', '20,1', 'л', '16,3–19,9'], ['Отношение ВнеКЖ/ОВО', '0,379', '', '0,360–0,390']]],
      ['Оценка', [['Фазовый угол', '6,8', '°', ''], ['Балл InBody', '78', '', '70–100']]],
      ['Производные', [['Индекс массы тела', '25,4', 'кг/м²', '18,5–25,0'], ['Основной обмен', '1 842', 'ккал', ''], ['Целевой вес', '82,0', 'кг', '']]],
      ['Посегментно', [['Мышцы · правая рука', '3,9', 'кг', ''], ['Мышцы · левая рука', '3,8', 'кг', ''], ['Мышцы · туловище', '29,9', 'кг', ''], ['Мышцы · правая нога', '10,6', 'кг', ''], ['Мышцы · левая нога', '10,5', 'кг', '']]],
    ] },
    { date: dt(8, 8), dev: 'InBody 770', n: 22, cats: [['Состав', [['Вес', '90,9', 'кг', ''], ['Процент жира', '19,4', '%', '10,0–20,0'], ['Скелетно-мышечная масса', '39,0', 'кг', '33,1–40,4']]]] },
    { date: dt(6, 12), dev: 'МедАсс', n: 14, cats: [['Состав', [['Вес', '94,4', 'кг', ''], ['Процент жира', '20,6', '%', '']]]] },
  ],
  noise: [
    { s: dt(9, 22), e: null, why: 'соль, ужин в ресторане', dir: 'up' },
    { s: dt(8, 12), e: dt(8, 18), why: 'загрузка креатином', dir: 'up' },
  ],
  photos: [dt(9, 12), dt(8, 9), dt(6, 29), dt(4, 1)],
  preview: [['Вес', '88,0', 'кг'], ['Скелетно-мышечная масса', '39,2', 'кг'], ['Жировая масса', '16,2', 'кг'], ['Процент жира', '18,4', '%'], ['Общая жидкость организма', '53,1', 'л'], ['Уровень висцерального жира', '7', ''], ['Фазовый угол', '6,8', '°'], ['Основной обмен', '1 842', 'ккал']],
};

/* ---------- Share (For the doctor) ---------- */
const SHARE = {
  sections: [['weight', 'Вес'], ['body_comp', 'Состав тела'], ['labs', 'Анализы'], ['glp1', 'Препараты ГПП-1'], ['hrt', 'Гормональная терапия'], ['supplements', 'Добавки'], ['garmin', 'Сон и активность'], ['workouts', 'Тренировки'], ['nutrition', 'Питание'], ['skincare', 'Кожа'], ['genetics', 'Генетика'], ['signals', 'Симптомы']],
  presets: {
    full: ['Полный', ['weight', 'body_comp', 'labs', 'glp1', 'hrt', 'supplements', 'garmin', 'workouts', 'nutrition', 'skincare', 'genetics', 'signals'], false],
    labs_meds: ['Анализы и препараты', ['labs', 'glp1', 'hrt', 'supplements'], false],
    endo: ['Эндокринолог', ['weight', 'body_comp', 'labs', 'glp1', 'hrt', 'supplements', 'garmin'], true],
    gp: ['Терапевт / первичный', ['weight', 'labs', 'glp1', 'supplements', 'garmin', 'signals'], true],
    derm: ['Дерматолог', ['skincare', 'supplements', 'hrt', 'labs'], true],
    sports: ['Спортивный врач / чекап', ['weight', 'body_comp', 'labs', 'garmin', 'workouts', 'nutrition'], false],
  },
  list: [
    { title: 'Терапевт, октябрь', doms: ['Вес', 'Анализы', 'Препараты ГПП-1', 'Добавки', 'Сон и активность'], from: dt(7, 1), to: dt(9, 29), exp: dt(10, 13), state: 'live', opened: 0, last: null },
    { title: 'Эндокринолог, август', doms: ['Вес', 'Состав тела', 'Анализы', 'Препараты ГПП-1'], from: dt(5, 1), to: dt(8, 28), exp: dt(9, 4), state: 'expired', opened: 3, last: dt(9, 1) },
    { title: 'Дерматолог', doms: ['Кожа', 'Добавки'], from: dt(6, 1), to: dt(8, 12), exp: dt(8, 26), state: 'revoked', opened: 1, last: dt(8, 13) },
  ],
};

/* ---------- Settings ---------- */
const SET = {
  core: ['Вес', 'Восстановление', 'Анализы', 'Отчёты', 'Графики'],
  optional: ['Тренировки', 'Питание', 'GLP-1', 'ГЗТ / TRT', 'Генетика', 'Добавки', 'Кожа', 'Взаимодействия', 'Сигналы', 'Состав тела', 'Хронология'],
  weekdays: ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'],
  where: ['Дома', 'В офисе', 'В дороге'], gym: ['Зал', 'Дом', 'Отдых'], load: ['Лёгкая', 'Обычная', 'Тяжёлая'],
};
