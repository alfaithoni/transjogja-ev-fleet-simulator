// dashboard/static/js/map.js
// T-15: Schematic map renderer — auto-layout berbasis urutan halte routes.json
// Gaya transit-map: lane-based, proportional stop spacing, 20 warna unik per rute.

const ROUTE_COLORS = [
  '#FF6B6B','#FF9A3C','#FFD740','#C6F135','#4CAF50',
  '#26C6DA','#42A5F5','#5C6BC0','#AB47BC','#EC407A',
  '#EF5350','#FF7043','#26A69A','#66BB6A','#FFA726',
  '#8D6E63','#78909C','#00BCD4','#FFFFFF','#F06292',
];

const LANE_H      = 50;    // px per rute
const MARGIN_TOP  = 24;
const MARGIN_LEFT = 110;   // ruang untuk label rute
const MARGIN_RIGHT = 20;
const STOP_R      = 3.5;   // radius halte normal
const TERMINAL_R  = 6;     // radius terminal besar

let routeLayouts = {};     // { route_id: { y, stopPositions, color, stops } }
let svgEl        = null;
let selectedRoute= null;
let tooltip      = null;
let onRouteSelect= null;   // callback(route_id)

// ── Init ─────────────────────────────────────────────────────────────────

export function initMap(svgElement, tooltipEl, routeSelectCallback) {
  svgEl = svgElement;
  tooltip = tooltipEl;
  onRouteSelect = routeSelectCallback;
}

export function drawMap(routes) {
  if (!svgEl || !routes || routes.length === 0) return;

  const mapWidth  = Math.max(svgEl.parentElement.clientWidth, 1200);
  const usableW   = mapWidth - MARGIN_LEFT - MARGIN_RIGHT;
  const svgHeight = routes.length * LANE_H + MARGIN_TOP + 16;

  svgEl.setAttribute('width',  '100%');
  svgEl.setAttribute('height', '100%');
  svgEl.setAttribute('viewBox', `0 0 ${mapWidth} ${svgHeight}`);
  svgEl.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svgEl.innerHTML = '';

  // Defs: glow filter
  const defs = createSVGEl('defs');
  defs.innerHTML = `
    <filter id="glow">
      <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
      <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>`;
  svgEl.appendChild(defs);

  routes.forEach((route, idx) => {
    const color = ROUTE_COLORS[idx % ROUTE_COLORS.length];
    const stops = route.stops || [];
    const y     = MARGIN_TOP + idx * LANE_H + LANE_H / 2;

    // Hitung posisi x proportional berdasarkan kumulatif jarak
    let cumDist = 0;
    const cumDists = [0];
    for (let i = 1; i < stops.length; i++) {
      cumDist += stops[i].dist_from_prev_m || 0;
      cumDists.push(cumDist);
    }
    const totalDist = cumDist || 1;
    const stopPositions = cumDists.map(d => MARGIN_LEFT + (d / totalDist) * usableW);

    routeLayouts[route.route_id] = { y, stopPositions, color, stops, idx };

    // Grup per rute
    const g = createSVGEl('g');
    g.setAttribute('class', 'route-lane');
    g.dataset.routeId = route.route_id;

    // Background lane (subtle)
    const laneRect = createSVGEl('rect');
    laneRect.setAttribute('x', 0);
    laneRect.setAttribute('y', idx * LANE_H + MARGIN_TOP - 2);
    laneRect.setAttribute('width', mapWidth);
    laneRect.setAttribute('height', LANE_H - 6);
    laneRect.setAttribute('fill', idx % 2 === 0 ? 'rgba(255,255,255,0.01)' : 'transparent');
    laneRect.setAttribute('rx', 4);
    g.appendChild(laneRect);

    // Label rute (kiri)
    const label = createSVGEl('text');
    label.setAttribute('x', MARGIN_LEFT - 8);
    label.setAttribute('y', y + 4);
    label.setAttribute('text-anchor', 'end');
    label.setAttribute('font-size', '11');
    label.setAttribute('font-weight', '600');
    label.setAttribute('font-family', 'Inter, system-ui, sans-serif');
    label.setAttribute('fill', color);
    label.setAttribute('class', 'route-label');
    label.textContent = route.route_id;
    g.appendChild(label);

    // Garis rute
    if (stopPositions.length >= 2) {
      const line = createSVGEl('line');
      line.setAttribute('x1', stopPositions[0]);
      line.setAttribute('y1', y);
      line.setAttribute('x2', stopPositions[stopPositions.length - 1]);
      line.setAttribute('y2', y);
      line.setAttribute('stroke', color);
      line.setAttribute('stroke-width', '2.5');
      line.setAttribute('opacity', '0.7');
      line.setAttribute('class', 'route-line');
      g.appendChild(line);
    }

    // Stop circles
    stops.forEach((stop, si) => {
      const x = stopPositions[si];
      const isTerminal = stop.name && (
        stop.name.startsWith('Terminal') ||
        stop.name.startsWith('Park and Ride') ||
        stop.name === 'Halte Ngabean'
      );
      const r = isTerminal ? TERMINAL_R : STOP_R;

      const circle = createSVGEl('circle');
      circle.setAttribute('cx', x);
      circle.setAttribute('cy', y);
      circle.setAttribute('r', r);
      circle.setAttribute('fill', isTerminal ? color : '#1a2840');
      circle.setAttribute('stroke', color);
      circle.setAttribute('stroke-width', isTerminal ? '2' : '1.5');
      circle.setAttribute('class', 'stop-circle');
      circle.dataset.routeId  = route.route_id;
      circle.dataset.stopIdx  = si;
      circle.dataset.stopName = stop.name;

      // Hover: tooltip
      circle.addEventListener('mouseenter', (e) => showTooltip(e, route, si, stop));
      circle.addEventListener('mouseleave', hideTooltip);
      g.appendChild(circle);

      // Label terminal besar
      if (isTerminal) {
        const tl = createSVGEl('text');
        tl.setAttribute('x', x);
        tl.setAttribute('y', y - TERMINAL_R - 3);
        tl.setAttribute('text-anchor', 'middle');
        tl.setAttribute('font-size', '7.5');
        tl.setAttribute('font-family', 'Inter, system-ui, sans-serif');
        tl.setAttribute('fill', color);
        tl.setAttribute('opacity', '0.75');
        // Hanya tampilkan nama pendek
        const shortName = stop.name.replace('Terminal ', 'T.').replace('Park and Ride ', 'P&R ');
        tl.textContent = shortName.length > 14 ? shortName.slice(0, 13) + '…' : shortName;
        g.appendChild(tl);
      }
    });

    // Click handler untuk select rute
    g.addEventListener('click', () => selectRoute(route.route_id));
    svgEl.appendChild(g);
  });

  // Layer bus markers (di atas semua elemen rute)
  const busLayer = createSVGEl('g');
  busLayer.setAttribute('id', 'bus-layer');
  svgEl.appendChild(busLayer);
}

