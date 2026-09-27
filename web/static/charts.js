/**
 * Custom chart builder — a shared multi-series renderer plus the Alpine
 * component backing the builder form.
 *
 * window.vitalsCustomCharts = { "<chart-id>": { normalize, series: [
 *   { label, unit, color_slot, points: [{date, value}] }, ...
 * ] }, ... }
 *
 * Series with different units get their own Y axis (up to 2 visible; a 3rd+
 * unit still scales its dataset but doesn't draw its own axis, to avoid an
 * unreadable pile-up). When `normalize` is on, every series is indexed to its
 * own first value (100 = start) and shares one axis instead — a more honest
 * comparison than stacking independently-scaled axes.
 */
/**
 * Extra Chart.js hover mode: the point nearest the cursor's x, one per series.
 *
 * None of the built-ins can pair curves sampled on different clocks. 'index'
 * matches datasets by position in the array, so on the Garmin day chart it reads
 * stress[200] (16:40) against heart_rate[200] (06:40); 'x' returns only the points
 * the cursor physically overlaps, which at ~1 px spacing is two heart-rate samples
 * and no stress at all. Either way the tooltip lies.
 *
 * It lives here rather than next to one chart because both garmin.js and
 * garmin_sleep.js need it, and charts.js is already the file the others load
 * after (see the script order in base.html). Registered once on the global Chart
 * and guarded, since a boosted navigation re-runs inits but not this file.
 */
/**
 * Charts draw in their final state. Every tap is a full page load, so Chart.js's
 * default 1 s grow-in animation replayed on each navigation and made every page
 * feel a second slower than it was. charts.js runs before every other script
 * that builds a chart, so this one default covers them all.
 */
if (window.Chart) Chart.defaults.animation = false;

if (window.Chart && !Chart.Interaction.modes.nearestByTime) {
    Chart.Interaction.modes.nearestByTime = (chart, e, options, useFinalPosition) => {
        const position = Chart.helpers.getRelativePosition(e, chart);
        const items = [];
        chart.getSortedVisibleDatasetMetas().forEach(meta => {
            let best = null;
            let bestDistance = Infinity;
            meta.data.forEach((element, index) => {
                if (element.skip) return;
                const distance = Math.abs(element.getProps(['x'], useFinalPosition).x - position.x);
                if (distance < bestDistance) {
                    bestDistance = distance;
                    best = { element, datasetIndex: meta.index, index };
                }
            });
            if (best) items.push(best);
        });
        return items;
    };
}

function vitalsFormatDateStr(dateStr) {
    if (!dateStr) return '';
    const match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) return `${match[3]}-${match[2]}-${match[1]}`;
    return dateStr;
}

function renderCustomChart(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const C = (window.vitalsChartTheme && window.vitalsChartTheme()) || {};
    // Same reasoning as the weight chart in app.js: eight dd-mm-yyyy ticks across
    // a phone's canvas run together into one string of digits.
    const phone = window.matchMedia('(max-width: 767px)').matches;
    // Multi-series categorical palette, drawn from the design tokens. Ordered so
    // consecutive series land on well-separated hues (amber → teal → green →
    // violet …) before the warmer tones repeat.
    const palette = [C.accent, C.cool, C.good, C.violet, C.bad, C.warn, C.accent2, C.muted];

    const series = (config && config.series) || [];
    const normalize = !!(config && config.normalize);

    const allDates = new Set();
    series.forEach(s => (s.points || []).forEach(p => allDates.add(p.date)));
    const labels = Array.from(allDates).sort();

    // unit -> axis id, in first-seen order (skipped entirely when normalizing).
    const unitAxis = new Map();
    if (!normalize) {
        series.forEach(s => {
            const unit = s.unit || '—';
            if (!unitAxis.has(unit)) unitAxis.set(unit, `y${unitAxis.size}`);
        });
    }

    const datasets = series.map(s => {
        const byDate = new Map((s.points || []).map(p => [p.date, p.value]));
        let data = labels.map(d => (byDate.has(d) ? byDate.get(d) : null));
        if (normalize) {
            const base = data.find(v => v != null && v !== 0);
            data = base == null ? data : data.map(v => (v == null ? null : (100 * v) / base));
        }
        const color = palette[(s.color_slot || 0) % palette.length];
        return {
            label: s.label,
            data,
            borderColor: color,
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            tension: 0.15,
            spanGaps: true,
            yAxisID: normalize ? 'y_norm' : unitAxis.get(s.unit || '—'),
        };
    });

    const axisTick = { color: C.muted, font: { family: 'Inter', size: 9 } };
    const scales = {
        x: {
            grid: { color: C.grid, drawTicks: false },
            border: { color: C.axisLine },
            ticks: { color: C.muted, maxRotation: 0, autoSkip: true, maxTicksLimit: phone ? 4 : 8, font: { family: 'Inter', size: 9 } },
        },
    };
    if (normalize) {
        scales.y_norm = {
            position: 'left',
            grid: { color: C.grid, drawTicks: false },
            border: { color: C.axisLine },
            ticks: axisTick,
            title: { display: true, text: (window.t ? window.t('chart.normalized_axis') : '= 100 at start'), color: C.muted, font: { family: 'Inter', size: 9 } },
        };
    } else {
        let idx = 0;
        unitAxis.forEach((axisId, unit) => {
            scales[axisId] = {
                position: idx % 2 === 0 ? 'left' : 'right',
                display: idx < 2,
                grid: { display: idx === 0, color: C.grid, drawTicks: false },
                border: { color: C.axisLine },
                ticks: axisTick,
                title: { display: idx < 2, text: unit, color: C.muted, font: { family: 'Inter', size: 9 } },
            };
            idx += 1;
        });
    }

    // Timeline flags (manual annotations) — same shared builder as app.js.
    const annotations = window.vitalsBuildAnnotations
        ? window.vitalsBuildAnnotations(config && config.annotations, labels)
        : {};

    if (canvas._vitalsChart) canvas._vitalsChart.destroy();
    canvas._vitalsChart = new Chart(canvas, {
        type: 'line',
        data: { labels: labels.map(vitalsFormatDateStr), datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            devicePixelRatio: window.devicePixelRatio || 2,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'bottom', labels: { color: C.muted, font: { family: 'Inter', size: phone ? 9 : 10 }, boxWidth: phone ? 8 : 12, boxHeight: phone ? 8 : undefined, padding: phone ? 6 : 10 } },
                tooltip: {
                    backgroundColor: C.surface, borderColor: C.line2, borderWidth: 1,
                    titleColor: C.accent2, titleFont: { family: 'Inter', size: 11 },
                    bodyColor: C.fg, bodyFont: { family: 'Inter', size: 10 }, padding: 8,
                },
                annotation: { annotations },
            },
            scales,
        },
    });
}

