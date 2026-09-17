"""
scripts/run_monte_carlo.py
---------------------------
Run any scenario N times with a different random seed per day (the
Monte Carlo layer described in Bab II/IV of the thesis) and report the
aggregate metrics in the same shape as data/comparison_table_stochastic.csv
(avg_headway_mean/std, avg_degraded_routes_per_day_mean/std, etc.).

This generalizes the one-off logic used during thesis development
(previously scattered across ad-hoc scripts not kept in this repo) into
a single reusable entry point for ANY scenario file in data/scenarios/.

Usage:
    python scripts/run_monte_carlo.py --scenario-file data/scenarios/s28_s17b_extra_bus_scaled_infra.json
    python scripts/run_monte_carlo.py --scenario-file data/scenarios/s17b_probabilistic_4loc_prop.json --n-days 100 --seed-base 42

Output:
    Prints the aggregate metrics to stdout and writes them to
    data/results/mc_<scenario_id>.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulation.engine import GlobalSimulator


def run_monte_carlo(scenario_path: Path, n_days: int, seed_base: int, segment_cv: float) -> dict:
    routes = json.load(open(ROOT / "data" / "routes.json", encoding="utf-8"))
    spec = json.load(open(ROOT / "data" / "bus_spec.json", encoding="utf-8"))
    spklu_locations = json.load(open(ROOT / "data" / "spklu_locations.json", encoding="utf-8"))
    scenario = json.load(open(scenario_path, encoding="utf-8"))

    daily_headways, daily_degraded, daily_timeouts, daily_requests = [], [], [], []

    for day in range(n_days):
        engine = GlobalSimulator(routes, spec, scenario, spklu_locations=spklu_locations)
        random.seed(seed_base + day)
        np.random.seed(seed_base + day)
        # Daily-level modifier: uniform(0.8, 1.2) approximates the 15% CV
        # log-normal daily layer described in Bab II/IV.
        engine.daily_time_modifier = random.uniform(0.8, 1.2)
        engine.segment_cv = segment_cv

        res = engine.run()
        route_results = res["routes"] if isinstance(res, dict) else res

        hws, deg_count, to_count, req_count = [], 0, 0, 0
        for r in route_results:
            if r.get("route_degraded", False):
                deg_count += 1
                continue
            hw_val = r.get("headway_actual", {}).get("avg_min")
            if hw_val is not None:
                hws.append(hw_val)
            req_count += r.get("summary", {}).get("total_charging_sessions", 0)
            for b in r.get("buses", []):
                for cs in b.get("charging_sessions", []):
                    if cs.get("is_abandoned"):
                        to_count += 1

        daily_headways.append(np.mean(hws) if hws else float("nan"))
        daily_degraded.append(deg_count)
        daily_timeouts.append(to_count)
        daily_requests.append(req_count)

        if (day + 1) % 20 == 0:
            print(f"  ... {day + 1}/{n_days} hari selesai")

    hw_arr = np.array(daily_headways, dtype=float)
    all_nan = np.isnan(hw_arr).all()
    return {
        "scenario_id": scenario["scenario_id"],
        "n_days": n_days,
        "avg_headway_mean": None if all_nan else round(float(np.nanmean(hw_arr)), 2),
        "avg_headway_std": None if all_nan else round(float(np.nanstd(hw_arr)), 2),
        "avg_degraded_routes_per_day_mean": round(float(np.mean(daily_degraded)), 2),
        "avg_degraded_routes_per_day_std": round(float(np.std(daily_degraded)), 2),
        "queue_timeouts_mean": round(float(np.mean(daily_timeouts)), 2),
        "total_requests_mean": round(float(np.mean(daily_requests)), 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo runner (N-day aggregate)")
    parser.add_argument("--scenario-file", required=True, metavar="PATH")
    parser.add_argument("--n-days", type=int, default=100)
    parser.add_argument("--seed-base", type=int, default=42)
    parser.add_argument("--segment-cv", type=float, default=0.05)
    args = parser.parse_args()

    scenario_path = ROOT / args.scenario_file if not Path(args.scenario_file).is_absolute() else Path(args.scenario_file)
    if not scenario_path.exists():
        print(f"[ERROR] File skenario tidak ditemukan: {scenario_path}")
        sys.exit(1)

    print(f"Menjalankan Monte Carlo (N={args.n_days}) untuk {scenario_path.name} ...")
    metrics = run_monte_carlo(scenario_path, args.n_days, args.seed_base, args.segment_cv)

    print("\n=== HASIL AGREGAT ===")
    print(json.dumps(metrics, indent=2))

    out_dir = ROOT / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"mc_{metrics['scenario_id']}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nDisimpan ke: {out_path}")
    print("\nBandingkan angka di atas dengan baris scenario_id yang sama di")
    print("data/comparison_table_stochastic.csv untuk verifikasi.")


if __name__ == "__main__":
    main()
