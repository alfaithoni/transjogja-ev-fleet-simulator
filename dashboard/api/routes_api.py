# -*- coding: utf-8 -*-
"""
dashboard/api/routes_api.py
----------------------------
Flask Blueprint: semua /api/* endpoints.
"""

from flask import Blueprint, jsonify, abort
import re
from .data_loader import (
    get_routes, get_routes_meta, get_comparison_table,
    get_playback_data, get_soc_data,
    get_simulation_result,
    get_playback_data_all, get_soc_data_all,
    get_scenarios
)

api_bp = Blueprint("api", __name__)

# ---------------------------------------------------------------------------
# /api/routes  — struktur topologi 20 rute (stops tanpa soc_trace)
# ---------------------------------------------------------------------------
@api_bp.route("/routes")
def routes():
    """Kembalikan semua rute dengan daftar stops (nama + dist)."""
    routes_data = get_routes()
    # Kembalikan versi ringkas: tidak perlu seluruh stops detail untuk map
    out = []
    for r in routes_data:
        stops_light = [
            {"name": s["name"], "dist_from_prev_m": s.get("dist_from_prev_m", 0)}
            for s in r.get("stops", [])
        ]
        out.append({
            "route_id": r["route_id"],
            "bus_count": r.get("bus_count", 1),
            "headway_dishub_min": r.get("headway_dishub_min"),
            "stops": stops_light,
        })
    return jsonify(out)


# ---------------------------------------------------------------------------
# /api/scenarios  — list skenario tersedia
# ---------------------------------------------------------------------------
@api_bp.route("/scenarios")
def scenarios():
    """Kembalikan metadata skenario yang ada di comparison_table.csv."""
    try:
        table = get_comparison_table()
    except Exception:
        table = []
    
    out = []
    for row in table:
        sid = row.get("scenario_id")
        if not sid:
            continue
        try:
            data = get_simulation_result(sid)
            summary = data.get("summary", {})
            out.append({
                "scenario_id": sid,
                "label": sid,
                "charging_mechanism": data.get("charging_mechanism", ""),
                "extra_bus_per_route": data.get("extra_bus_per_route", 0),
                "routes_degraded_count": summary.get("routes_degraded_count", 0),
                "total_breach_hard_limit": summary.get("total_breach_hard_limit", 0),
                "is_degraded": summary.get("routes_degraded_count", 0) > 0,
            })
        except Exception:
            continue
        except FileNotFoundError:
            pass
    def natural_sort_key(s):
        return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s['scenario_id'])]
    
    out.sort(key=natural_sort_key)
    return jsonify(out)


# ---------------------------------------------------------------------------
# /api/comparison  — comparison_table.csv sebagai JSON
# ---------------------------------------------------------------------------
@api_bp.route("/comparison")
def comparison():
    table = get_comparison_table()
    def natural_sort_key(s):
        sid = s.get('scenario_id', '')
        return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', sid)]
    table.sort(key=natural_sort_key)
    return jsonify(table)


# ---------------------------------------------------------------------------
# /api/playback/<scenario_id>/<route_id>
# ---------------------------------------------------------------------------
@api_bp.route("/playback/<scenario_id>/<route_id>")
def playback(scenario_id, route_id):
    data = get_playback_data(scenario_id, route_id)
    if data is None:
        abort(404, f"Rute {route_id} tidak ditemukan di skenario {scenario_id}")
    return jsonify(data)


# ---------------------------------------------------------------------------
# /api/soc/<scenario_id>/<route_id>
# ---------------------------------------------------------------------------
@api_bp.route("/soc/<scenario_id>/<route_id>")
def soc(scenario_id, route_id):
    data = get_soc_data(scenario_id, route_id)
    if data is None:
        abort(404, f"Rute {route_id} tidak ditemukan di skenario {scenario_id}")
    return jsonify(data)


# ---------------------------------------------------------------------------
# /api/playback_all/<scenario_id>
# ---------------------------------------------------------------------------
@api_bp.route("/playback_all/<scenario_id>")
def playback_all(scenario_id):
    data = get_playback_data_all(scenario_id)
    return jsonify(data)


# ---------------------------------------------------------------------------
# /api/soc_all/<scenario_id>
# ---------------------------------------------------------------------------
@api_bp.route("/soc_all/<scenario_id>")
def soc_all(scenario_id):
    data = get_soc_data_all(scenario_id)
    return jsonify(data)

# ---------------------------------------------------------------------------
# /api/stranded/<scenario_id>  — semua stranded events di skenario ini
# ---------------------------------------------------------------------------
@api_bp.route("/stranded/<scenario_id>")
def stranded(scenario_id):
    try:
        data = get_simulation_result(scenario_id)
    except FileNotFoundError:
        abort(404)
    events = []
    for route in data.get("routes", []):
        for bus in route.get("buses", []):
            for ev in bus.get("stranded_events", []):
                events.append({
                    "route_id": route["route_id"],
                    "bus_id": bus["bus_id"],
                    **ev,
                })
    return jsonify({
        "scenario_id": scenario_id,
        "total_stranded": len(events),
        "events": events,
    })