function initCustomCharts() {
    Object.entries(window.vitalsCustomCharts || {}).forEach(([id, config]) => {
        renderCustomChart(`customChart-${id}`, config);
    });
}
function initCustomChartsSafe() {
    try { initCustomCharts(); } catch (e) { console.error('customCharts init failed', e); }
}
if (document.readyState !== 'loading') {
    initCustomChartsSafe();
} else {
    document.addEventListener('DOMContentLoaded', initCustomChartsSafe);
}
// Register boosted-navigation hooks once (this script re-runs on every hx-boost
// swap into /charts); historyRestore re-draws after browser back/forward.
if (!window.__customChartsBound) {
    window.__customChartsBound = true;
    document.addEventListener('htmx:afterSettle', initCustomChartsSafe);
    document.addEventListener('htmx:historyRestore', initCustomChartsSafe);
}

/** Alpine component backing the "new chart" builder form. */
function chartBuilder(catalog) {
    return {
        catalog: catalog || {},
        name: '',
        normalize: false,
        series: [{ domain: '', metricKey: '', param: '', open: null }],
        maxSeries: 8,
        domains() {
            return Object.keys(this.catalog);
        },
        metricsFor(domain) {
            return (this.catalog[domain] && this.catalog[domain].metrics) || [];
        },
        metricInfo(domain, metricKey) {
            return this.metricsFor(domain).find(m => m.key === metricKey) || null;
        },
        paramsFor(domain, metricKey) {
            const m = this.metricInfo(domain, metricKey);
            return (m && m.params) || [];
        },
        needsParam(domain, metricKey) {
            const m = this.metricInfo(domain, metricKey);
            return !!(m && m.param_kind && m.param_kind !== 'none');
        },
        addSeries() {
            if (this.series.length < this.maxSeries) {
                this.series.push({ domain: '', metricKey: '', param: '', open: null });
            }
        },
        removeSeries(index) {
            this.series.splice(index, 1);
        },
        onDomainChange(row) {
            row.metricKey = '';
            row.param = '';
        },
        onMetricChange(row) {
            row.param = '';
        },
        // Custom dropdown helpers — a themed replacement for native <select>
        // popups (unstylable in most browsers). Open/closed state lives on the
        // `row` object itself (like onDomainChange/onMetricChange already do)
        // rather than on `this`: inside an x-for, `this` in a called method is
        // the loop's extended scope, not the root component, so `this.x = y`
        // would silently shadow-write a throwaway property instead of
        // reaching the reactive root — the actual UI state never budges.
        toggleRowDropdown(row, field, triggerEl) {
            const opening = row.open !== field;
            row.open = opening ? field : null;
            if (opening && triggerEl) {
                // Flip the panel upward when there isn't room below (same
                // idea as a native <select>'s popup), so it never runs off
                // the bottom of the viewport/page.
                const rect = triggerEl.getBoundingClientRect();
                const panelMaxHeight = 240; // matches --dropdown panel max-height (15rem)
                row.dropUp = window.innerHeight - rect.bottom < panelMaxHeight
                    && rect.top > window.innerHeight - rect.bottom;
            }
        },
        closeRowDropdown(row) {
            row.open = null;
        },
        // A row has 3 sibling dropdowns (domain/metric/param) each with their
        // own @click.outside. A click that opens dropdown A is "outside" B and
        // C too, so their outside-handlers must only clear `row.open` when
        // it's still THEIR field — otherwise B/C stomp the field A just set.
        closeRowDropdownIfOpen(row, field) {
            if (row.open === field) row.open = null;
        },
        domainLabel(row) {
            const d = this.catalog[row.domain];
            return d ? d.label : null;
        },
        metricLabel(row) {
            const m = this.metricInfo(row.domain, row.metricKey);
            if (!m) return null;
            return m.label + (m.unit ? ` (${m.unit})` : '');
        },
        paramLabel(row) {
            const p = this.paramsFor(row.domain, row.metricKey).find(p => p.value === row.param);
            return p ? p.label : null;
        },
    };
}
