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
