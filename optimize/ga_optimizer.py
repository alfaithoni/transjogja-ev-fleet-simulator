# -*- coding: utf-8 -*-
"""
optimize/ga_optimizer.py
--------------------------
Genetic Algorithm sederhana (custom, tanpa dependency eksternal seperti DEAP)
untuk ruang keputusan di decision_space.py. Single-objective, scalarized lewat
fitness.scalarize() (degraded routes >> total gun).

Operator:
  - Selection : tournament (k=3)
  - Crossover : uniform per-gene utk assignment[route] & n_gun[loc]; assignment
                yg tidak valid setelah crossover diperbaiki lewat DecisionSpace.repair()
  - Mutasi    : per-gene, tiap gene (assignment satu rute / n_gun satu lokasi /
                toggle active satu lokasi / ganti algo) punya peluang mutasi kecil
  - Elitism   : elite_size individu terbaik selalu lolos ke generasi berikutnya

Cara pakai (dari root repo, setelah data prep step 1-2 selesai):
    python -m optimize.ga_optimizer --n-days 20 --pop 30 --gens 25

Catatan performa: tiap evaluasi = n_days x 20 rute x DES simulation. Dengan
pop=30, gens=25 -> ~750 evaluasi x n_days=20 hari = 15.000 run simulasi rute.
Ini BISA lama (menit-jam tergantung mesin) -- turunkan pop/gens/n_days dulu utk
smoke test, baru naikkan kalau sudah yakin kodenya jalan benar.
"""

from __future__ import annotations
import argparse
import copy
import json
import os
import random
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimize.decision_space import DecisionSpace, CANDIDATE_LOCATIONS, ALGO_CHOICES, MIN_GUN, MAX_GUN
from optimize.fitness import evaluate_chromosome, scalarize


def crossover(parent_a: dict, parent_b: dict, ds: DecisionSpace, rng: random.Random) -> dict:
    child = {
        "active": {loc: rng.choice([parent_a["active"][loc], parent_b["active"][loc]]) for loc in CANDIDATE_LOCATIONS},
        "n_gun": {loc: rng.choice([parent_a["n_gun"][loc], parent_b["n_gun"][loc]]) for loc in CANDIDATE_LOCATIONS},
        "assignment": {rid: rng.choice([parent_a["assignment"][rid], parent_b["assignment"][rid]]) for rid in ds.route_ids},
        "algo": rng.choice([parent_a["algo"], parent_b["algo"]]),
    }
    return ds.repair(child, rng)


def mutate(chromo: dict, ds: DecisionSpace, rng: random.Random,
           p_active: float = 0.05, p_gun: float = 0.15, p_assign: float = 0.10, p_algo: float = 0.05) -> dict:
    chromo = copy.deepcopy(chromo)

    for loc in CANDIDATE_LOCATIONS:
        if rng.random() < p_active:
            chromo["active"][loc] = not chromo["active"][loc]
        if rng.random() < p_gun:
            delta = rng.choice([-2, -1, 1, 2])
            chromo["n_gun"][loc] = min(MAX_GUN, max(MIN_GUN, chromo["n_gun"][loc] + delta))

    for rid in ds.route_ids:
        if rng.random() < p_assign:
            choices = [loc for loc in ds.reachable[rid] if chromo["active"][loc]] or ds.reachable[rid]
            chromo["assignment"][rid] = rng.choice(choices)

    if rng.random() < p_algo:
        chromo["algo"] = rng.choice(ALGO_CHOICES)

    return ds.repair(chromo, rng)


def tournament_select(pop_with_fitness: list, k: int, rng: random.Random) -> dict:
    contenders = rng.sample(pop_with_fitness, k)
    contenders.sort(key=lambda pf: pf[1])  # fitness lebih kecil = lebih baik
    return contenders[0][0]


