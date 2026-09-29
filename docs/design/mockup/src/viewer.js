/* Viewer: frames, mode switch, fit-to-window. Not part of the product. */
(() => {
  const native = innerWidth < 600 && matchMedia('(pointer: coarse)').matches;
  if (native) document.body.classList.add('native');

  const url = document.getElementById('url');
  const apps = {};
  const start = async () => {
    try { await Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 1500))]); } catch (e) { }
    apps.phone = createApp(document.getElementById('host-phone'));
    if (!native) apps.desk = createApp(document.getElementById('host-desk'), { onNav: (id) => url.textContent = 'vitals.local/' + (id === 'today' ? 'today' : id) });
    const q = new URLSearchParams(location.search);
    if (q.get('mode')) document.querySelector(`[data-mode="${q.get('mode')}"]`)?.click();
    fit();
    const scr = q.get('screen') || 'today';
    Object.entries(apps).forEach(([k, a]) => a.reset(scr === 'more' && k === 'desk' ? 'today' : scr, { intro: true }));
  };

  let mode = 'both';
  const slots = { desk: document.getElementById('slot-desk'), phone: document.getElementById('slot-phone') };
  const DW = 1440, DH = 900, PW = 426, PH = 898;
  function fit() {
    if (native) return;
    const stage = document.getElementById('stage');
    const W = stage.clientWidth - 64, H = stage.clientHeight - 72;
    slots.desk.hidden = mode === 'phone'; slots.phone.hidden = mode === 'desk';
    let sd = 0, sp = 0;
    if (mode === 'phone') sp = Math.min(1, H / PH);
    else if (mode === 'desk') sd = Math.min(1, W / DW, H / DH);
    else { sp = Math.min(1, H / PH); sd = Math.min(1, (W - PW * sp - 56) / DW, H / DH); if (sd < .42) { sp = Math.min(sp, .8); sd = Math.min(1, (W - PW * sp - 56) / DW, H / DH); } }
    const set = (slot, s, w, h) => { slot.style.width = w * s + 'px'; slot.style.height = h * s + 'px'; slot.querySelector('.vscale').style.transform = `scale(${s})`; };
    if (sd) set(slots.desk, sd, DW, DH);
    if (sp) set(slots.phone, sp, PW, PH);
  }
  addEventListener('resize', fit);

  document.getElementById('mode').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    mode = b.dataset.mode;
    b.parentElement.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    fit();
  });
  document.getElementById('jump').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    const j = b.dataset.j;
    Object.entries(apps).forEach(([k, a]) => {
      if (j === 'log') return a.openSheet('weight');
      a.closeSheet();
      if (j === 'more' && k === 'desk') return;
      a.reset(j, { intro: true });
    });
  });
  document.getElementById('replay').addEventListener('click', () => Object.values(apps).forEach(a => a.replay()));
  const notes = document.getElementById('notes');
  document.getElementById('notes-btn').addEventListener('click', () => notes.classList.toggle('open'));
  document.getElementById('stage').addEventListener('click', (e) => { if (notes.classList.contains('open') && !e.target.closest('#notes')) notes.classList.remove('open'); }, true);

  start();
})();
