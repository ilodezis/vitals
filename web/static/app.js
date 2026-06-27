/**
 * Vitals OS Dashboard - Alpine.js & Chart.js client controller.
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('weightOSDashboard', () => ({
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
            this.overrideFlag = true;
            this.showConfirm = false;
            if (this.lastFormEvent) {
                this.submitForm(this.lastFormEvent);
            }
        },

        cancelOverride() {
            this.showConfirm = false;
            this.overrideFlag = false;
            this.violations = [];
            this.lastFormEvent = null;
        },

        showPhotoModal(id, src, date) {
            this.largePhotoId = id;
            this.largePhotoSrc = src;
            this.largePhotoDate = date;
            this.showLargePhoto = true;
        }
    }));
});

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

    const data = window.vitalsChartData || { raw: [], trend_ma: [], lbm: [], noise: [], phases: [] };

    // Extract all unique dates to form the x-axis timeline
    const allDatesSet = new Set();
    data.raw.forEach(p => allDatesSet.add(p.date));
    data.trend_ma.forEach(p => allDatesSet.add(p.date));
    data.lbm.forEach(p => allDatesSet.add(p.date));
    
    const sortedLabels = Array.from(allDatesSet).sort();

    // Map data to timeline
    const rawMap = new Map(data.raw.map(p => [p.date, p.weight_kg]));
    const trendMap = new Map(data.trend_ma.map(p => [p.date, p.weight_kg]));
    const lbmMap = new Map(data.lbm.map(p => [p.date, p.lbm_kg]));

    const rawData = sortedLabels.map(d => rawMap.has(d) ? rawMap.get(d) : null);
    const trendData = sortedLabels.map(d => trendMap.has(d) ? trendMap.get(d) : null);
    const lbmData = sortedLabels.map(d => lbmMap.has(d) ? lbmMap.get(d) : null);

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
                    yAdjust: 6,
                    color: '#F5A623',
                    backgroundColor: 'rgba(27, 25, 32, 0.85)',
                    padding: 3,
                    font: { family: 'Inter', size: 9, weight: 'bold' }
                }
            };
        });
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
                    borderColor: '#F5A623',
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
                    borderColor: '#A39AB0',
                    borderDash: [4, 4],
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.1,
                    spanGaps: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            devicePixelRatio: window.devicePixelRatio || 2,
            layout: {
                padding: { top: 18, bottom: 14, right: 8 }
            },
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#A39AB0',
                        font: {
                            family: 'Inter',
                            size: 10
                        },
                        boxWidth: 12
                    }
                },
                tooltip: {
                    backgroundColor: '#332F3C',
                    borderColor: '#564E63',
                    borderWidth: 1,
                    titleColor: '#FBB54C',
                    titleFont: {
                        family: 'Inter',
                        size: 11
                    },
                    bodyColor: '#F3F0F6',
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
                        color: 'rgba(163, 154, 176, 0.08)',
                        drawTicks: false
                    },
                    border: {
                        color: 'rgba(163, 154, 176, 0.16)'
                    },
                    ticks: {
                        color: '#A39AB0',
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
                        color: 'rgba(163, 154, 176, 0.08)',
                        drawTicks: false
                    },
                    border: {
                        color: 'rgba(163, 154, 176, 0.16)'
                    },
                    ticks: {
                        color: '#A39AB0',
                        font: {
                            family: 'Inter',
                            size: 9
                        }
                    }
                }
            }
        }
    });
}
if (document.readyState !== 'loading') {
    initWeightChart();
} else {
    document.addEventListener('DOMContentLoaded', initWeightChart);
}
document.addEventListener('htmx:afterSettle', initWeightChart);
