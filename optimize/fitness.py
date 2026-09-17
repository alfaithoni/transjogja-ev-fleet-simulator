# -*- coding: utf-8 -*-
"""
optimize/fitness.py
--------------------
Fitness function = simulasi Monte Carlo yang SUDAH ADA (GlobalSimulator), bukan
model deterministik baru. Aggregasi metrik meniru persis pola yang dipakai di
scratch/run_all_final_31.py supaya angka dari optimizer bisa dibandingkan
apple-to-apple dengan S17b/S28/S33/S35 di comparison_table_stochastic.csv.

Metrik utama (2 objective, selaras dgn cara kerja manual sebelumnya):
  1. avg_degraded_routes_per_day_mean  -> MINIMIZE (paling penting; S33/S35 = 0.00)
  2. total_gun                         -> MINIMIZE (proxy biaya infrastruktur)
Metrik sekunder (dicatat, tidak dioptimasi langsung):
  - avg_headway_mean (rute yang TIDAK degraded)
  - queue_timeouts_mean

N_SEARCH lebih kecil dari N_CONFIRM sesuai rencana kerja: cepat saat mencari
kandidat (GA/Bayesian butuh ratusan-ribuan evaluasi), lalu re-run N=100 di
kandidat terbaik untuk angka final yang dilaporkan di TA.
"""

from __future__ import annotations
import random
import numpy as np

from simulation.engine import GlobalSimulator


def run_monte_carlo(scenario: dict, routes_data: list, spec: dict, spklu_data_static: dict,
                     n_days: int = 20, seed_base: int = 42, segment_cv: float = 0.05) -> dict:
    """Jalankan GlobalSimulator n_days kali dengan seed berbeda, aggregasi hasil.

    spklu_data_static: dipakai HANYA untuk depot_locations & fallback n_gun default
    (format sama seperti data/spklu_locations.json). n_gun aktual tetap datang dari
    scenario["spklu_details"][loc]["n_gun"] (lihat GlobalSimulator.run(), override
    dari spklu_details didahulukan atas spklu_locations.json).
    """
    daily_headways, daily_degraded, daily_timeouts, daily_requests = [], [], [], []

    for day in range(n_days):
        engine = GlobalSimulator(routes_data, spec, scenario, spklu_locations=spklu_data_static)
        random.seed(seed_base + day)
        np.random.seed(seed_base + day)
        engine.daily_time_modifier = random.uniform(0.8, 1.2)
        engine.segment_cv = segment_cv

        res = engine.run()

        iterator = res.get("routes", res.values()) if isinstance(res, dict) else res

        hws, deg_count, to_count, req_count = [], 0, 0, 0
        for r in iterator:
            if isinstance(r, list):
                continue
            is_degraded = r.get("route_degraded", False)
            if is_degraded:
                deg_count += 1
            hw_val = r.get("headway_mean") or r.get("headway_actual", {}).get("avg_min")
            if not is_degraded and hw_val is not None:
                hws.append(hw_val)
            to_count += r.get("queue_timeouts", 0)
            req_count += r.get("charge_requests", 0)

        daily_headways.append(np.mean(hws) if hws else float("nan"))
        daily_degraded.append(deg_count)
        daily_timeouts.append(to_count)
        daily_requests.append(req_count)

    hw_arr = np.array(daily_headways, dtype=float)
    return {
        "avg_headway_mean": float(np.nanmean(hw_arr)) if not np.isnan(hw_arr).all() else float("nan"),
        "avg_headway_std": float(np.nanstd(hw_arr)) if not np.isnan(hw_arr).all() else float("nan"),
        "avg_degraded_routes_per_day_mean": float(np.mean(daily_degraded)),
        "avg_degraded_routes_per_day_std": float(np.std(daily_degraded)),
        "queue_timeouts_mean": float(np.mean(daily_timeouts)),
        "total_requests_mean": float(np.mean(daily_requests)),
        "n_days": n_days,
        "segment_cv": segment_cv,
    }


def evaluate_chromosome(chromo: dict, decision_space, routes_data: list, spec: dict,
                         spklu_data_static: dict, n_days: int = 20, seed_base: int = 42) -> dict:
    scenario = decision_space.decode_to_scenario(chromo)
    metrics = run_monte_carlo(scenario, routes_data, spec, spklu_data_static, n_days=n_days, seed_base=seed_base)
    metrics["total_gun"] = decision_space.total_gun(chromo)
    metrics["n_active_locations"] = decision_space.n_active_locations(chromo)
    metrics["algo"] = chromo["algo"]
    return metrics


def scalarize(metrics: dict, degraded_penalty_weight: float = 1000.0) -> float:
    """Weighted-sum scalar untuk GA single-objective / ranking cepat.

    degraded_penalty_weight besar SENGAJA -- histori manual TA ini menunjukkan
    0 degraded route adalah syarat hampir mutlak sebelum penghematan gun jadi
    relevan (S28 26 gun/0.01 degraded vs S33 sama infra + algo = 0.00 degraded
    dianggap kualitatif jauh lebih baik walau gun sama). Kalau mau eksplorasi
    trade-off, pakai NSGA-II 2-objective (lihat ga_optimizer.py) bukan scalar ini.
    """
    if np.isnan(metrics["avg_headway_mean"]):
        return float("inf")  # semua rute degraded -> skenario tidak valid, buang
    return (metrics["avg_degraded_routes_per_day_mean"] * degraded_penalty_weight
            + metrics["total_gun"])