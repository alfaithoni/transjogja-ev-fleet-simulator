// dashboard/static/js/soc_chart.js
// T-18: SoC per-bus chart using Chart.js
// Menampilkan line chart SoC, threshold lines 30%/20%, event markers

import { getRouteColor } from './map.js?v=2';

const BUS_PALETTE = [
  '#00D4FF','#FFD740','#00E676','#F06292','#CE93D8',
  '#80CBC4','#FF8A65','#A5D6A7','#90CAF9','#FFCC80',
];

let _chart = null;
let _currentBusId = null;

const verticalLinePlugin = {
  id: 'verticalLinePlugin',
  afterDraw: chart => {
    if (chart.config.options.plugins.verticalLinePlugin?.xVal !== undefined) {
      const xVal = chart.config.options.plugins.verticalLinePlugin.xVal;
      const xAxis = chart.scales.x;
      const yAxis = chart.scales.y;
      
      const xPixel = xAxis.getPixelForValue(xVal);
      const ctx = chart.ctx;
      
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(xPixel, yAxis.top);
      ctx.lineTo(xPixel, yAxis.bottom);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = '#FFFFFF90';
      ctx.stroke();
      
      // Draw a small triangle at the top to look like a slider thumb
      ctx.fillStyle = '#FFFFFF';
      ctx.beginPath();
      ctx.moveTo(xPixel - 5, yAxis.top - 5);
      ctx.lineTo(xPixel + 5, yAxis.top - 5);
      ctx.lineTo(xPixel, yAxis.top + 2);
      ctx.fill();
      
      ctx.restore();
    }
  }
};

// ── Init ──────────────────────────────────────────────────────────────────

export function initSocChart(canvasId) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  _chart = new Chart(ctx, {
    type: 'line',
    plugins: [verticalLinePlugin],
    data: { datasets: [] },
    options: {
      animation: { duration: 300 },
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false },
      plugins: {
        zoom: {
          zoom: {
            wheel: { enabled: true },
            pinch: { enabled: true },
            mode: 'x',
          },
          pan: {
            enabled: true,
            mode: 'x',
          }
        },
        legend: {
          display: false,
        },
        tooltip: {
          backgroundColor: 'rgba(15,22,40,0.95)',
          borderColor: 'rgba(80,120,200,0.35)',
          borderWidth: 1,
          titleColor: '#e8eeff',
          bodyColor: '#8ba0c8',
          padding: 10,
          callbacks: {
            title: (items) => {
              const t = items[0]?.parsed.x;
              return simTimeToLabel(t) + ` (menit ke-${Math.round(t)})`;
            },
            label: (item) => {
              const r = item.raw;
              if (item.dataset.label.includes('⚡charging')) {
                let lines = [` ${item.dataset.label}: ${item.parsed.y.toFixed(1)}% SoC [${r.spklu || 'Depot'}]`];
                let durText = `   ↳ Durasi: ${r.dur} mnt`;
                if (r.dur < 60) durText += ` (⚠️ Dipangkas V2)`;
                lines.push(durText);
                if (r.wait > 0 || r.proj_q > 0) {
                    lines.push(`   ↳ Antrian Aktual: ${r.wait} mnt (Proj: ${r.proj_q})`);
                }
                return lines;
              }
              return ` ${item.dataset.label}: ${item.parsed.y.toFixed(1)}% SoC`;
            },
          }
        },
      },
      scales: {
        x: {
          type: 'linear',
          min: 0,
          max: 1200,
          ticks: {
            color: '#4a5c84',
            maxTicksLimit: 12,
            font: { size: 9, family: 'Inter' },
            callback: function(val) {
              const h = (Math.floor(val / 60) + 5) % 24;
              const m = Math.floor(val % 60);
              return `${h.toString().padStart(2,'0')}:${m.toString().padStart(2,'0')}`;
            },
          },
          grid: { color: 'rgba(255,255,255,0.04)' },
          border: { color: 'rgba(255,255,255,0.08)' },
        },
        y: {
          min: 0,
          max: 105,
          ticks: {
            color: '#4a5c84',
            font: { size: 9, family: 'Inter' },
            callback: (v) => v + '%',
          },
          grid: { color: 'rgba(255,255,255,0.04)' },
          border: { color: 'rgba(255,255,255,0.08)' },
        }
      },
    }
  });
}