# ---------------------------------------------------------------------------
# /api/headway/<scenario_id>/<route_id>  — headway detail untuk 1 rute
# ---------------------------------------------------------------------------
@api_bp.route("/headway/<scenario_id>/<route_id>")
def headway(scenario_id, route_id):
    try:
        data = get_simulation_result(scenario_id)
    except FileNotFoundError:
        abort(404)
    route = next((r for r in data.get("routes", []) if r["route_id"] == route_id), None)
    if not route:
        abort(404)
    return jsonify(route.get("headway_actual", {}))


# ---------------------------------------------------------------------------
# /api/regenerate/<scenario_id> — Hasilkan trace 1 hari yang benar-benar baru (Acak)
# ---------------------------------------------------------------------------
@api_bp.route("/regenerate/<scenario_id>", methods=["POST"])
def regenerate(scenario_id):
    """Jalankan simulasi 1 hari (unseeded/random) untuk scenario_id dan timpa file _live."""
    import json
    import random
    from pathlib import Path
    import sys
    
    # We must load the engine
    ROOT = Path(__file__).resolve().parent.parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    
    from simulation.engine import GlobalSimulator
    from .data_loader import _result_cache, SCENARIO_ALIASES
    
    # Map _live ids back to config files
    REGENERATE_MAP = {
        "s17b_live": "s17b_probabilistic_4loc_prop",
        "s28_live": "s28_s17b_extra_bus_scaled_infra",
        "s30_live": "s30_s17b_extra_bus_buffer_mid",
        "s31_live": "s31_s17b_dynamic_v1",
        "s32_live": "s32_s17b_dynamic_v2",
        "s33_live": "s33_ultimate",
        "s34_live": "s34_staggered",
        "s35_live": "s33_ultimate",  # Note: S35 needs config modification (23 guns) which we'll handle below
    }
    
    # scenario_id could be "s28_live" OR "s28_s17b_extra_bus_scaled_infra"
    config_name = REGENERATE_MAP.get(scenario_id, scenario_id)
    
    # The output file name should be the alias if it exists
    target_id = SCENARIO_ALIASES.get(scenario_id, scenario_id)
    # If the user passed "s28_live", SCENARIO_ALIASES doesn't have it, so target_id remains "s28_live"
    
    try:
        config_path = ROOT / "data" / "scenarios" / f"{config_name}.json"
        if not config_path.exists():
            return jsonify({"success": False, "error": f"Scenario {scenario_id} tidak bisa di-regenerate live karena config {config_name}.json tidak ditemukan."}), 400
            
        with open(config_path) as f:
            sc = json.load(f)
        with open(ROOT / "data" / "spklu_locations.json") as f:
            spklu_data = json.load(f)
        with open(ROOT / "data" / "routes.json") as f:
            routes_data = json.load(f)
        with open(ROOT / "data" / "bus_spec.json") as f:
            specs = json.load(f)
            
        # Handle S35 special config modifications
        if target_id == "s35_live":
            if "spklu_details" not in sc:
                sc["spklu_details"] = {}
            if "SPKLU-NGB" not in sc["spklu_details"]: sc["spklu_details"]["SPKLU-NGB"] = {}
            if "SPKLU-CON" not in sc["spklu_details"]: sc["spklu_details"]["SPKLU-CON"] = {}
            sc["spklu_details"]["SPKLU-NGB"]["n_gun"] = 8
            sc["spklu_details"]["SPKLU-CON"]["n_gun"] = 8

        # Unseeded - Full randomization!
        engine = GlobalSimulator(routes_data, specs, sc, spklu_locations=spklu_data)
        engine.daily_time_modifier = random.uniform(0.8, 1.2)
        engine.segment_cv = 0.05
        
        res = engine.run()
        routes_res = res.get("routes", res) if isinstance(res, dict) else res

        
        degraded_count = sum(1 for r in routes_res if r.get('route_degraded', False))
        total_breach = sum(r.get('headway_actual', {}).get('total_breach_hard_limit', 0) for r in routes_res)
        
        output = {
            "scenario_id": target_id,
            "charging_mechanism": sc.get("charging_mechanism", "opportunity"),
            "extra_bus_per_route": sc.get("extra_bus_per_route", 0),
            "summary": {
                "routes_degraded_count": degraded_count,
                "total_breach_hard_limit": total_breach
            },
            "routes": routes_res
        }
        
        out_path = ROOT / "data" / "results" / f"simulation_result_{target_id}.json"
        with open(out_path, 'w') as f:
            json.dump(output, f)
            
        # Clear cache in memory so new data is loaded
        if target_id in _result_cache:
            del _result_cache[target_id]
        if scenario_id in _result_cache:
            del _result_cache[scenario_id]
            
        return jsonify({"success": True, "message": f"Successfully regenerated {scenario_id} to {target_id}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

