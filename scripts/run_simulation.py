# -*- coding: utf-8 -*-
"""
scripts/run_simulation.py
--------------------------
T-09/T-10: Jalankan simulasi 1 rute / semua rute dari file skenario JSON,
            ekspor simulation_result_<scenario_id>.json ke data/results/.

Penggunaan:
  python scripts/run_simulation.py --scenario-file data/scenarios/s1_baseline_opportunity.json
  python scripts/run_simulation.py --scenario-file data/scenarios/s2_full_depot.json --route L-1
"""

from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulation.engine import GlobalSimulator


def load_data() -> tuple[list[dict], dict]:
    with open(ROOT / "data" / "routes.json", encoding="utf-8") as f:
        routes = json.load(f)
    with open(ROOT / "data" / "bus_spec.json", encoding="utf-8") as f:
        spec = json.load(f)
    return routes, spec


def load_scenario(scenario_file: Path) -> dict:
    with open(scenario_file, encoding="utf-8") as f:
        return json.load(f)


def resolve_spklu(scenario: dict, route_id: str) -> dict:
    """
    Kembalikan config SPKLU untuk rute ini berdasarkan spklu_assignment.
    - 'single'        : gunakan single_spklu untuk semua rute
    - 'multi_by_route': lookup di spklu_assignment_map
    - 'none'          : tidak ada SPKLU mid-day (full_depot)
    """
    assignment = scenario.get("spklu_assignment", "single")

    if assignment == "none":
        # full_depot: kembalikan dummy (tidak akan pernah dipakai karena mekanisme=full_depot)
        return {"id": "NONE", "name": "No SPKLU", "travel_min": 0, "charge_min": 0}

    if assignment == "single":
        return scenario["single_spklu"]

    if assignment == "multi_by_route":
        assignment_map = scenario["spklu_assignment_map"]   # {spklu_id: [route_ids]}
        spklu_details = scenario["spklu_details"]
        for spklu_id, route_list in assignment_map.items():
            if route_id in route_list:
                detail = spklu_details[spklu_id]
                return {
                    "id": spklu_id,
                    "name": detail["name"],
                    "travel_min": detail["travel_min"],
                    "charge_min": detail["charge_min"],
                }
        # Fallback ke SPKLU-ADI jika tidak ada di map
        import warnings
        warnings.warn(f"[WARN] Rute {route_id} tidak ada di spklu_assignment_map, fallback ke SPKLU-ADI")
        return {"id": "SPKLU-ADI", "name": "SPKLU Adisucipto (fallback)", "travel_min": 30, "charge_min": 60}

    raise ValueError(f"spklu_assignment '{assignment}' tidak dikenal.")


def calc_stagger(route: dict, total_bus_count: int) -> int:
    """
    Hitung stagger antar bus secara otomatis per rute:
      stagger = round(headway_dishub_min / total_bus_count)

    Mengikuti pola tervalidasi Fase 2: L-1 headway=45 menit, 2 bus
    → stagger 22 menit (45/2 = 22.5 → dibulatkan 22).

    Untuk extra bus (s4/s5), total_bus_count sudah termasuk bus tambahan
    sehingga stagger lebih kecil → distribusi keberangkatan lebih rapat.

    Fallback: stagger=0 jika headway_dishub_min tidak tersedia.
    """
    target_hw = route.get("headway_dishub_min")
    if target_hw and total_bus_count > 1:
        return round(target_hw / total_bus_count)
    return 0


def run_route(route: dict, spec: dict, scenario: dict) -> dict:
    route_id = route["route_id"]
    spklu = resolve_spklu(scenario, route_id)
    base_bus_count = route.get("bus_count", 1)
    extra_bus = scenario.get("extra_bus_per_route", 0)
    total_bus = base_bus_count + extra_bus
    stagger = calc_stagger(route, total_bus)

    sim = RouteSimulator(
        route=route,
        spec=spec,
        spklu=spklu,
        scenario_id=scenario["scenario_id"],
        charging_mechanism=scenario["charging_mechanism"],
        extra_bus_per_route=extra_bus,
        op_end_min=900,
        speed_kmph=20.0,
        stagger_min=stagger,
        depot_config=scenario.get("depot_config", {}),
    )
    return sim.run()


def print_summary(result: dict) -> None:
    rid = result["route_id"]
    s = result["summary"]
    hw = result["headway_actual"]
    degraded = result.get("route_degraded", False)
    print(f"\nRute {rid}:{' [DEGRADED]' if degraded else ''}")
    print(f"  Bus            : {result['bus_count']} (extra: {result.get('extra_bus_count', 0)})")
    print(f"  Stagger        : {result.get('stagger_min_used', '?')} menit antar bus")
    print(f"  Total rit      : {s['total_trips']}")
    print(f"  Charging sesi  : {s['total_charging_sessions']}")
    print(f"  Breach HL (<=20%): {s['total_breach_hard_limit']}")
    print(f"  Bus stranded   : {s['total_stranded_buses']}")
    print(f"  SoC=0 incidents: {s['soc_zero_incidents']}")
    if hw.get("avg_min") is not None:
        print(f"  Headway target : {hw['target_headway_min']} menit")
        print(f"  Headway aktual : avg={hw['avg_min']} min (pre-degradation), "
              f"min={hw['min_min']} min, max={hw['max_min']} min")
        print(f"  Gap too wide   (>{hw['tolerance_pct']}% target): {hw['gap_too_wide']}")
        print(f"  Gap too narrow (<{hw['tolerance_pct']}% target): {hw['gap_too_narrow']}")
    elif degraded:
        print(f"  Headway        : N/A (route degraded sebelum 2 departure)")


