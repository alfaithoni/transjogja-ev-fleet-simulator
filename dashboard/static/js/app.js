// dashboard/static/js/app.js
// T-17: Main controller — state management, wiring semua komponen

import * as Map      from './map.js?v=3';
import * as Playback from './playback.js?v=3';
import * as SocChart from './soc_chart.js?v=3';
import * as Metrics  from './metrics.js?v=3';

// ── State ─────────────────────────────────────────────────────────────────

const state = {
  routes:          [],
  scenarios:       [],
  comparisonTable: [],
  activeScenario:  's28_live',
  activeRoute:     'ALL',
  playbackData:    null,
  socData:         null,
};

// ── DOM Refs ──────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

const svgEl           = $('schematic-map');
const tooltipEl       = $('map-tooltip');
const scenarioSelect  = $('select-scenario');
const routeSelect     = $('select-route');
const btnPlay         = $('btn-play');
const btnPause        = $('btn-pause');
const btnReset        = $('btn-reset');
const timeSlider      = $('time-slider');
const timeCurrent     = $('time-current');
const speedBtns       = document.querySelectorAll('.speed-btn');
const statusBadges    = $('status-badges');
const metricsTable    = $('metrics-table');
const legendEl        = $('route-legend');

// ── Bootstrap ─────────────────────────────────────────────────────────────

(async function init() {
  // 1. Init map + chart
  Map.initMap(svgEl, tooltipEl, onRouteSelectFromMap);
  SocChart.initSocChart('soc-canvas');
  Metrics.initMetrics(metricsTable, onScenarioClickFromTable);

  Playback.setCallbacks(onPlaybackTick, onPlaybackEnd);

  // 2. Fetch routes (struktur topologi)
  const routes = await fetchJSON('/api/routes');
  state.routes = routes;
  Map.drawMap(routes);
  buildLegend(routes);
  populateRouteSelect(routes);

  // 3. Fetch scenarios
  const scenarios = await fetchJSON('/api/scenarios');
  state.scenarios = scenarios;
  if (scenarios.length > 0 && !scenarios.some(s => s.scenario_id === state.activeScenario)) {
    state.activeScenario = scenarios[0].scenario_id;
  }
  populateScenarioSelect(scenarios);

  // 4. Fetch comparison table
  const table = await fetchJSON('/api/comparison');
  state.comparisonTable = table;
  Metrics.renderMetrics(metricsTable, table, state.activeScenario);

  // 5. Load default skenario
  await loadScenario(state.activeScenario);

  // 6. Wire up UI
  wireUI();

  // 7. Initial time display
  updateTimeDisplay(0);
})();

// ── Data Loading ──────────────────────────────────────────────────────────

async function loadScenario(scenarioId) {
  state.activeScenario = scenarioId;

  // Fetch Playback All
  const pbData = await fetchJSON(`/api/playback_all/${scenarioId}`);
  state.playbackData = pbData;

  // Fetch SoC Chart All
  const socData = await fetchJSON(`/api/soc_all/${scenarioId}`);
  state.socData = socData;

  // Apply filter and render
  applyRouteFilter();

  // Update metrics highlight
  Metrics.setActiveScenario(metricsTable, scenarioId);
}

function applyRouteFilter() {
  const r = state.activeRoute;
  
  // Filter buses
  let buses = state.playbackData?.buses || [];
  if (r !== 'ALL') {
    buses = buses.filter(b => b.route_id === r);
  }

  // Filter soc
  let socBuses = state.socData?.buses || [];
  if (r !== 'ALL') {
    socBuses = socBuses.filter(s => s.bus_id.startsWith(r + '-'));
  }

  const filteredSocData = {
    ...state.socData,
    buses: socBuses
  };

  // Apply to Playback & Map
  Playback.loadPlaybackData({ buses });
  Map.initBusMarkers(buses);
  Map.hideAllBusMarkers();

  // Apply to Chart
  SocChart.renderSocData(filteredSocData);

  // Update status badges
  updateStatusBadges({ buses });

  // Reset playback ke t=0
  Playback.reset();
  updateTimeDisplay(0);
}

// ── UI Wiring ─────────────────────────────────────────────────────────────

