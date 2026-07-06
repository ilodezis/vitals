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
const VITALS_CHART_PALETTE = [
    '#3987e5', '#199e70', '#c98500', '#008300',
    '#9085e9', '#e66767', '#d55181', '#d95926',
];

function vitalsFormatDateStr(dateStr) {
    if (!dateStr) return '';
    const match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) return `${match[3]}-${match[2]}-${match[1]}`;
    return dateStr;
}

function renderCustomChart(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

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
        const color = VITALS_CHART_PALETTE[(s.color_slot || 0) % VITALS_CHART_PALETTE.length];
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

    const axisTick = { color: '#A39AB0', font: { family: 'Inter', size: 9 } };
    const scales = {
        x: {
            grid: { color: 'rgba(163, 154, 176, 0.08)', drawTicks: false },
            border: { color: 'rgba(163, 154, 176, 0.16)' },
            ticks: { color: '#A39AB0', maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { family: 'Inter', size: 9 } },
        },
    };
    if (normalize) {
        scales.y_norm = {
            position: 'left',
            grid: { color: 'rgba(163, 154, 176, 0.08)', drawTicks: false },
            border: { color: 'rgba(163, 154, 176, 0.16)' },
            ticks: axisTick,
            title: { display: true, text: (window.t ? window.t('chart.normalized_axis') : '= 100 at start'), color: '#A39AB0', font: { family: 'Inter', size: 9 } },
        };
    } else {
        let idx = 0;
        unitAxis.forEach((axisId, unit) => {
            scales[axisId] = {
                position: idx % 2 === 0 ? 'left' : 'right',
                display: idx < 2,
                grid: { display: idx === 0, color: 'rgba(163, 154, 176, 0.08)', drawTicks: false },
                border: { color: 'rgba(163, 154, 176, 0.16)' },
                ticks: axisTick,
                title: { display: idx < 2, text: unit, color: '#A39AB0', font: { family: 'Inter', size: 9 } },
            };
            idx += 1;
        });
    }

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
                legend: { position: 'bottom', labels: { color: '#A39AB0', font: { family: 'Inter', size: 10 }, boxWidth: 12 } },
                tooltip: {
                    backgroundColor: '#2C2933', borderColor: '#4B4555', borderWidth: 1,
                    titleColor: '#FBB54C', titleFont: { family: 'Inter', size: 11 },
                    bodyColor: '#F3F0F6', bodyFont: { family: 'Inter', size: 10 }, padding: 8,
                },
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
if (document.readyState !== 'loading') {
    initCustomCharts();
} else {
    document.addEventListener('DOMContentLoaded', initCustomCharts);
}
document.addEventListener('htmx:afterSettle', initCustomCharts);

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
        toggleRowDropdown(row, field) {
            row.open = row.open === field ? null : field;
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
