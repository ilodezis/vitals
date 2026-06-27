/**
 * Hevy module — working-weight history chart.
 * Renders window.hevyChartData.points (top working weight per session) onto
 * #hevyChart, matching the warm Vitals palette used by the weight chart.
 * The template only renders the canvas when there are 2+ points — a single
 * session is shown as a stat card instead, so this can assume a real series.
 */
function formatDateStr(dateStr) {
    if (!dateStr) return '';
    const match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) {
        return `${match[3]}-${match[2]}-${match[1]}`;
    }
    return dateStr;
}

function initHevyChart() {
    const canvas = document.getElementById('hevyChart');
    if (!canvas) return;

    const data = (window.hevyChartData && window.hevyChartData.points) || [];
    if (data.length < 2) return;

    const labels = data.map(p => formatDateStr(p.date));
    const weights = data.map(p => p.weight_kg);
    const reps = data.map(p => p.top_reps);

    if (window.hevyChartInstance) {
        window.hevyChartInstance.destroy();
    }
    window.hevyChartInstance = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: window.t('chart.working_weight'),
                data: weights,
                borderColor: '#F5A623',
                backgroundColor: 'rgba(245, 166, 35, 0.08)',
                borderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6,
                pointBackgroundColor: '#FBB54C',
                tension: 0.15,
                fill: true,
                spanGaps: true
            }]
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
                    padding: 8,
                    callbacks: {
                        afterBody: (items) => {
                            const i = items[0].dataIndex;
                            return reps[i] != null ? window.t('chart.top_reps').replace('{reps}', reps[i]) : '';
                        }
                    }
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
    initHevyChart();
} else {
    document.addEventListener('DOMContentLoaded', initHevyChart);
}
document.addEventListener('htmx:afterSettle', initHevyChart);