// ── Render SoC Data ───────────────────────────────────────────────────────

export function renderSocData(socData) {
  if (!_chart || !socData) return;

  const datasets = [];

  // Threshold lines
  datasets.push({
    label: '⚡ Charge Threshold (30%)',
    data: [{x:0,y:30},{x:1200,y:30}],
    borderColor: '#FFD740',
    borderWidth: 1.5,
    borderDash: [6,3],
    pointRadius: 0,
    fill: false,
    order: 100,
  });
  datasets.push({
    label: '🚨 Hard Limit (20%)',
    data: [{x:0,y:20},{x:1200,y:20}],
    borderColor: '#FF5252',
    borderWidth: 1.5,
    borderDash: [4,2],
    pointRadius: 0,
    fill: false,
    order: 101,
  });

  // Per-bus series
  socData.buses.forEach((bus, bi) => {
    const routeColor = getRouteColor(bus.route_id);
    const color = bus.is_stranded ? '#FF5252' : routeColor;

    // Main SoC series (Heatmap style for 124+ buses)
    const points = bus.series.map(p => ({ x: p.t, y: p.soc }));
    datasets.push({
      label: bus.bus_id,
      data: points,
      borderColor: bus.is_stranded ? '#FF5252' : routeColor,
      backgroundColor: 'transparent',
      borderWidth: bus.is_stranded ? 2 : 1.5,
      pointRadius: 0,
      pointHoverRadius: 4,
      fill: false,
      tension: 0.1,
      order: bi,
    });

    // Charging markers
    if (bus.charging_markers.length > 0) {
      datasets.push({
        label: `${bus.bus_id} ⚡charging`,
        data: bus.charging_markers.map(m => ({ 
            x: m.t, y: m.soc, spklu: m.spklu, dur: m.dur, wait: m.wait, proj_q: m.proj_q 
        })),
        borderColor: 'transparent',
        backgroundColor: '#FFD740',
        pointRadius: 6,
        pointStyle: 'triangle',
        showLine: false,
        order: bi,
      });
    }

    // Stranded markers
    if (bus.stranded_markers.length > 0) {
      datasets.push({
        label: `${bus.bus_id} 💀stranded`,
        data: bus.stranded_markers.map(m => ({ x: m.t, y: m.soc })),
        borderColor: 'transparent',
        backgroundColor: '#FF5252',
        pointRadius: 8,
        pointStyle: 'crossRot',
        showLine: false,
        order: bi,
      });
    }
  });

  _chart.data.datasets = datasets;
  _chart.update('none');
}

// ── Cursor/Time Sync ──────────────────────────────────────────────────────

export function updateCursor(simMin) {
  if (!_chart) return;
  if (!_chart.config.options.plugins) _chart.config.options.plugins = {};
  if (!_chart.config.options.plugins.verticalLinePlugin) _chart.config.options.plugins.verticalLinePlugin = {};
  
  _chart.config.options.plugins.verticalLinePlugin.xVal = simMin;
  _chart.update('none');
}

// ── Highlight Bus ─────────────────────────────────────────────────────────

export function highlightBus(busId) {
  if (!_chart) return;
  _currentBusId = busId;
  _chart.data.datasets.forEach(ds => {
    const isBus = ds.label === busId || ds.label.startsWith(busId);
    ds.borderWidth = isBus ? 3 : 1;
    ds.borderColor = isBus ? ds.borderColor : (ds.borderColor + '40');
  });
  _chart.update('none');
}

// ── Helper ────────────────────────────────────────────────────────────────

function simTimeToLabel(minInt) {
  const total = 5 * 60 + 30 + Math.round(minInt);
  const h     = Math.floor(total / 60) % 24;
  const m     = total % 60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
}
