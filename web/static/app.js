/**
 * Vitals OS Dashboard - Alpine.js & Chart.js client controller.
 */

// ── vitalsLoader: wrapper around the global-loader overlay in base.html ──────
// The overlay HTML element exists in base.html; HTMX hooks show it for slow
// form-POST routes. For fetch()-based flows (body-scan upload) we expose the
// same element via this object so app.js can control it programmatically.
window.vitalsLoader = {
    show(title, text) {
        const el = document.getElementById('global-loader');
        if (!el) return;
        const titleEl = document.getElementById('loader-title');
        const textEl  = document.getElementById('loader-text');
        if (title && titleEl) titleEl.textContent = title;
        if (text  && textEl)  textEl.textContent  = text;
        el.classList.add('is-active');
    },
    hide() {
        const el = document.getElementById('global-loader');
        if (el) el.classList.remove('is-active');
    }
};

// Plain global function (not Alpine.data()/alpine:init) — x-data="weightOSDashboard()"
// calls this directly, so it works the instant this script runs. alpine:init fires
// exactly once, on Alpine's initial boot; a boosted hx-boost navigation re-executes
// this <script> (it lives in <body>) long after that event already fired, so a
// listener registered here would silently never run, leaving weightOSDashboard()
// undefined and throwing "ReferenceError: weightOSDashboard is not defined" the
// first time this page is reached via SPA navigation instead of a hard reload.
window.weightOSDashboard = function () {
    return {
        activeTab: 'log',
        overrideFlag: false,
        showConfirm: false,
        violations: [],
        showLargePhoto: false,
        largePhotoId: null,
        largePhotoSrc: '',
        largePhotoDate: '',
        lastFormEvent: null,
        isEditingLog: false,
        isEditingMeasure: false,

        // U9: restore the tab a save redirected away from (see vitalsStashRestore
        // in base.html <head> — must read this in init(), not later, since
        // window.load fires after Alpine has already built this component).
        init() {
            if (window.__vitalsRestoreTab) {
                this.activeTab = window.__vitalsRestoreTab;
                window.__vitalsRestoreTab = null;
            }
        },

        editWeight(w) {
            this.activeTab = 'log';
            this.isEditingLog = true;
            const form = document.getElementById('form-log');
            if (form) {
                form.elements['date'].value = w.date;
                form.elements['weight_kg'].value = w.weight_kg;
                form.elements['note'].value = w.note || '';
                let idInput = form.querySelector('input[name="id"]');
                if (!idInput) {
                    idInput = document.createElement('input');
                    idInput.type = 'hidden';
                    idInput.name = 'id';
                    form.appendChild(idInput);
                }
                idInput.value = w.id;
                const submitBtn = form.querySelector('button[type="submit"]');
                if (submitBtn) {
                    submitBtn.textContent = window.t('weight.update');
                }
            }
        },

        editMeasurement(m) {
            this.activeTab = 'measure';
            this.isEditingMeasure = true;
            const form = document.getElementById('form-measure');
            if (form) {
                form.elements['date'].value = m.date;
                form.elements['neck_cm'].value = m.neck_cm || '';
                form.elements['waist_cm'].value = m.waist_cm || '';
                if (form.elements['hips_cm']) form.elements['hips_cm'].value = m.hips_cm || '';
                form.elements['note'].value = m.note || '';
                let idInput = form.querySelector('input[name="id"]');
                if (!idInput) {
                    idInput = document.createElement('input');
                    idInput.type = 'hidden';
                    idInput.name = 'id';
                    form.appendChild(idInput);
                }
                idInput.value = m.id;
                const submitBtn = form.querySelector('button[type="submit"]');
                if (submitBtn) {
                    submitBtn.textContent = window.t('weight.update_measures');
                }
            }
        },

        cancelEdit(tab) {
            if (tab === 'log') {
                this.isEditingLog = false;
                const form = document.getElementById('form-log');
                if (form) {
                    form.reset();
                    const idInput = form.querySelector('input[name="id"]');
                    if (idInput) {
                        idInput.remove();
                    }
                    const submitBtn = form.querySelector('button[type="submit"]');
                    if (submitBtn) {
                        submitBtn.textContent = window.t('weight.save');
                    }
                }
            } else if (tab === 'measure') {
                this.isEditingMeasure = false;
                const form = document.getElementById('form-measure');
                if (form) {
                    form.reset();
                    const idInput = form.querySelector('input[name="id"]');
                    if (idInput) {
                        idInput.remove();
                    }
                    const submitBtn = form.querySelector('button[type="submit"]');
                    if (submitBtn) {
                        submitBtn.textContent = window.t('weight.save_measures');
                    }
                }
            }
        },

        async submitForm(e) {
            this.lastFormEvent = e;
            const form = e.target;
            // Block double-submit and show progress on the button.
            const btn = form.querySelector('button[type="submit"]');
            const prevLabel = btn ? btn.textContent : null;
            if (btn) { btn.disabled = true; btn.textContent = window.t('saving'); }
            const restoreBtn = () => { if (btn) { btn.disabled = false; if (prevLabel !== null) btn.textContent = prevLabel; } };

            const formData = new FormData(form);
            // Append override flag explicitly
            formData.set('override', this.overrideFlag ? 'true' : 'false');

            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'hx-request': 'true'
                    }
                });

                if (response.status === 409) {
                    const data = await response.json();
                    this.violations = data.violations;
                    this.showConfirm = true;
                    restoreBtn();
                } else if (response.ok) {
                    // Check if there is a redirection header (HTMX pattern)
                    const redirectUrl = response.headers.get('HX-Redirect') || '/weight';
                    if (window.vitalsStashRestore) window.vitalsStashRestore({ tab: this.activeTab });
                    window.location.href = redirectUrl;
                } else {
                    restoreBtn();
                    if (window.vitalsToast) window.vitalsToast(window.t('save_error'));
                    console.error('Submission failed:', response.statusText);
                }
            } catch (err) {
                restoreBtn();
                if (window.vitalsToast) window.vitalsToast(window.t('network_error'));
                console.error('Request error:', err);
            }
        },

        overrideSave() {
            this.showConfirm = false;
            // Body-composition save uses its own JSON endpoint, not a form submit.
            if (this.bsAwaitingOverride) {
                this.bsAwaitingOverride = false;
                this.bsOverride = true;
                this.bsSave();
                return;
            }
            this.overrideFlag = true;
            if (this.lastFormEvent) {
                this.submitForm(this.lastFormEvent);
            }
        },

        cancelOverride() {
            this.showConfirm = false;
            this.overrideFlag = false;
            this.bsAwaitingOverride = false;
            this.violations = [];
            this.lastFormEvent = null;
        },

        showPhotoModal(id, src, date) {
            this.largePhotoId = id;
            this.largePhotoSrc = src;
            this.largePhotoDate = date;
            this.showLargePhoto = true;
        },

        // ── Body composition (InBody / МедАсс) — upload → preview → save ──────
        bsUploading: false,
        bsPreviewOpen: false,
        bsError: '',
        bsScan: { date: '', device: '', file_key: null, raw_payload_id: null },
        bsRows: [],
        bsOverride: false,
        bsAwaitingOverride: false,
        bsExpanded: {},

        async bsUpload(e) {
            const form = e.target;
            const fileInput = form.querySelector('input[type="file"]');
            if (!fileInput || !fileInput.files.length) {
                this.bsError = window.t('body.error.no_file');
                return;
            }
            this.bsError = '';
            this.bsUploading = true;
            if (window.vitalsLoader) {
                window.vitalsLoader.show(window.t('loader.body_upload_title'), window.t('loader.body_upload_text'));
            }
            try {
                const resp = await fetch('/weight/body-scan/upload', {
                    method: 'POST', body: new FormData(form), headers: { 'hx-request': 'true' }
                });
                const data = await resp.json();
                if (!resp.ok || !data.ok) {
                    this.bsError = (data && data.message) || window.t('body.upload.error');
                } else {
                    this.bsScan = {
                        date: data.scan.date,
                        device: data.scan.device || '',
                        file_key: data.scan.file_key,
                        raw_payload_id: data.scan.raw_payload_id
                    };
                    this.bsRows = (data.scan.metrics || []).map(r => ({ ...r }));
                    this.bsOverride = false;
                    this.bsPreviewOpen = true;
                }
            } catch (err) {
                this.bsError = window.t('network_error');
            } finally {
                this.bsUploading = false;
                if (window.vitalsLoader) window.vitalsLoader.hide();
                form.reset();
                const hint = form.querySelector('.v-file-drop__hint');
                if (hint && hint.dataset.default) hint.textContent = hint.dataset.default;
            }
        },

        bsAddRow() {
            this.bsRows.push({ metric_key: '', label: '', value: null, unit: '', ref_low: null, ref_high: null, segment: null, category: 'other' });
        },
        bsRemoveRow(i) { this.bsRows.splice(i, 1); },
        bsCancelPreview() { this.bsPreviewOpen = false; this.bsRows = []; this.bsError = ''; },

        async bsSave() {
            const rows = this.bsRows.filter(r => r.value !== null && r.value !== '' && (r.label || r.metric_key));
            const payload = {
                date: this.bsScan.date,
                device: this.bsScan.device || null,
                file_key: this.bsScan.file_key,
                raw_payload_id: this.bsScan.raw_payload_id,
                note: null,
                override: this.bsOverride,
                metrics: rows
            };
            try {
                const resp = await fetch('/weight/body-scan/confirm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'hx-request': 'true' },
                    body: JSON.stringify(payload)
                });
                if (resp.status === 409) {
                    const d = await resp.json();
                    this.violations = d.violations;
                    this.bsAwaitingOverride = true;
                    this.showConfirm = true;
                    return;
                }
                if (resp.ok) {
                    if (window.vitalsStashRestore) window.vitalsStashRestore({ tab: this.activeTab });
                    window.location.href = '/weight';
                } else if (window.vitalsToast) {
                    window.vitalsToast(window.t('save_error'));
                }
            } catch (err) {
                if (window.vitalsToast) window.vitalsToast(window.t('network_error'));
            }
        },

        bsToggleDetail(id) { this.bsExpanded[id] = !this.bsExpanded[id]; }
    };
};