function wireUI() {
  // Scenario select
  scenarioSelect.addEventListener('change', async () => {
    await loadScenario(scenarioSelect.value);
    Playback.pause();
    syncPlayPauseBtn();
  });

  // Route select
  routeSelect.addEventListener('change', () => {
    state.activeRoute = routeSelect.value;
    if (state.activeRoute === 'ALL') {
      Map.clearRouteSelection();
    } else {
      Map.selectRoute(state.activeRoute);
    }
    applyRouteFilter();
    Playback.pause();
    syncPlayPauseBtn();
  });

  // Play
  btnPlay.addEventListener('click', () => {
    if (Playback.getSimTime() >= 900) Playback.reset();
    Playback.play();
    syncPlayPauseBtn();
  });

  // Pause
  btnPause.addEventListener('click', () => {
    Playback.pause();
    syncPlayPauseBtn();
  });

  // Reset
  btnReset.addEventListener('click', () => {
    Playback.pause();
    Playback.reset();
    syncPlayPauseBtn();
    Map.hideAllBusMarkers();
    updateTimeDisplay(0);
  });

  // Regenerate (Acak Ulang)
  const btnRegenerate = $('btn-regenerate');
  if (btnRegenerate) {
    btnRegenerate.addEventListener('click', async () => {
      btnRegenerate.disabled = true;
      btnRegenerate.textContent = '⏳ Mengacak...';
      try {
        Playback.pause();
        const res = await fetch(`/api/regenerate/${state.activeScenario}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          // Reload the scenario with new randomized data
          await loadScenario(state.activeScenario);
          Playback.reset();
          updateTimeDisplay(0);
        } else {
          alert('Gagal mengacak: ' + data.error);
        }
      } catch (err) {
        alert('Gagal menghubungi server.');
      }
      btnRegenerate.disabled = false;
      btnRegenerate.textContent = '🎲 Acak Ulang';
    });
  }

  // Speed buttons
  speedBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const s = parseInt(btn.dataset.speed);
      Playback.setSpeed(s);
      speedBtns.forEach(b => b.classList.toggle('active', b === btn));
    });
  });
  // Default: 10x
  document.querySelector('.speed-btn[data-speed="10"]')?.classList.add('active');

  // Time slider (drag to seek)
  let sliderDragging = false;
  timeSlider.addEventListener('mousedown', () => {
    sliderDragging = true;
    Playback.pause();
    syncPlayPauseBtn();
  });
  timeSlider.addEventListener('input', () => {
    if (sliderDragging) {
      const t = parseInt(timeSlider.value);
      Playback.seekTo(t);
      updateTimeDisplay(t);
    }
  });
  window.addEventListener('mouseup', () => { sliderDragging = false; });
}

// ── Playback Callbacks ────────────────────────────────────────────────────

function onPlaybackTick(simTime, busStates) {
  updateTimeDisplay(simTime);

  busStates.forEach(bs => {
    if (bs.state === 'idle') {
      Map.hideBusMarker(bs.bus_id);
    } else {
      Map.updateBusMarker(bs.bus_id, bs.route_id, bs.si, bs.state);
    }
  });
}

function onPlaybackEnd() {
  syncPlayPauseBtn();
}

// ── Scenario click from table ──────────────────────────────────────────────

const SCENARIO_CLIENT_MAP = {
  's17b_probabilistic_4loc_prop': 's17b_live',
  's28_s17b_extra_bus_scaled_infra': 's28_live',
  's30_s17b_extra_bus_buffer_mid': 's30_live',
  's31_s17b_dynamic_v1': 's31_live',
  's32_s17b_dynamic_v2': 's32_live',
  's25_s17b_mix': 's17b_live',
  's26_s17b_mix_extra_bus': 's17b_live',
  's27_s17b_full_depot': 's2_full_depot',
  's29_s17b_extra_bus_pure_proportional': 's30_live',
  's29b_s17b_extra_bus_pure_proportional_fixed': 's30_live',
};

async function onScenarioClickFromTable(scenarioId) {
  const targetId = SCENARIO_CLIENT_MAP[scenarioId] || scenarioId;
  
  // Dropdown options match the comparison table rows (scenarioId)
  const hasOpt = Array.from(scenarioSelect.options).some(opt => opt.value === scenarioId);
  
  try {
    // Test fetch first to see if data exists for this mapped targetId
    const res = await fetch(`/api/playback_all/${targetId}`);
    if (!res.ok) {
      throw new Error(`Data live trace tidak tersedia untuk skenario ${scenarioId}.`);
    }
    
    // Sinkronkan dropdown dengan nama skenario asli yang diklik (bukan alias)
    if (hasOpt) {
      scenarioSelect.value = scenarioId;
    }
    
    await loadScenario(scenarioId); // loadScenario backend handles the alias gracefully!
    Playback.pause();
    syncPlayPauseBtn();
  } catch (err) {
    alert(err.message);
  }
}

function onRouteSelectFromMap(routeId) {
  routeSelect.value = routeId;
  state.activeRoute = routeId;
  applyRouteFilter();
  Playback.pause();
  syncPlayPauseBtn();
}

// ── Helpers ───────────────────────────────────────────────────────────────

function populateScenarioSelect(scenarios) {
  scenarioSelect.innerHTML = '';
  scenarios.forEach(sc => {
    const opt = document.createElement('option');
    opt.value = sc.scenario_id;
    opt.textContent = sc.label;
    if (sc.is_degraded) opt.textContent += ' ⚠';
    scenarioSelect.appendChild(opt);
  });
  scenarioSelect.value = state.activeScenario;
}

function populateRouteSelect(routes) {
  routeSelect.innerHTML = '';
  const optAll = document.createElement('option');
  optAll.value = 'ALL';
  optAll.textContent = 'Semua Rute';
  routeSelect.appendChild(optAll);
  
  routes.forEach(r => {
    const opt = document.createElement('option');
    opt.value = r.route_id;
    opt.textContent = `Koridor ${r.route_id} (${r.bus_count} Bus)`;
    routeSelect.appendChild(opt);
  });
  routeSelect.value = state.activeRoute;
}

function buildLegend(routes) {
  const COLORS = [
    '#FF6B6B','#FF9A3C','#FFD740','#C6F135','#4CAF50',
    '#26C6DA','#42A5F5','#5C6BC0','#AB47BC','#EC407A',
    '#EF5350','#FF7043','#26A69A','#66BB6A','#FFA726',
    '#8D6E63','#78909C','#00BCD4','#FFFFFF','#F06292',
  ];
  legendEl.innerHTML = '';
  routes.forEach((r, i) => {
    const item = document.createElement('div');
    item.className = 'legend-item';
    item.style.cursor = 'pointer';
    item.dataset.routeId = r.route_id;
    item.innerHTML = `<span class="legend-dot" style="background:${COLORS[i % COLORS.length]}"></span>${r.route_id}`;
    item.addEventListener('click', () => {
      onRouteSelectFromMap(r.route_id);
      Map.selectRoute(r.route_id);
    });
    legendEl.appendChild(item);
  });
}

function updateStatusBadges(pbData) {
  if (!statusBadges) return;
  const buses = pbData?.buses || [];
  const nStranded  = buses.filter(b => b.is_stranded).length;

  statusBadges.innerHTML = '';
  if (nStranded > 0) {
    addBadge(statusBadges, `💀 ${nStranded} bus stranded`, 'badge-red');
  } else {
    addBadge(statusBadges, '✓ Operasional normal', 'badge-green');
  }
}

function addBadge(parent, text, cls) {
  const b = document.createElement('span');
  b.className = `badge ${cls}`;
  b.textContent = text;
  parent.appendChild(b);
}

function updateTimeDisplay(simMin) {
  const clamped = Math.max(0, Math.min(900, simMin));
  timeSlider.value    = Math.round(clamped);
  timeCurrent.textContent = Playback.simTimeToLabel(clamped);
  SocChart.updateCursor(clamped);
}

function syncPlayPauseBtn() {
  const playing = Playback.isPlaying();
  btnPlay.disabled  = playing;
  btnPause.disabled = !playing;
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API error: ${url} → ${res.status}`);
  return res.json();
}
