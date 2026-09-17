# -*- coding: utf-8 -*-
"""
optimize/bayesian_optimizer.py
---------------------------------
Alternatif GA: Bayesian Optimization pakai Optuna (TPE sampler). Ruang keputusan
SAMA dgn decision_space.py, cuma cara sampling-nya beda (Optuna belajar dari
trial sebelumnya, bukan populasi+mutasi).

Install dulu kalau belum ada: pip install optuna

Cara pakai:
    python -m optimize.bayesian_optimizer --n-trials 300 --n-days 20

Catatan: Optuna men-support dynamic/conditional search space secara native
(suggest_categorical dipanggil beda-beda tiap trial tergantung `active` yang
disample duluan) -- jadi encoding di bawah TIDAK perlu fixed-length vector
seperti GA, tapi tetap pakai DecisionSpace.repair() supaya rute yang di-assign
ke lokasi non-aktif tetap diperbaiki.
"""

from __future__ import annotations
import argparse
import json
import os
import random
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimize.decision_space import DecisionSpace, CANDIDATE_LOCATIONS, ALGO_CHOICES, MIN_GUN, MAX_GUN
from optimize.fitness import evaluate_chromosome, scalarize

try:
    import optuna
except ImportError:
    optuna = None


def suggest_chromosome(trial, ds: DecisionSpace) -> dict:
    active = {loc: trial.suggest_categorical(f"active_{loc}", [True, False]) for loc in CANDIDATE_LOCATIONS}
    n_gun = {loc: trial.suggest_int(f"n_gun_{loc}", MIN_GUN, MAX_GUN) for loc in CANDIDATE_LOCATIONS}
    assignment = {}
    for rid in ds.route_ids:
        choices = [loc for loc in ds.reachable[rid] if active[loc]] or ds.reachable[rid]
        assignment[rid] = trial.suggest_categorical(f"assign_{rid}", choices)
    algo = trial.suggest_categorical("algo", ALGO_CHOICES)

    chromo = {"active": active, "n_gun": n_gun, "assignment": assignment, "algo": algo}
    return ds.repair(chromo, random.Random(trial.number))


def make_objective(ds: DecisionSpace, routes_data, spec, spklu_data_static, n_days: int):
    def objective(trial):
        chromo = suggest_chromosome(trial, ds)
        metrics = evaluate_chromosome(chromo, ds, routes_data, spec, spklu_data_static,
                                       n_days=n_days, seed_base=42 + trial.number)
        # simpan metrics mentah di trial supaya bisa ditarik lagi setelah study selesai
        for k, v in metrics.items():
            trial.set_user_attr(k, v)
        return scalarize(metrics)
    return objective


def main():
    if optuna is None:
        print("Optuna belum terinstall. Jalankan: pip install optuna")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--routes", default="data/routes.json")
    parser.add_argument("--spklu", default="data/spklu_locations.json")
    parser.add_argument("--matrix", default="data/route_spklu_distance_matrix.json")
    parser.add_argument("--spec", default="data/bus_spec.json")
    parser.add_argument("--n-trials", type=int, default=300)
    parser.add_argument("--n-days", type=int, default=20, help="Monte Carlo N saat search (kecil dulu)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="optimize/results/bayesian_best_scenario.json")
    parser.add_argument("--study-db", default=None, help="Opsional: sqlite:///optimize/results/study.db utk resume")
    args = parser.parse_args()

    ds = DecisionSpace.from_files(args.routes, args.spklu, args.matrix)
    routes_data = json.load(open(args.routes, encoding="utf-8"))
    spec = json.load(open(args.spec, encoding="utf-8"))
    spklu_data_static = json.load(open(args.spklu, encoding="utf-8"))

    sampler = optuna.samplers.TPESampler(seed=args.seed)
    study = optuna.create_study(direction="minimize", sampler=sampler,
                                 storage=args.study_db, load_if_exists=bool(args.study_db))
    study.optimize(make_objective(ds, routes_data, spec, spklu_data_static, args.n_days),
                    n_trials=args.n_trials, show_progress_bar=True)

    best_trial = study.best_trial
    best_chromo = suggest_chromosome_from_params(best_trial.params, ds)  # rekonstruksi utk decode scenario
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    best_scenario = ds.decode_to_scenario(best_chromo, scenario_id="bayesian_best")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "scenario": best_scenario,
            "chromosome": best_chromo,
            "metrics_at_search_n": {k: v for k, v in best_trial.user_attrs.items()},
            "best_value": best_trial.value,
        }, f, indent=2)

    print("\n=== BEST (evaluated at search N, BELUM confirmation run N=100) ===")
    print(json.dumps(best_trial.user_attrs, indent=2))
    print(f"\nScenario tersimpan di {args.out}")


def suggest_chromosome_from_params(params: dict, ds: DecisionSpace) -> dict:
    """Rekonstruksi chromosome dari optuna best_trial.params (tanpa perlu re-run trial)."""
    active = {loc: params[f"active_{loc}"] for loc in CANDIDATE_LOCATIONS}
    n_gun = {loc: params[f"n_gun_{loc}"] for loc in CANDIDATE_LOCATIONS}
    assignment = {rid: params[f"assign_{rid}"] for rid in ds.route_ids}
    algo = params["algo"]
    chromo = {"active": active, "n_gun": n_gun, "assignment": assignment, "algo": algo}
    return ds.repair(chromo, random.Random(0))


if __name__ == "__main__":
    main()