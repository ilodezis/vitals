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
