/**
 * Garmin dashboard — the latest day's intraday curves (stress + Body Battery).
 *
 * window.vitalsGarminIntraday = { "<series_type>": [{ ts, value }, ...], ... }
 * (ts is a local wall-clock ISO string; the server already converted from
 * Garmin's UTC epoch ms).
 *
 * Unlike the custom-chart builder in charts.js, this is a *within-day* view: the
 * x-axis is time of day, not dates, and the series never land in the chart
 * registry (which groups by date). Both series are 0–100 scores, so they share
 * one axis and stay directly comparable — the whole point of drawing them
 * together is seeing a stress spike drain the battery.
 */
function initGarminIntradayChart() {
    const canvas = document.getElementById('garminIntradayChart');
    if (!canvas) return;

    const data = window.vitalsGarminIntraday || {};
    const C = (window.vitalsChartTheme && window.vitalsChartTheme()) || {};

    const SERIES = [
        { key: 'stress', labelKey: 'garmin.series.stress', color: C.bad, fallback: 'Stress' },
        { key: 'body_battery', labelKey: 'garmin.series.body_battery', color: C.good, fallback: 'Body Battery' },
    ];

    // One shared time axis: union of every series' timestamps, in order.
    const allTs = new Set();
    SERIES.forEach(s => (data[s.key] || []).forEach(p => allTs.add(p.ts)));
    const labels = Array.from(allTs).sort();
    if (!labels.length) return;

    const datasets = SERIES.filter(s => (data[s.key] || []).length).map(s => {
        const byTs = new Map((data[s.key] || []).map(p => [p.ts, p.value]));
        return {
            label: (window.t ? window.t(s.labelKey) : s.fallback),
            data: labels.map(ts => (byTs.has(ts) ? byTs.get(ts) : null)),
            borderColor: s.color,
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            pointRadius: 0,
            pointHoverRadius: 3,
            tension: 0.25,
            // false, not true: a gap here means the watch recorded nothing (taken
            // off, or a sentinel reading the parser dropped). Bridging it would
            // draw a straight line through hours that were never measured.
            spanGaps: false,
        };
    });

    const hhmm = ts => (ts || '').slice(11, 16);

    if (canvas._vitalsChart) canvas._vitalsChart.destroy();
    canvas._vitalsChart = new Chart(canvas, {
        type: 'line',
        data: { labels: labels.map(hhmm), datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            devicePixelRatio: window.devicePixelRatio || 2,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'bottom', labels: { color: C.muted, font: { family: 'Inter', size: 10 }, boxWidth: 12 } },
                tooltip: {
                    backgroundColor: C.surface, borderColor: C.line2, borderWidth: 1,
                    titleColor: C.accent2, titleFont: { family: 'Inter', size: 11 },
                    bodyColor: C.fg, bodyFont: { family: 'Inter', size: 10 }, padding: 8,
                },
            },
            scales: {
                x: {
                    grid: { color: C.grid, drawTicks: false },
                    border: { color: C.axisLine },
                    ticks: { color: C.muted, maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { family: 'Inter', size: 9 } },
                },
                y: {
                    min: 0,
                    max: 100,
                    grid: { color: C.grid, drawTicks: false },
                    border: { color: C.axisLine },
                    ticks: { color: C.muted, stepSize: 25, font: { family: 'Inter', size: 9 } },
                },
            },
        },
    });
}

function initGarminIntradayChartSafe() {
    // A throw here must not bubble out of an htmx:afterSettle handler and abort
    // the rest of the swap (same guard as the other chart scripts).
    try { initGarminIntradayChart(); } catch (e) { console.error('garminIntraday init failed', e); }
}

if (document.readyState !== 'loading') {
    initGarminIntradayChartSafe();
} else {
    document.addEventListener('DOMContentLoaded', initGarminIntradayChartSafe);
}

// Registered once: this file lives in <head>, so it does NOT re-execute on a
// boosted navigation — these hooks are what redraw the chart after an hx-boost
// swap into /garmin and after browser back/forward.
if (!window.__garminIntradayBound) {
    window.__garminIntradayBound = true;
    document.addEventListener('htmx:afterSettle', initGarminIntradayChartSafe);
    document.addEventListener('htmx:historyRestore', initGarminIntradayChartSafe);
}