// ── Route Selection ────────────────────────────────────────────────────────

export function selectRoute(routeId) {
  selectedRoute = routeId;
  // Highlight rute terpilih, dim yang lain
  document.querySelectorAll('.route-lane').forEach(g => {
    const rid = g.dataset.routeId;
    const isSelected = rid === routeId;
    g.querySelectorAll('.route-line').forEach(l => {
      l.setAttribute('opacity', isSelected ? '1' : '0.15');
      l.setAttribute('stroke-width', isSelected ? '3.5' : '2');
    });
    g.querySelectorAll('.stop-circle').forEach(c => {
      c.setAttribute('opacity', isSelected ? '1' : '0.15');
    });
    g.querySelectorAll('.route-label').forEach(t => {
      t.setAttribute('opacity', isSelected ? '1' : '0.3');
      t.setAttribute('font-size', isSelected ? '12' : '11');
    });
  });
  // Update legend
  document.querySelectorAll('.legend-item').forEach(el => {
    el.classList.toggle('active', el.dataset.routeId === routeId);
  });
  if (onRouteSelect) onRouteSelect(routeId);
}

export function clearRouteSelection() {
  selectedRoute = null;
  document.querySelectorAll('.route-lane').forEach(g => {
    g.querySelectorAll('.route-line').forEach(l => {
      l.setAttribute('opacity', '0.7');
      l.setAttribute('stroke-width', '2.5');
    });
    g.querySelectorAll('.stop-circle').forEach(c => c.setAttribute('opacity', '1'));
    g.querySelectorAll('.route-label').forEach(t => {
      t.setAttribute('opacity', '1');
      t.setAttribute('font-size', '11');
    });
  });
  document.querySelectorAll('.legend-item').forEach(el => el.classList.remove('active'));
}

// ── Bus Markers ────────────────────────────────────────────────────────────

const busMarkers = {};  // { busId: SVGElement }

