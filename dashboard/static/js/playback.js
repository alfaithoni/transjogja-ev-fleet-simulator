// dashboard/static/js/playback.js
// T-16: Bus playback engine — interpolasi posisi per waktu dari timeline data

const OP_START_MIN = 0;    // menit ke-0 = 05:30
const OP_END_MIN   = 900;  // menit ke-900 = 20:30

let _busTimelines= [];     // [{bus_id, route_id, timeline: [{t,si,soc,state?}], is_stranded}]
let _simTime     = 0;      // current sim time (menit)
let _speed       = 10;     // sim menit per real detik
let _playing     = false;
let _lastRealMs  = null;
let _rafId       = null;

let _onTick      = null;   // callback(simTime, busStates)
let _onEnd       = null;   // callback()

// ── API ───────────────────────────────────────────────────────────────────

export function loadPlaybackData(data) {
  _busTimelines = data.buses || [];
  _simTime      = 0;
  _playing      = false;
  _lastRealMs   = null;
  stopLoop();
}

export function setCallbacks(onTick, onEnd) {
  _onTick = onTick;
  _onEnd  = onEnd;
}

export function play() {
  if (_playing) return;
  _playing    = true;
  _lastRealMs = performance.now();
  startLoop();
}

export function pause() {
  _playing = false;
  stopLoop();
}

export function reset() {
  _playing = false;
  _simTime = 0;
  stopLoop();
  tick();  // render posisi awal
}

export function seekTo(simMin) {
  _simTime    = Math.max(0, Math.min(OP_END_MIN, simMin));
  _lastRealMs = performance.now();
  tick();
}

export function setSpeed(factor) {
  _speed = factor;
}

export function isPlaying() { return _playing; }
export function getSimTime() { return _simTime; }

// ── Animation Loop ────────────────────────────────────────────────────────

function startLoop() {
  if (_rafId) return;
  _rafId = requestAnimationFrame(frame);
}

function stopLoop() {
  if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
}

function frame(nowMs) {
  if (!_playing) { _rafId = null; return; }

  const elapsed = nowMs - (_lastRealMs || nowMs);
  _lastRealMs = nowMs;

  // Maju waktu simulasi: elapsed ms × speed / 1000 (ms→s) = menit sim
  _simTime += (elapsed / 1000) * _speed;

  if (_simTime >= OP_END_MIN) {
    _simTime = OP_END_MIN;
    _playing = false;
    tick();
    if (_onEnd) _onEnd();
    _rafId = null;
    return;
  }

  tick();
  _rafId = requestAnimationFrame(frame);
}

// ── Tick: hitung posisi semua bus ─────────────────────────────────────────

function tick() {
  const states = _busTimelines.map(bus => getBusStateAt(bus, _simTime));
  if (_onTick) _onTick(_simTime, states);
}

function getBusStateAt(bus, t) {
  const tl = bus.timeline || [];
  if (tl.length === 0) return { bus_id: bus.bus_id, route_id: bus.route_id, state: 'idle', si: null, soc: 100 };

  // Belum mulai
  if (t < tl[0].t) return { bus_id: bus.bus_id, route_id: bus.route_id, state: 'idle', si: null, soc: tl[0].soc };

  // Sudah stranded
  for (const pt of tl) {
    if (pt.state === 'stranded' && t >= pt.t) {
      return { bus_id: bus.bus_id, route_id: bus.route_id, state: 'stranded', si: null, soc: pt.soc };
    }
  }

  // Sedang charging?
  for (const pt of tl) {
    if (pt.state === 'charging' && t >= pt.t && t < pt.return_t) {
      return { bus_id: bus.bus_id, route_id: bus.route_id, state: pt.is_depot ? 'depot_charging' : 'charging', si: -1, soc: pt.soc, spklu: pt.spklu };
    }
  }

  // Cari 2 titik konsekutif yang mengapit t
  let prev = tl[0];
  let next = null;
  for (let i = 1; i < tl.length; i++) {
    const pt = tl[i];
    if (pt.state === 'charging' || pt.state === 'stranded') continue;
    if (pt.t <= t) {
      prev = pt;
    } else {
      next = pt;
      break;
    }
  }

  if (!next) {
    // Setelah rit terakhir: bus idle di halte akhir
    return { bus_id: bus.bus_id, route_id: bus.route_id, state: 'idle', si: prev.si, soc: prev.soc };
  }

  // Interpolasi stop_index (integer, snap ke terdekat)
  const ratio = (t - prev.t) / (next.t - prev.t);
  const si_f  = (prev.si ?? 0) + ratio * ((next.si ?? prev.si ?? 0) - (prev.si ?? 0));
  const si    = Math.round(si_f);
  const soc   = prev.soc + ratio * (next.soc - prev.soc);

  return {
    bus_id: bus.bus_id,
    route_id: bus.route_id,
    state: 'en_route',
    si,
    soc: Math.round(soc * 10) / 10,
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────

export function simTimeToLabel(minInt) {
  const total = 5 * 60 + 30 + Math.round(minInt);  // offset dari 05:30
  const h     = Math.floor(total / 60) % 24;
  const m     = total % 60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
}
