# -*- coding: utf-8 -*-
"""
dashboard/api/data_loader.py
-----------------------------
Lazy-load & in-memory cache untuk file data simulasi.
Semua akses data JSON/CSV melalui fungsi di sini.
"""

import csv
import json
from pathlib import Path
from functools import lru_cache

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = DATA_DIR / "results"


# ---------------------------------------------------------------------------
# Routes & Spec
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_routes() -> list:
    """Kembalikan semua rute dari routes.json (tanpa soc_trace)."""
    with open(DATA_DIR / "routes.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_routes_meta() -> list:
    """Kembalikan metadata ringan setiap rute (tanpa stop detail yang panjang)."""
    routes = get_routes()
    meta = []
    for r in routes:
        stops = r.get("stops", [])
        total_km = sum(s.get("dist_from_prev_m", 0) for s in stops) / 1000.0
        meta.append({
            "route_id": r["route_id"],
            "bus_count": r.get("bus_count", 1),
            "headway_dishub_min": r.get("headway_dishub_min"),
            "n_stops": len(stops),
            "total_km": round(total_km, 2),
        })
    return meta


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

SCENARIO_ALIASES = {
    "s17b_probabilistic_4loc_prop": "s17b_live",
    "s28_s17b_extra_bus_scaled_infra": "s28_live",
    "s30_s17b_extra_bus_buffer_mid": "s30_live",
    "s31_s17b_dynamic_v1": "s31_live",
    "s32_s17b_dynamic_v2": "s32_live",
    "s25_s17b_mix": "s17b_live",
    "s26_s17b_mix_extra_bus": "s17b_live",
    "s27_s17b_full_depot": "s2_full_depot",
    "s29_s17b_extra_bus_pure_proportional": "s30_live",
    "s29b_s17b_extra_bus_pure_proportional_fixed": "s30_live",
    "s33_ultimate": "s33_live",
    "s34_staggered": "s34_live",
    "s35_sweet_spot": "s35_live",
}

@lru_cache(maxsize=1)
def get_scenarios() -> list:
    """Kembalikan list skenario yang tersedia untuk visualisasi live."""
    ORDER = [
        "s35_live",
        "s33_live",
        "s34_live",
        "s28_live",
        "s30_live",
        "s17b_live",
        "s31_live",
        "s32_live",
        "s1_baseline_opportunity",
        "s2_full_depot",
        "s3_mix_charging",
        "s3b_mix_4spklu_nobus",
        "s4_mix_extra_bus",
        "s5_mix_all_spklu_extra",
    ]
    
    LABEL_MAP = {
        "s35_live": "S35 (Sweet Spot: 23 Gun + Dynamic) ★",
        "s33_live": "S33 (Ultimate: 26 Gun + Dynamic)",
        "s34_live": "S34 (Staggered Dispatch: 20 Gun)",
        "s28_live": "S28 (Rekomendasi: Infra +12%)",
        "s30_live": "S30 (Buffer Mid: Infra +7%)",
        "s17b_live": "S17b (Baseline Stokastik)",
        "s31_live": "S31 (Algoritma V1: Time-Aware)",
        "s32_live": "S32 (Algoritma V2: Queue-Aware)",
        "s1_baseline_opportunity": "S1 (1 SPKLU, No Extra - Legacy)",
        "s2_full_depot": "S2 (Full Depot - Legacy)",
        "s3_mix_charging": "S3 (Mix, 1 SPKLU - Legacy)",
        "s3b_mix_4spklu_nobus": "S3b (Mix, 4 SPKLU - Legacy)",
        "s4_mix_extra_bus": "S4 (Mix, 1 SPKLU, +1 Bus - Legacy)",
        "s5_mix_all_spklu_extra": "S5 (Mix, 4 SPKLU, +1 Bus - Legacy)",
    }
    
    scenarios = []
    for sid in ORDER:
        path = RESULTS_DIR / f"simulation_result_{sid}.json"
        if not path.exists():
            continue
        try:
            data = _read_top_level(path)
        except Exception:
            continue
            
        routes_deg = data.get("summary", {}).get("routes_degraded_count", 0)
        scenarios.append({
            "scenario_id": sid,
            "label": LABEL_MAP.get(sid, sid),
            "is_degraded": routes_deg > 0,
            "charging_mechanism": data.get("charging_mechanism", ""),
            "extra_bus_per_route": data.get("extra_bus_per_route", 0),
            "routes_degraded": routes_deg,
            "total_breach": data.get("summary", {}).get("total_breach_hard_limit", 0),
        })
    return scenarios


def _read_top_level(path: Path) -> dict:
    """Baca hanya field top-level JSON tanpa nested 'routes' array (cepat)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if k != "routes"}


# ---------------------------------------------------------------------------
# Simulation Results (cached per scenario_id)
# ---------------------------------------------------------------------------

_result_cache: dict = {}


def get_simulation_result(scenario_id: str) -> dict:
    """Lazy-load & cache simulation result JSON dengan alias mapping."""
    target_id = SCENARIO_ALIASES.get(scenario_id, scenario_id)
    if target_id not in _result_cache:
        path = RESULTS_DIR / f"simulation_result_{target_id}.json"
        if not path.exists():
            # Coba cari nama aslinya
            path_orig = RESULTS_DIR / f"simulation_result_{scenario_id}.json"
            if path_orig.exists():
                path = path_orig
            else:
                raise FileNotFoundError(f"Simulation result tidak ditemukan: {path}")
        with open(path, encoding="utf-8") as f:
            _result_cache[target_id] = json.load(f)
    return _result_cache[target_id]


def get_route_result(scenario_id: str, route_id: str) -> dict | None:
    """Kembalikan result 1 rute dari skenario tertentu."""
    data = get_simulation_result(scenario_id)
    for r in data.get("routes", []):
        if r["route_id"] == route_id:
            return r
    return None


# ---------------------------------------------------------------------------
# Comparison Table
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_comparison_table() -> list:
    """Kembalikan comparison_table_stochastic.csv sebagai list of dicts."""
    path = DATA_DIR / "comparison_table_stochastic.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            # Parse float fields
            for field in [
                "avg_headway_mean", "avg_headway_std",
                "avg_degraded_routes_per_day_mean", "avg_degraded_routes_per_day_std",
                "queue_timeouts_mean", "queue_timeouts_std",
                "total_requests_mean", "total_requests_std"
            ]:
                val = row.get(field, "")
                if val not in ("", "null", None):
                    try:
                        row[field] = float(val)
                    except ValueError:
                        pass
                else:
                    row[field] = None
            
            row["headway_reliable"] = str(row.get("headway_reliable", "true")).lower() == "true"
            rows.append(row)
        return rows


# ---------------------------------------------------------------------------
# Playback Data Extraction
# ---------------------------------------------------------------------------

def get_playback_data(scenario_id: str, route_id: str) -> dict | None:
    """
    Kembalikan data playback compact untuk 1 rute/skenario.
    Format ringan: per bus, list {t, si, soc, state?}
    """
    route_result = get_route_result(scenario_id, route_id)
    if not route_result:
        return None

    buses_out = []
    for bus in route_result.get("buses", []):
        timeline = []
        for trip in bus.get("trips", []):
            for entry in trip.get("soc_trace", []):
                point = {
                    "t": entry["time_min"],
                    "si": entry["stop_index"],
                    "soc": round(entry["soc_pct"], 1),
                }
                timeline.append(point)

            # Charging event: bus keluar jalur
            if trip.get("charging_event"):
                ev = trip["charging_event"]
                timeline.append({
                    "t": ev["triggered_at_time_min"],
                    "si": -1,          # off-route
                    "soc": round(ev["triggered_at_soc_pct"], 1),
                    "state": "charging",
                    "spklu": ev.get("spklu_id", ""),
                    "is_depot": ev.get("is_depot", False),
                    "return_t": ev["triggered_at_time_min"] + ev["total_downtime_min"],
                })

            # Stranded event
            if trip.get("stranded_event"):
                ev = trip["stranded_event"]
                timeline.append({
                    "t": ev["at_time_min"],
                    "si": None,
                    "soc": round(ev["at_soc_pct"], 1),
                    "state": "stranded",
                })

        buses_out.append({
            "bus_id": bus["bus_id"],
            "timeline": sorted(timeline, key=lambda x: x["t"]),
            "is_stranded": bus.get("is_stranded", False),
            "stranded_at": bus.get("stranded_at_time_min"),
            "total_trips": bus.get("total_trips", 0),
            "total_charging_sessions": bus.get("total_charging_sessions", 0),
        })

    return {
        "route_id": route_id,
        "scenario_id": scenario_id,
        "target_headway_min": route_result.get("target_headway_min"),
        "stagger_min_used": route_result.get("stagger_min_used", 0),
        "route_degraded": route_result.get("route_degraded", False),
        "buses": buses_out,
    }


# ---------------------------------------------------------------------------
# SoC Trace (for chart)
# ---------------------------------------------------------------------------

def get_soc_data(scenario_id: str, route_id: str) -> dict | None:
    """Kembalikan soc_trace per bus untuk grafik SoC."""
    route_result = get_route_result(scenario_id, route_id)
    if not route_result:
        return None

    buses_out = []
    for bus in route_result.get("buses", []):
        # Flatten semua trip soc_trace menjadi 1 series
        series = []
        charging_markers = []
        stranded_markers = []

        for trip in bus.get("trips", []):
            for entry in trip.get("soc_trace", []):
                series.append({
                    "t": entry["time_min"],
                    "soc": round(entry["soc_pct"], 1),
                })
            if trip.get("charging_event"):
                ev = trip["charging_event"]
                charging_markers.append({
                    "t": ev["triggered_at_time_min"],
                    "soc": round(ev["triggered_at_soc_pct"], 1),
                    "spklu": ev.get("spklu_id", ""),
                    "dur": ev.get("charging_duration_min", 60),
                    "wait": ev.get("queue_wait_min", 0),
                    "proj_q": ev.get("projected_queue_wait", 0),
                })
            if trip.get("stranded_event"):
                ev = trip["stranded_event"]
                stranded_markers.append({
                    "t": ev["at_time_min"],
                    "soc": round(ev["at_soc_pct"], 1),
                })

        buses_out.append({
            "bus_id": bus["bus_id"],
            "series": series,
            "charging_markers": charging_markers,
            "stranded_markers": stranded_markers,
            "is_stranded": bus.get("is_stranded", False),
        })

    return {
        "route_id": route_id,
        "scenario_id": scenario_id,
        "buses": buses_out,
        "threshold_charge_pct": 30.0,
        "threshold_hard_pct": 20.0,
    }


def get_playback_data_all(scenario_id: str) -> dict:
    """Mengembalikan data playback untuk seluruh bus di semua rute."""
    try:
        data = get_simulation_result(scenario_id)
    except FileNotFoundError:
        return {"buses": []}
    
    buses_out = []
    for route in data.get("routes", []):
        route_id = route["route_id"]
        for bus in route.get("buses", []):
            timeline = []
            for trip in bus.get("trips", []):
                for entry in trip.get("soc_trace", []):
                    timeline.append({
                        "t": entry["time_min"],
                        "si": entry["stop_index"],
                        "soc": round(entry["soc_pct"], 1),
                    })

                if trip.get("charging_event"):
                    ev = trip["charging_event"]
                    timeline.append({
                        "t": ev["triggered_at_time_min"],
                        "si": -1,          
                        "soc": round(ev["triggered_at_soc_pct"], 1),
                        "state": "charging",
                        "spklu": ev.get("spklu_id", ""),
                        "is_depot": ev.get("is_depot", False),
                        "return_t": ev["triggered_at_time_min"] + ev["total_downtime_min"],
                    })

                if trip.get("stranded_event"):
                    ev = trip["stranded_event"]
                    timeline.append({
                        "t": ev["at_time_min"],
                        "si": None,
                        "soc": round(ev["at_soc_pct"], 1),
                        "state": "stranded",
                    })

            buses_out.append({
                "route_id": route_id,
                "bus_id": bus["bus_id"],
                "timeline": sorted(timeline, key=lambda x: x["t"]),
                "is_stranded": bus.get("is_stranded", False),
            })

    return {
        "scenario_id": scenario_id,
        "buses": buses_out,
    }


def get_soc_data_all(scenario_id: str) -> dict:
    """Mengembalikan trace SoC untuk seluruh bus di semua rute."""
    try:
        data = get_simulation_result(scenario_id)
    except FileNotFoundError:
        return {"buses": []}
        
    buses_out = []
    for route in data.get("routes", []):
        for bus in route.get("buses", []):
            series = []
            charging_markers = []
            stranded_markers = []

            for trip in bus.get("trips", []):
                for entry in trip.get("soc_trace", []):
                    series.append({
                        "t": entry["time_min"],
                        "soc": round(entry["soc_pct"], 1),
                    })
                if trip.get("charging_event"):
                    ev = trip["charging_event"]
                    charging_markers.append({
                        "t": ev["triggered_at_time_min"],
                        "soc": round(ev["triggered_at_soc_pct"], 1),
                        "spklu": ev.get("spklu_id", ""),
                    })
                if trip.get("stranded_event"):
                    ev = trip["stranded_event"]
                    stranded_markers.append({
                        "t": ev["at_time_min"],
                        "soc": round(ev["at_soc_pct"], 1),
                    })

            buses_out.append({
                "route_id": route["route_id"],
                "bus_id": bus["bus_id"],
                "series": series,
                "charging_markers": charging_markers,
                "stranded_markers": stranded_markers,
                "is_stranded": bus.get("is_stranded", False),
            })

    return {
        "scenario_id": scenario_id,
        "buses": buses_out,
        "threshold_charge_pct": 30.0,
        "threshold_hard_pct": 20.0,
    }