export function initBusMarkers(buses) {
  const layer = document.getElementById('bus-layer');
  if (!layer) return;
  // Hapus marker lama
  layer.innerHTML = '';
  Object.keys(busMarkers).forEach(k => delete busMarkers[k]);

  buses.forEach((bus, bi) => {
    const g = createSVGEl('g');
    g.setAttribute('id', `bus-${bus.bus_id}`);
    g.setAttribute('class', 'bus-marker');
    g.style.display = 'none';
    g.dataset.busId = bus.bus_id;

    const routeColor = getRouteColor(bus.route_id);
    const color = bus.is_stranded ? '#FF5252' : routeColor;
    
    // Circle
    const c = createSVGEl('circle');
    c.setAttribute('r', '7');
    c.setAttribute('fill', color);
    c.setAttribute('stroke', '#0f1622');
    c.setAttribute('stroke-width', '2');
    c.setAttribute('filter', 'url(#glow)');
    // Label
    const t = createSVGEl('text');
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('dy', '3');
    t.setAttribute('font-size', '7');
    t.setAttribute('font-weight', '700');
    t.setAttribute('fill', '#000');
    t.textContent = bus.bus_id.split('-').slice(-1)[0].replace('x','');

    g.appendChild(c);
    g.appendChild(t);
    layer.appendChild(g);
    busMarkers[bus.bus_id] = { el: g, color };
  });
}

export function updateBusMarker(busId, routeId, stopIndex, state) {
  const marker = busMarkers[busId];
  if (!marker) return;
  const layout = routeLayouts[routeId];
  if (!layout) return;

  const { el } = marker;

  if (state === 'stranded') {
    // Tampilkan X merah statis
    el.style.display = '';
    el.querySelector('circle').setAttribute('fill', '#FF5252');
    el.querySelector('text').textContent = '✕';
    return;
  }

  if (state === 'depot_charging') {
    // Off-route (depot) - tampilkan di kiri luar peta
    el.style.display = '';
    el.setAttribute('transform', `translate(${MARGIN_LEFT - 80}, ${layout.y})`);
    el.querySelector('circle').setAttribute('fill', '#4CAF50'); // Green
    el.querySelector('text').textContent = '\uD83C\uDFE0'; // 🏠 House emoji
    return;
  }

  if (stopIndex === -1 || stopIndex === null) {
    // Off-route (charging) - tampilkan di kanan luar peta
    el.style.display = '';
    el.setAttribute('transform', `translate(${MARGIN_LEFT - 60}, ${layout.y})`);
    el.querySelector('circle').setAttribute('fill', '#FFD740');
    el.querySelector('text').textContent = '⚡';
    return;
  }

  if (stopIndex >= 0 && stopIndex < layout.stopPositions.length) {
    const x = layout.stopPositions[stopIndex];
    const y = layout.y;
    el.setAttribute('transform', `translate(${x}, ${y})`);
    el.style.display = '';
    el.querySelector('circle').setAttribute('fill', marker.color);
    el.querySelector('text').textContent =
      busId.split('-').slice(-1)[0].replace('x','');
  }
}

export function hideBusMarker(busId) {
  const marker = busMarkers[busId];
  if (marker) marker.el.style.display = 'none';
}

export function hideAllBusMarkers() {
  Object.values(busMarkers).forEach(m => m.el.style.display = 'none');
}

export function getRouteLayouts() { return routeLayouts; }
export function getSelectedRoute() { return selectedRoute; }
export function getRouteColor(routeId) { 
  return routeLayouts[routeId] ? routeLayouts[routeId].color : '#3d9eff'; 
}

// ── Tooltip ────────────────────────────────────────────────────────────────

function showTooltip(e, route, si, stop) {
  if (!tooltip) return;
  const km = stop.dist_from_prev_m ? (stop.dist_from_prev_m / 1000).toFixed(2) : '0';
  tooltip.innerHTML = `
    <div class="tooltip-title">${stop.name}</div>
    <div class="tooltip-body">
      Rute ${route.route_id} · Halte ke-${si + 1}<br>
      Jarak dari sebelumnya: ${km} km
    </div>`;
  tooltip.classList.add('visible');
  positionTooltip(e);
}

function hideTooltip() {
  if (tooltip) tooltip.classList.remove('visible');
}

svgEl?.addEventListener('mousemove', positionTooltip);

function positionTooltip(e) {
  if (!tooltip || !tooltip.classList.contains('visible')) return;
  const x = e.clientX + 14;
  const y = e.clientY - 6;
  const tw = tooltip.offsetWidth;
  const th = tooltip.offsetHeight;
  tooltip.style.left = (x + tw > window.innerWidth ? e.clientX - tw - 14 : x) + 'px';
  tooltip.style.top  = (y + th > window.innerHeight ? e.clientY - th : y) + 'px';
}

// ── Util ───────────────────────────────────────────────────────────────────

function createSVGEl(tag) {
  return document.createElementNS('http://www.w3.org/2000/svg', tag);
}
