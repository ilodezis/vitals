/**
 * Labs module — per-marker history chart.
 * Plots window.labChartData.points (value over time) on #labChart, with the
 * reference low/high drawn as faint dashed bands so out-of-range points stand out.
 */
function initLabChart() {
    const canvas = document.getElementById('labChart');
    if (!canvas) return;

    const C = (window.vitalsChartTheme && window.vitalsChartTheme()) || {};
    const data = (window.labChartData && window.labChartData.points) || [];
    const labels = data.map(p => p.date);
    const values = data.map(p => p.value);
    const refLow = data.map(p => (p.ref_low != null ? p.ref_low : null));
    const refHigh = data.map(p => (p.ref_high != null ? p.ref_high : null));

    // Colour each point red when out of its range.
    const pointColors = data.map(p => {
        const lo = p.ref_low, hi = p.ref_high;
        const bad = (lo != null && p.value < lo) || (hi != null && p.value > hi);
        return bad ? C.bad : C.accent2;
    });

    if (window.labsChartInstance) {
        window.labsChartInstance.destroy();
    }
    window.labsChartInstance = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: window.t('chart.value'),
                    data: values,
                    borderColor: C.accent,
                    backgroundColor: C.accentSoft,
                    borderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: pointColors,
                    tension: 0.15,
                    fill: true,
                    spanGaps: true
                },
                {
                    label: window.t('chart.ref_low'),
                    data: refLow,
                    borderColor: 'rgba(163, 154, 176, 0.45)',
                    borderDash: [4, 4],
                    borderWidth: 1,
                    pointRadius: 0,
                    spanGaps: true
                },
                {
                    label: window.t('chart.ref_high'),
                    data: refHigh,
                    borderColor: 'rgba(163, 154, 176, 0.45)',
                    borderDash: [4, 4],
                    borderWidth: 1,
                    pointRadius: 0,
                    spanGaps: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            devicePixelRatio: window.devicePixelRatio || 2,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: C.muted, font: { family: 'Inter', size: 10 }, boxWidth: 12 }
                },
                tooltip: {
                    backgroundColor: C.surface,
                    borderColor: C.line2,
                    borderWidth: 1,
                    titleColor: C.accent2,
                    titleFont: { family: 'Inter', size: 11 },
                    bodyColor: C.fg,
                    bodyFont: { family: 'Inter', size: 10 },
                    padding: 8
                }
            },
            scales: {
                x: {
                    grid: { color: C.grid, drawTicks: false },
                    border: { color: C.axisLine },
                    ticks: { color: C.muted, maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { family: 'Inter', size: 9 } }
                },
                y: {
                    grid: { color: C.grid, drawTicks: false },
                    border: { color: C.axisLine },
                    ticks: { color: C.muted, font: { family: 'Inter', size: 9 } }
                }
            }
        }
    });
}
function initLabChartSafe() {
    try { initLabChart(); } catch (e) { console.error('labChart init failed', e); }
}
if (document.readyState !== 'loading') {
    initLabChartSafe();
} else {
    document.addEventListener('DOMContentLoaded', initLabChartSafe);
}
// Register boosted-navigation hooks once (this script re-runs on every hx-boost
// swap into /labs); historyRestore re-draws the chart after browser back/forward.
if (!window.__labChartBound) {
    window.__labChartBound = true;
    document.addEventListener('htmx:afterSettle', initLabChartSafe);
    document.addEventListener('htmx:historyRestore', initLabChartSafe);
}
