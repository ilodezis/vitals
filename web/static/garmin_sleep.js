/**
 * Garmin — one night in detail (/garmin/sleep/<date>): the hypnogram plus the
 * minute-level curves recorded while asleep.
 *
 * window.vitalsGarminSleep = {
 *   stages: [{ start, end, stage }, ...],          // intervals, from garmin_daily
 *   series: { "<series_type>": [{ ts, value }] }   // points, from garmin_intraday
 * }
 * (all timestamps are local wall-clock ISO strings; the server already converted
 * from Garmin's GMT).
 *
 * Both charts share ONE x-axis: minutes elapsed since the night's first sample,
 * with the ticks formatted back into clock time. Two reasons it isn't a time
 * scale or a category scale like the day chart in garmin.js uses:
 *   - Chart.js's time scale needs a date adapter, which isn't vendored.
 *   - a category axis spaces labels evenly, so a 4-minute wake would draw as wide
 *     as a 90-minute deep block — a hypnogram that lies about duration.
 * A linear minute axis is proportional, needs no adapter, and lets the hypnogram
 * and the curve chart line up vertically, which is the whole point of showing
 * them stacked: you read a SpO2 dip against the stage it happened in.
 */
(function () {
    // Bottom-to-top on the y-axis: deep at the floor, awake at the ceiling — the
    // conventional hypnogram shape.
    var STAGE_ORDER = ['deep', 'light', 'rem', 'awake'];

    function stageColors(C) {
        return {
            deep: C.violet,
            light: C.cool,
            rem: C.good,
            // Muted, not warn: waking a couple of times a night is normal, and
            // colouring it as a problem would be the app nagging.
            awake: C.muted,
            unknown: C.muted
        };
    }

    var GROUPS = {
        // Grouped by what shares a scale. Where two series don't (bpm vs ms), the
        // second one gets its own right-hand axis instead of being squashed.
        pulse: [
            { key: 'sleep_hr', label: 'garmin.series.sleep_hr', tone: 'bad', axis: 'y' },
            { key: 'sleep_hrv', label: 'garmin.series.sleep_hrv', tone: 'violet', axis: 'y1' }
        ],
        breathing: [
            { key: 'sleep_spo2', label: 'garmin.series.sleep_spo2', tone: 'cool', axis: 'y' },
            { key: 'sleep_respiration', label: 'garmin.series.sleep_respiration', tone: 'good', axis: 'y1' }
        ],
        recovery: [
            { key: 'sleep_stress', label: 'garmin.series.sleep_stress', tone: 'bad', axis: 'y' },
            { key: 'sleep_bb', label: 'garmin.series.sleep_bb', tone: 'good', axis: 'y' }
        ],
        movement: [
            { key: 'sleep_movement', label: 'garmin.series.sleep_movement', tone: 'violet', axis: 'y' }
        ]
    };

    function ms(iso) {
        var t = new Date(iso).getTime();
        return isNaN(t) ? null : t;
    }

    /** Night start (epoch ms) across stages and every series, or null if empty. */
    function originOf(data) {
        var earliest = null;
        (data.stages || []).forEach(function (s) {
            var t = ms(s.start);
            if (t !== null && (earliest === null || t < earliest)) earliest = t;
        });
        Object.keys(data.series || {}).forEach(function (key) {
            (data.series[key] || []).forEach(function (p) {
                var t = ms(p.ts);
                if (t !== null && (earliest === null || t < earliest)) earliest = t;
            });
        });
        return earliest;
    }

    function minutesFrom(origin, iso) {
        var t = ms(iso);
        return t === null ? null : (t - origin) / 60000;
    }

    /** Minutes-since-origin back into a clock label. Parsing and formatting are
     *  both local, so the browser's own zone cancels out and the label always
     *  reads as the wall-clock time the server stored. */
    function clockLabel(origin, minutes) {
        var d = new Date(origin + minutes * 60000);
        return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
    }

    function baseScales(C, origin, spanMinutes) {
        return {
            x: {
                type: 'linear',
                min: 0,
                max: spanMinutes,
                grid: { color: C.grid, drawTicks: false },
                border: { color: C.axisLine },
                ticks: {
                    color: C.muted,
                    maxRotation: 0,
                    autoSkip: true,
                    maxTicksLimit: 8,
                    font: { family: 'Inter', size: 9 },
                    callback: function (value) { return clockLabel(origin, value); }
                }
            }
        };
    }

    function tooltipStyle(C, origin) {
        return {
            backgroundColor: C.surface, borderColor: C.line2, borderWidth: 1,
            titleColor: C.accent2, titleFont: { family: 'Inter', size: 11 },
            bodyColor: C.fg, bodyFont: { family: 'Inter', size: 10 }, padding: 8,
            callbacks: {
                // The raw x is a minute offset — nobody wants to read "213.5".
                title: function (items) {
                    return items.length ? clockLabel(origin, items[0].parsed.x) : '';
                }
            }
        };
    }

    function drawHypnogram(data, C, origin, spanMinutes) {
        var canvas = document.getElementById('garminHypnogram');
        if (!canvas) return;
        var stages = data.stages || [];
        if (!stages.length) return;

        var colors = stageColors(C);
        // Two points per stage (its start and its end). Consecutive stages share a
        // boundary, so the line drawn through them is horizontal inside a stage
        // and vertical at each transition — a hypnogram, with no `stepped` needed.
        var points = [];
        stages.forEach(function (s) {
            var from = minutesFrom(origin, s.start);
            var to = minutesFrom(origin, s.end);
            var y = STAGE_ORDER.indexOf(s.stage);
            if (from === null || to === null || y === -1) return;
            points.push({ x: from, y: y }, { x: to, y: y });
        });
        if (!points.length) return;

        if (canvas._vitalsChart) canvas._vitalsChart.destroy();
        canvas._vitalsChart = new Chart(canvas, {
            type: 'line',
            data: {
                datasets: [{
                    data: points,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    // Points come in pairs, so an even p0 index starts a stage's own
                    // (horizontal) span and an odd one is the transition between two.
                    segment: {
                        borderColor: function (ctx) {
                            var i = ctx.p0DataIndex;
                            if (i % 2 !== 0) return C.line2;  // the vertical hop
                            var stage = stages[Math.floor(i / 2)];
                            return colors[stage && stage.stage] || C.muted;
                        }
                    }
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: window.devicePixelRatio || 2,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        enabled: true,
                        displayColors: false,
                        backgroundColor: C.surface, borderColor: C.line2, borderWidth: 1,
                        titleColor: C.accent2, titleFont: { family: 'Inter', size: 11 },
                        bodyColor: C.fg, bodyFont: { family: 'Inter', size: 10 }, padding: 8,
                        callbacks: {
                            title: function (items) {
                                return items.length ? clockLabel(origin, items[0].parsed.x) : '';
                            },
                            label: function (item) {
                                var name = STAGE_ORDER[item.parsed.y];
                                return window.t ? window.t('garmin.stage.' + name) : name;
                            }
                        }
                    }
                },
                scales: Object.assign(baseScales(C, origin, spanMinutes), {
                    y: {
                        min: -0.5,
                        max: STAGE_ORDER.length - 0.5,
                        grid: { color: C.grid, drawTicks: false },
                        border: { color: C.axisLine },
                        ticks: {
                            color: C.muted,
                            stepSize: 1,
                            font: { family: 'Inter', size: 9 },
                            callback: function (value) {
                                var name = STAGE_ORDER[value];
                                if (!name) return '';
                                return window.t ? window.t('garmin.stage.' + name) : name;
                            }
                        }
                    }
                })
            }
        });
    }

    function drawCurves(data, C, origin, spanMinutes, group) {
        var canvas = document.getElementById('garminSleepCurves');
        if (!canvas) return;
        var series = data.series || {};
        var tones = { bad: C.bad, good: C.good, cool: C.cool, violet: C.violet, muted: C.muted };

        var members = (GROUPS[group] || []).filter(function (m) {
            return (series[m.key] || []).length;
        });

        var datasets = members.map(function (m) {
            return {
                label: window.t ? window.t(m.label) : m.key,
                data: (series[m.key] || []).map(function (p) {
                    return { x: minutesFrom(origin, p.ts), y: p.value };
                }).filter(function (p) { return p.x !== null; }),
                borderColor: tones[m.tone] || C.muted,
                backgroundColor: 'transparent',
                borderWidth: 1.5,
                pointRadius: 0,
                pointHoverRadius: 3,
                tension: 0.25,
                yAxisID: m.axis,
                // A gap means the watch recorded nothing there; bridging it would
                // invent a reading (same call as the day chart in garmin.js).
                spanGaps: false
            };
        });

        var usesRightAxis = members.some(function (m) { return m.axis === 'y1'; });
        var scales = Object.assign(baseScales(C, origin, spanMinutes), {
            y: {
                grid: { color: C.grid, drawTicks: false },
                border: { color: C.axisLine },
                ticks: { color: C.muted, font: { family: 'Inter', size: 9 } }
            },
            y1: {
                display: usesRightAxis,
                position: 'right',
                grid: { drawOnChartArea: false },
                border: { color: C.axisLine },
                ticks: { color: C.muted, font: { family: 'Inter', size: 9 } }
            }
        });

        if (canvas._vitalsChart) canvas._vitalsChart.destroy();
        canvas._vitalsChart = new Chart(canvas, {
            type: 'line',
            data: { datasets: datasets },
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
                    tooltip: tooltipStyle(C, origin)
                },
                scales: scales
            }
        });
    }

    function initGarminSleepCharts() {
        var data = window.vitalsGarminSleep;
        if (!data) return;
        if (!document.getElementById('garminHypnogram') &&
            !document.getElementById('garminSleepCurves')) return;

        var C = (window.vitalsChartTheme && window.vitalsChartTheme()) || {};
        var origin = originOf(data);
        if (origin === null) return;

        // One shared span so the two charts' x-axes line up pixel for pixel.
        var latest = origin;
        (data.stages || []).forEach(function (s) {
            var t = ms(s.end);
            if (t !== null && t > latest) latest = t;
        });
        Object.keys(data.series || {}).forEach(function (key) {
            (data.series[key] || []).forEach(function (p) {
                var t = ms(p.ts);
                if (t !== null && t > latest) latest = t;
            });
        });
        var spanMinutes = Math.max((latest - origin) / 60000, 1);

        drawHypnogram(data, C, origin, spanMinutes);

        var groupBar = document.getElementById('garminSleepGroups');
        var buttons = groupBar ? groupBar.querySelectorAll('[data-sleep-group]') : [];
        var active = buttons.length ? buttons[0].dataset.sleepGroup : 'pulse';
        drawCurves(data, C, origin, spanMinutes, active);

        // Delegated on the container and guarded per-node: this whole function
        // reruns on every htmx:afterSettle, and a swap that leaves this same
        // #garminSleepGroups element in the DOM (rather than a fresh one) would
        // otherwise stack a second, third, ... click listener on top of the first.
        if (groupBar && !groupBar._vitalsSleepGroupBound) {
            groupBar._vitalsSleepGroupBound = true;
            groupBar.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-sleep-group]');
                if (!btn || !groupBar.contains(btn)) return;
                var current = groupBar.querySelectorAll('[data-sleep-group]');
                Array.prototype.forEach.call(current, function (b) {
                    b.classList.toggle('is-active', b === btn);
                });
                drawCurves(data, C, origin, spanMinutes, btn.dataset.sleepGroup);
            });
        }
    }

    function initGarminSleepChartsSafe() {
        // A throw here must not bubble out of an htmx:afterSettle handler and abort
        // the rest of the swap (same guard as the other chart scripts).
        try { initGarminSleepCharts(); } catch (e) { console.error('garminSleep init failed', e); }
    }

    if (document.readyState !== 'loading') {
        initGarminSleepChartsSafe();
    } else {
        document.addEventListener('DOMContentLoaded', initGarminSleepChartsSafe);
    }

    // Registered once: this file lives in <head>, so it does NOT re-execute on a
    // boosted navigation — these hooks are what draw the charts after an hx-boost
    // swap into the page and after browser back/forward.
    if (!window.__garminSleepBound) {
        window.__garminSleepBound = true;
        document.addEventListener('htmx:afterSettle', initGarminSleepChartsSafe);
        document.addEventListener('htmx:historyRestore', initGarminSleepChartsSafe);
    }
})();
