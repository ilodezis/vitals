/**
 * Labs module — per-marker history chart.
 * Plots window.labChartData.points (value over time) on #labChart, with the
 * reference low/high drawn as faint dashed bands so out-of-range points stand out.
 */
function initLabChart() {
    const canvas = document.getElementById('labChart');
    if (!canvas) return;

    const data = (window.labChartData && window.labChartData.points) || [];
    const labels = data.map(p => p.date);
    const values = data.map(p => p.value);
    const refLow = data.map(p => (p.ref_low != null ? p.ref_low : null));
    const refHigh = data.map(p => (p.ref_high != null ? p.ref_high : null));

    // Colour each point red when out of its range.
    const pointColors = data.map(p => {
        const lo = p.ref_low, hi = p.ref_high;
        const bad = (lo != null && p.value < lo) || (hi != null && p.value > hi);
        return bad ? '#E5484D' : '#FBB54C';
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
                    borderColor: '#F5A623',
                    backgroundColor: 'rgba(245, 166, 35, 0.08)',
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
                    labels: { color: '#A39AB0', font: { family: 'Inter', size: 10 }, boxWidth: 12 }
                },
                tooltip: {
                    backgroundColor: '#2C2933',
                    borderColor: '#4B4555',
                    borderWidth: 1,
                    titleColor: '#FBB54C',
                    titleFont: { family: 'Inter', size: 11 },
                    bodyColor: '#F3F0F6',
                    bodyFont: { family: 'Inter', size: 10 },
                    padding: 8
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(163, 154, 176, 0.08)', drawTicks: false },
                    border: { color: 'rgba(163, 154, 176, 0.16)' },
                    ticks: { color: '#A39AB0', maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { family: 'Inter', size: 9 } }
                },
                y: {
                    grid: { color: 'rgba(163, 154, 176, 0.08)', drawTicks: false },
                    border: { color: 'rgba(163, 154, 176, 0.16)' },
                    ticks: { color: '#A39AB0', font: { family: 'Inter', size: 9 } }
                }
            }
        }
    });
}
if (document.readyState !== 'loading') {
    initLabChart();
} else {
    document.addEventListener('DOMContentLoaded', initLabChart);
}
document.addEventListener('htmx:afterSettle', initLabChart);
