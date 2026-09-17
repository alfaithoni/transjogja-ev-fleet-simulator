// dashboard/static/js/metrics.js
// Visualisasi perbandingan skenario dari comparison_table_stochastic.csv

const FIELD_LABELS = {
  scenario_id:                     'Skenario',
  avg_headway_mean:                'Avg HW (mnt)',
  avg_degraded_routes_per_day_mean:'Degraded Rute/Hari',
  queue_timeouts_mean:             'Queue TO',
  total_requests_mean:             'Requests',
  headway_reliable:                'Reliable?',
  notes:                           'Catatan',
};

let _rows = [];
let _activeScenario = null;
let _onScenarioClick = null;

export function initMetrics(tableEl, onScenarioClick) {
  _onScenarioClick = onScenarioClick;
  renderHeader(tableEl);
}

export function renderMetrics(tableEl, rows, activeScenarioId) {
  _rows = rows;
  _activeScenario = activeScenarioId;

  const tbody = tableEl.querySelector('tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  rows.forEach(row => {
    const tr = document.createElement('tr');
    const degMean = row.avg_degraded_routes_per_day_mean ?? 0;
    const isDegraded = degMean > 0.05;
    const isActive   = row.scenario_id === activeScenarioId ||
                       (activeScenarioId === 's28_live' && row.scenario_id.includes('s28')) ||
                       (activeScenarioId === 's30_live' && row.scenario_id.includes('s30')) ||
                       (activeScenarioId === 's17b_live' && row.scenario_id.includes('s17b')) ||
                       (activeScenarioId === 's31_live' && row.scenario_id.includes('s31')) ||
                       (activeScenarioId === 's32_live' && row.scenario_id.includes('s32'));

    if (isActive)   tr.classList.add('row-active');
    if (isDegraded) tr.classList.add('row-degraded');
    tr.style.cursor = 'pointer';
    tr.title = `Klik untuk memilih skenario ${row.scenario_id}`;

    // 1. scenario_id
    tr.appendChild(makeCell(row.scenario_id, 'cell-id'));

    // 2. avg_headway_mean (± std)
    if (row.avg_headway_mean === null || row.avg_headway_mean === undefined) {
      tr.appendChild(makeCell('N/A', 'cell-null'));
    } else {
      const hw = parseFloat(row.avg_headway_mean);
      const std = row.avg_headway_std ? ` ±${parseFloat(row.avg_headway_std).toFixed(1)}` : '';
      const cls = hw <= 27 ? 'cell-good' : hw <= 34 ? 'cell-warn' : 'cell-bad';
      tr.appendChild(makeCell(`${hw.toFixed(1)}${std}`, cls));
    }

    // 3. avg_degraded_routes_per_day_mean (± std)
    if (row.avg_degraded_routes_per_day_mean === null || row.avg_degraded_routes_per_day_mean === undefined) {
      tr.appendChild(makeCell('─', 'cell-null'));
    } else {
      const deg = parseFloat(row.avg_degraded_routes_per_day_mean);
      const std = row.avg_degraded_routes_per_day_std ? ` ±${parseFloat(row.avg_degraded_routes_per_day_std).toFixed(1)}` : '';
      const cls = deg <= 0.1 ? 'cell-good' : deg <= 3.5 ? 'cell-warn' : 'cell-bad';
      tr.appendChild(makeCell(`${deg.toFixed(2)}${std}`, cls));
    }

    // 4. queue_timeouts_mean
    if (row.queue_timeouts_mean === null || row.queue_timeouts_mean === undefined) {
      tr.appendChild(makeCell('─', 'cell-null'));
    } else {
      const qto = parseFloat(row.queue_timeouts_mean);
      tr.appendChild(makeCell(qto.toFixed(1), qto === 0 ? 'cell-good' : 'cell-bad'));
    }

    // 5. total_requests_mean
    if (row.total_requests_mean === null || row.total_requests_mean === undefined) {
      tr.appendChild(makeCell('─', 'cell-null'));
    } else {
      const req = parseFloat(row.total_requests_mean);
      tr.appendChild(makeCell(req.toFixed(1)));
    }

    // 6. headway_reliable badge
    const rel = row.headway_reliable === true || String(row.headway_reliable).toLowerCase() === 'true';
    const badge = document.createElement('td');
    const b = document.createElement('span');
    b.className = `badge ${rel ? 'badge-green' : 'badge-red'}`;
    b.textContent = rel ? 'TRUE' : 'FALSE';
    badge.appendChild(b);
    tr.appendChild(badge);

    // 7. notes
    const notesCell = makeCell(row.notes || '─');
    notesCell.style.maxWidth = '180px';
    notesCell.style.overflow = 'hidden';
    notesCell.style.textOverflow = 'ellipsis';
    notesCell.style.whiteSpace = 'nowrap';
    notesCell.title = row.notes || '';
    tr.appendChild(notesCell);

    tr.addEventListener('click', () => {
      if (_onScenarioClick) _onScenarioClick(row.scenario_id);
    });

    tbody.appendChild(tr);
  });
}

export function setActiveScenario(tableEl, scenarioId) {
  _activeScenario = scenarioId;
  tableEl.querySelectorAll('tbody tr').forEach((tr, i) => {
    const rowId = _rows[i]?.scenario_id || '';
    const match = rowId === scenarioId ||
                  (scenarioId === 's28_live' && rowId.includes('s28')) ||
                  (scenarioId === 's30_live' && rowId.includes('s30')) ||
                  (scenarioId === 's17b_live' && rowId.includes('s17b')) ||
                  (scenarioId === 's31_live' && rowId.includes('s31')) ||
                  (scenarioId === 's32_live' && rowId.includes('s32'));
    tr.classList.toggle('row-active', match);
  });
}

function renderHeader(tableEl) {
  const thead = tableEl.querySelector('thead') || tableEl.createTHead();
  thead.innerHTML = '';
  const tr = document.createElement('tr');
  Object.values(FIELD_LABELS).forEach(label => {
    const th = document.createElement('th');
    th.textContent = label;
    tr.appendChild(th);
  });
  thead.appendChild(tr);
}

function makeCell(text, cls) {
  const td = document.createElement('td');
  td.textContent = text;
  if (cls) td.className = cls;
  return td;
}