def run_ga(ds: DecisionSpace, routes_data, spec, spklu_data_static,
           pop_size: int = 30, generations: int = 25, elite_size: int = 3,
           n_days: int = 20, seed: int = 0, log_path: str = None) -> dict:
    rng = random.Random(seed)
    population = [ds.random_chromosome(rng) for _ in range(pop_size)]
    history = []
    best_overall = None
    best_overall_fitness = float("inf")

    for gen in range(generations):
        t0 = time.time()
        scored = []
        for i, chromo in enumerate(population):
            metrics = evaluate_chromosome(chromo, ds, routes_data, spec, spklu_data_static,
                                           n_days=n_days, seed_base=42 + gen * 1000 + i)
            fit = scalarize(metrics)
            scored.append((chromo, fit, metrics))

        scored.sort(key=lambda x: x[1])
        gen_best_chromo, gen_best_fit, gen_best_metrics = scored[0]
        if gen_best_fit < best_overall_fitness:
            best_overall_fitness = gen_best_fit
            best_overall = (gen_best_chromo, gen_best_metrics)

        elapsed = time.time() - t0
        record = {
            "gen": gen,
            "best_fitness": gen_best_fit,
            "best_degraded": gen_best_metrics["avg_degraded_routes_per_day_mean"],
            "best_total_gun": gen_best_metrics["total_gun"],
            "best_headway": gen_best_metrics["avg_headway_mean"],
            "elapsed_sec": round(elapsed, 1),
        }
        history.append(record)
        print(f"[gen {gen:02d}] fitness={gen_best_fit:.2f} degraded={record['best_degraded']:.2f} "
              f"gun={record['best_total_gun']} headway={record['best_headway']:.2f} ({elapsed:.1f}s)")

        # Elitism + reproduksi generasi berikutnya
        pop_with_fitness = [(c, f) for c, f, _ in scored]
        next_pop = [copy.deepcopy(c) for c, f in pop_with_fitness[:elite_size]]
        while len(next_pop) < pop_size:
            parent_a = tournament_select(pop_with_fitness, k=3, rng=rng)
            parent_b = tournament_select(pop_with_fitness, k=3, rng=rng)
            child = crossover(parent_a, parent_b, ds, rng)
            child = mutate(child, ds, rng)
            next_pop.append(child)
        population = next_pop

    if log_path:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    return {"best_chromosome": best_overall[0], "best_metrics": best_overall[1], "history": history}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--routes", default="data/routes.json")
    parser.add_argument("--spklu", default="data/spklu_locations.json")
    parser.add_argument("--matrix", default="data/route_spklu_distance_matrix.json")
    parser.add_argument("--spec", default="data/bus_spec.json")
    parser.add_argument("--pop", type=int, default=30)
    parser.add_argument("--gens", type=int, default=25)
    parser.add_argument("--elite", type=int, default=3)
    parser.add_argument("--n-days", type=int, default=20, help="Monte Carlo N saat search (kecil dulu)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="optimize/results/ga_best_scenario.json")
    parser.add_argument("--log", default="optimize/results/ga_history.json")
    args = parser.parse_args()

    ds = DecisionSpace.from_files(args.routes, args.spklu, args.matrix)
    routes_data = json.load(open(args.routes, encoding="utf-8"))
    spec = json.load(open(args.spec, encoding="utf-8"))
    spklu_data_static = json.load(open(args.spklu, encoding="utf-8"))

    result = run_ga(ds, routes_data, spec, spklu_data_static,
                     pop_size=args.pop, generations=args.gens, elite_size=args.elite,
                     n_days=args.n_days, seed=args.seed, log_path=args.log)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    best_scenario = ds.decode_to_scenario(result["best_chromosome"], scenario_id="ga_best")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"scenario": best_scenario, "chromosome": result["best_chromosome"],
                    "metrics_at_search_n": result["best_metrics"]}, f, indent=2)

    print("\n=== BEST (evaluated at search N, BELUM confirmation run N=100) ===")
    print(json.dumps(result["best_metrics"], indent=2))
    print(f"\nScenario tersimpan di {args.out} -- jalankan ulang dgn N=100 (pakai fitness.run_monte_carlo "
          f"langsung, atau taruh scenario ini di data/scenarios/ lalu jalankan lewat scratch/run_all_final_31.py "
          f"style script) sebelum dipakai sbg angka final di TA.")


if __name__ == "__main__":
    main()