function formatDateStr(dateStr) {
    if (!dateStr) return '';
    const match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) {
        return `${match[3]}-${match[2]}-${match[1]}`;
    }
    return dateStr;
}

// ── Chart.js Setup ───────────────────────────────────────────────────────────

function initWeightChart() {
    const canvas = document.getElementById('weightChart');
    if (!canvas) return;

    const C = (window.vitalsChartTheme && window.vitalsChartTheme()) || {};
    const data = window.vitalsChartData || { raw: [], trend_ma: [], lbm: [], noise: [], phases: [], bia: null };

    // BIA (InBody/МедАсс) overlay — a second LBM source shown alongside Navy.
    const biaLbm = (data.bia && data.bia.lbm) ? data.bia.lbm : [];

    // Extract all unique dates to form the x-axis timeline
    const allDatesSet = new Set();
    data.raw.forEach(p => allDatesSet.add(p.date));
    data.trend_ma.forEach(p => allDatesSet.add(p.date));
    data.lbm.forEach(p => allDatesSet.add(p.date));
    biaLbm.forEach(p => allDatesSet.add(p.date));

    const sortedLabels = Array.from(allDatesSet).sort();

    // Map data to timeline
    const rawMap = new Map(data.raw.map(p => [p.date, p.weight_kg]));
    const trendMap = new Map(data.trend_ma.map(p => [p.date, p.weight_kg]));
    const lbmMap = new Map(data.lbm.map(p => [p.date, p.lbm_kg]));
    const biaLbmMap = new Map(biaLbm.map(p => [p.date, p.value]));

    const rawData = sortedLabels.map(d => rawMap.has(d) ? rawMap.get(d) : null);
    const trendData = sortedLabels.map(d => trendMap.has(d) ? trendMap.get(d) : null);
    const lbmData = sortedLabels.map(d => lbmMap.has(d) ? lbmMap.get(d) : null);
    const biaLbmData = sortedLabels.map(d => biaLbmMap.has(d) ? biaLbmMap.get(d) : null);

    // Annotations for noise markers
    const annotations = {};
    if (data.noise && data.noise.length > 0) {
        data.noise.forEach((range, idx) => {
            const startIdx = sortedLabels.indexOf(range.start);
            const endIdx = range.end ? sortedLabels.indexOf(range.end) : sortedLabels.length - 1;

            if (startIdx !== -1) {
                annotations[`noise_${idx}`] = {
                    type: 'box',
                    xMin: startIdx - 0.2,
                    xMax: endIdx !== -1 ? endIdx + 0.2 : sortedLabels.length - 1 + 0.2,
                    backgroundColor: 'rgba(232, 112, 86, 0.07)',
                    borderColor: 'rgba(232, 112, 86, 0.18)',
                    borderWidth: 1,
                    label: {
                        display: true,
                        content: window.t('chart.noise_period'),
                        position: 'center',
                        rotation: -90,
                        color: 'rgba(232, 112, 86, 0.7)',
                        font: {
                            family: 'Inter',
                            size: 9,
                            weight: 'bold'
                        }
                    }
                };
            }
        });
    }

    // GLP-1 dose phases — teal tinted bands behind the trend. Start/end dates may
    // not be exact weight points, so map them to the nearest label index by ISO
    // string comparison (sortedLabels are ISO dates → lexicographically ordered).
    if (data.phases && data.phases.length > 0) {
        const lastLabelIdx = sortedLabels.length - 1;

        // 1. Map each index in sortedLabels to its corresponding phase index (last active phase wins)
        const labelPhaseIndices = sortedLabels.map(dateStr => {
            return data.phases.findIndex(p => {
                return dateStr >= p.start && (!p.end || dateStr <= p.end);
            });
        });

        // 2. Identify the contiguous blocks of phase indices
        const blocks = [];
        let currentBlock = null;

        for (let i = 0; i <= lastLabelIdx; i++) {
            const phaseIdx = labelPhaseIndices[i];
            if (phaseIdx === -1) continue; // skip if no phase active for this log

            if (currentBlock && currentBlock.phaseIdx === phaseIdx) {
                currentBlock.endIdx = i;
            } else {
                if (currentBlock) {
                    blocks.push(currentBlock);
                }
                currentBlock = {
                    phaseIdx: phaseIdx,
                    startIdx: i,
                    endIdx: i
                };
            }
        }
        if (currentBlock) {
            blocks.push(currentBlock);
        }

        // 3. Draw the boxes for the blocks, making them touch at the boundaries
        blocks.forEach((block, idx) => {
            const phase = data.phases[block.phaseIdx];

            // Left boundary: if first block, extend to -0.4, else touch the previous block at middle point
            const xMin = idx === 0 ? -0.4 : (blocks[idx - 1].endIdx + block.startIdx) / 2;

            // Right boundary: if last block, extend to lastIdx + 0.4, else touch the next block at middle point
            const xMax = idx === blocks.length - 1 ? lastLabelIdx + 0.4 : (block.endIdx + blocks[idx + 1].startIdx) / 2;

            const drugMap = {
                'semaglutide': window.t('chart.drug_semaglutide') || 'semaglutide',
                'tirzepatide': window.t('chart.drug_tirzepatide') || 'tirzepatide'
            };
            const drugKey = phase.drug || '';
            const drug = drugMap[drugKey.toLowerCase()] || drugKey || 'GLP-1';
            const dose = phase.dose_mg !== undefined && phase.dose_mg !== null ? `${phase.dose_mg} ${window.t('chart.dose_mg')}` : '';
            const content = dose ? [drug, dose] : [drug];

            annotations[`phase_${block.phaseIdx}`] = {
                type: 'box',
                xMin: xMin,
                xMax: xMax,
                backgroundColor: 'rgba(245, 166, 35, 0.07)',
                borderColor: 'rgba(245, 166, 35, 0.18)',
                borderWidth: 1,
                drawTime: 'beforeDatasetsDraw',
                label: {
                    display: true,
                    content: content,
                    position: { x: 'center', y: 'start' },
                    // The first band hugs the left edge; nudge its label inward so a
                    // narrow first phase doesn't clip the drug name (U15).
                    xAdjust: idx === 0 ? 22 : 0,
                    yAdjust: 6,
                    color: C.accent,
                    backgroundColor: 'rgba(27, 25, 32, 0.85)',
                    padding: 3,
                    font: { family: 'Inter', size: 9, weight: 'bold' }
                }
            };
        });
    }

    // Timeline flags (manual annotations) — shared builder also used by charts.js.
    if (window.vitalsBuildAnnotations) {
        Object.assign(annotations, window.vitalsBuildAnnotations(data.annotations, sortedLabels));
    }

    if (window.vitalsChartInstance) {
        window.vitalsChartInstance.destroy();
    }
    window.vitalsChartInstance = new Chart(canvas, {
        type: 'line',
        data: {
            labels: sortedLabels.map(formatDateStr),
            datasets: [
                {
                    label: window.t('chart.trend_ma'),
                    data: trendData,
                    borderColor: C.accent,
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.15,
                    spanGaps: true
                },
                {
                    label: window.t('chart.weight_points'),
                    data: rawData,
                    borderColor: 'rgba(243, 240, 246, 0.25)',
                    backgroundColor: 'rgba(243, 240, 246, 0.6)',
                    borderWidth: 0,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    showLine: false,
                    spanGaps: false
                },
                {
                    label: window.t('chart.lbm'),
                    data: lbmData,
                    borderColor: C.muted,
                    borderDash: [4, 4],
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.1,
                    spanGaps: true
                },
                // BIA lean mass (InBody/МедАсс) — distinct teal, points + light line,
                // so a measured scan reads clearly next to the Navy estimate.
                {
                    label: window.t('chart.bia_lbm'),
                    data: biaLbmData,
                    borderColor: C.cool,
                    backgroundColor: C.cool,
                    borderWidth: 1.5,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    tension: 0.1,
                    spanGaps: true,
                    hidden: biaLbm.length === 0
                }
            ]
        },
        options: {
            // responsive:false + manual resize-on-window-resize eliminates the
            // ResizeObserver → chart.resize() → layout-change → ResizeObserver loop
            // that fires every scroll frame when the <main> scrollbar appears.
            responsive: false,
            maintainAspectRatio: false,
            devicePixelRatio: window.devicePixelRatio || 2,
            layout: {
                // Symmetric left/right padding (U15): gives the first GLP-1 phase
                // label room so a multi-word drug name isn't clipped at the left edge.
                padding: { top: 18, bottom: 14, left: 8, right: 8 }
            },
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: C.muted,
                        font: {
                            family: 'Inter',
                            size: 10
                        },
                        boxWidth: 12
                    }
                },
                tooltip: {
                    backgroundColor: C.surface,
                    borderColor: C.line2,
                    borderWidth: 1,
                    titleColor: C.accent2,
                    titleFont: {
                        family: 'Inter',
                        size: 11
                    },
                    bodyColor: C.fg,
                    bodyFont: {
                        family: 'Inter',
                        size: 10
                    },
                    padding: 8,
                    displayColors: true
                },
                annotation: {
                    annotations: annotations
                }
            },
            scales: {
                x: {
                    grid: {
                        color: C.grid,
                        drawTicks: false
                    },
                    border: {
                        color: C.axisLine
                    },
                    ticks: {
                        color: C.muted,
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 8,
                        font: {
                            family: 'Inter',
                            size: 9
                        }
                    }
                },
                y: {
                    grid: {
                        color: C.grid,
                        drawTicks: false
                    },
                    border: {
                        color: C.axisLine
                    },
                    ticks: {
                        color: C.muted,
                        font: {
                            family: 'Inter',
                            size: 9
                        }
                    }
                }
            }
        }
    });

    // Manually size the canvas to fill its fixed-height wrapper.
    // This runs once on init and again on window resize (debounced) —
    // NOT during scroll, which eliminates the ResizeObserver loop entirely.
    function sizeChart() {
        const wrapper = canvas.parentElement;
        if (!wrapper || !window.vitalsChartInstance) return;
        const w = wrapper.clientWidth;
        const h = wrapper.clientHeight;
        if (w > 0 && h > 0) {
            canvas.style.width  = w + 'px';
            canvas.style.height = h + 'px';
            window.vitalsChartInstance.resize(w, h);
        }
    }
    sizeChart();

    // Debounced window resize handler — fires at most once per 200ms after
    // the user stops resizing the window (NOT during scroll).
    let _chartResizeTimer = null;
    window.removeEventListener('resize', window._vitalsChartResizeHandler);
    window._vitalsChartResizeHandler = function () {
        clearTimeout(_chartResizeTimer);
        _chartResizeTimer = setTimeout(sizeChart, 200);
    };
    window.addEventListener('resize', window._vitalsChartResizeHandler);
}
function initWeightChartSafe() {
    // A throw here must not bubble out of an htmx:afterSettle / view-transition
    // callback — that can leave the swap unfinished and <main> stuck invisible.
    try { initWeightChart(); } catch (e) { console.error('weightChart init failed', e); }
}

if (document.readyState !== 'loading') {
    initWeightChartSafe();
} else {
    document.addEventListener('DOMContentLoaded', initWeightChartSafe);
}

// Register boosted-navigation hooks ONCE. This page's <script src> re-executes on
// every hx-boost swap into it, so an unguarded addEventListener stacked another
// afterSettle listener per visit (N visits → N redundant re-inits). historyRestore
// covers browser back/forward, where htmx restores a snapshot whose <canvas> is
// blank until the chart is re-drawn.
if (!window.__weightChartBound) {
    window.__weightChartBound = true;
    document.addEventListener('htmx:afterSettle', initWeightChartSafe);
    document.addEventListener('htmx:historyRestore', initWeightChartSafe);
}