def main():
    parser = argparse.ArgumentParser(description="TransJogja EV Sim — Fase 3 Runner")
    parser.add_argument("--scenario-file", required=True, metavar="PATH",
                        help="Path ke file skenario JSON (contoh: data/scenarios/s1_baseline_opportunity.json)")
    parser.add_argument("--route", default=None, metavar="ROUTE_ID",
                        help="Jalankan hanya 1 rute (opsional, default: semua rute)")
    args = parser.parse_args()

    scenario_path = ROOT / args.scenario_file if not Path(args.scenario_file).is_absolute() else Path(args.scenario_file)
    if not scenario_path.exists():
        print(f"[ERROR] File skenario tidak ditemukan: {scenario_path}")
        sys.exit(1)

    routes, spec = load_data()
    scenario = load_scenario(scenario_path)
    scenario_id = scenario["scenario_id"]

    # Pilih rute
    if args.route:
        selected = [r for r in routes if r["route_id"] == args.route]
        if not selected:
            print(f"[ERROR] Rute '{args.route}' tidak ditemukan.")
            sys.exit(1)
    else:
        selected = routes

    print("=" * 65)
    print(f"TransJogja EV Sim — Fase 3.5")
    print(f"Skenario    : {scenario_id}")
    print(f"Mekanisme   : {scenario['charging_mechanism']}")
    print(f"Extra bus   : {scenario.get('extra_bus_per_route', 0)} per rute")
    print(f"Rute        : {[r['route_id'] for r in selected]}")
    print("=" * 65)

    with open(ROOT / "data" / "spklu_locations.json", encoding="utf-8") as f:
        spklu_locations = json.load(f)

    sim = GlobalSimulator(
        routes=selected,
        spec=spec,
        scenario=scenario,
        spklu_locations=spklu_locations
    )
    
    try:
        sim_output = sim.run()
        route_results = sim_output["routes"]
    except Exception as e:
        print(f"\n[ERROR] Simulation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    warnings_log = []
    for result in route_results:
        print_summary(result)
        if result.get("route_degraded"):
            warnings_log.append(f"[WARN] Rute {result['route_id']} degraded — "
                                 f"{result['summary']['total_stranded_buses']} bus stranded.")

    # Bangun output sesuai schema.md §5
    total_degraded = sum(1 for r in route_results if r.get("route_degraded", False))
    output = {
        "scenario_id": scenario_id,
        "charging_mechanism": scenario["charging_mechanism"],
        "extra_bus_per_route": scenario.get("extra_bus_per_route", 0),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spklu_assignment": scenario.get("spklu_assignment", "single"),
        "routes": route_results,
        "warnings": warnings_log,
        "summary": {
            "total_routes": len(route_results),
            "total_buses": sum(r["bus_count"] for r in route_results),
            "total_trips": sum(r["summary"]["total_trips"] for r in route_results),
            "total_charging_sessions": sum(
                r["summary"]["total_charging_sessions"] for r in route_results),
            "total_queue_wait_min": sum(
                r["summary"].get("total_queue_wait_min", 0) for r in route_results),
            "total_breach_hard_limit": sum(
                r["summary"]["total_breach_hard_limit"] for r in route_results),
            "soc_zero_incidents": sum(
                r["summary"]["soc_zero_incidents"] for r in route_results),
            "routes_degraded_count": total_degraded,
        },
    }

    # Simpan ke data/results/
    out_dir = ROOT / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"simulation_result_{scenario_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 65)
    gs = output["summary"]
    print(f"[GLOBAL SUMMARY] Skenario: {scenario_id}")
    print(f"  Rute          : {gs['total_routes']}")
    print(f"  Bus           : {gs['total_buses']}")
    print(f"  Total rit     : {gs['total_trips']}")
    print(f"  Charging sesi : {gs['total_charging_sessions']}")
    print(f"  Breach HL     : {gs['total_breach_hard_limit']}")
    print(f"  SoC=0 insiden : {gs['soc_zero_incidents']}")
    print(f"  Rute degraded : {gs['routes_degraded_count']}")
    if warnings_log:
        print(f"\n  WARNINGS ({len(warnings_log)}):")
        for w in warnings_log:
            print(f"    {w}")
    print(f"\n  Output: {out_path}")
    print("=" * 65)


if __name__ == "__main__":
    main()
