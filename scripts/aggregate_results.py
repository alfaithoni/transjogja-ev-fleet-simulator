# -*- coding: utf-8 -*-
"""
scripts/aggregate_results.py
------------------------------
Baca semua data/results/simulation_result_*.json dan hasilkan
data/comparison_table.csv dengan kolom sesuai Implementation Plan Fase 3.

Kolom output:
  scenario_id, charging_mechanism, spklu_locations, extra_bus_total,
  avg_headway_all_routes, max_gap_too_wide, total_breach_hard_limit,
  soc_zero_count, queue_timeout_count, routes_degraded_count, headway_comparable

Penggunaan:
  python scripts/aggregate_results.py
"""

from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "data" / "results"
OUT_CSV = ROOT / "data" / "comparison_table.csv"


def summarize_spklu(result: dict) -> str:
    """Ringkaskan lokasi SPKLU dari metadata skenario ke string."""
    assignment = result.get("spklu_assignment", "single")
    if assignment == "none":
        return "Depot only"
    if assignment == "single":
        return "SPKLU-ADI"
    if assignment == "multi_by_route":
        return "SPKLU-ADI+JOM+CON+GIW"
    return assignment


def aggregate_headway(route_results: list[dict]) -> tuple:
    """
    Hitung avg_headway dan total_gap_too_wide hanya dari rute non-degraded
    yang punya data headway valid (avg_min tidak None).

    total_gap_too_wide = JUMLAH seluruh gap terlebar di semua rute (sum, bukan max).
    Ini berbeda dari max_gap_too_wide (nilai terbesar 1 rute) yang sebelumnya
    dipakai. Total lebih informatif untuk perbandingan antar-skenario.

    Returns (avg_headway, total_wide, scenario_soc_0, scenario_q_to).
    """
    valid_avgs = []
    total_wide = 0
    scenario_soc_0 = 0
    scenario_q_to = 0

    for r in route_results:
        hw = r.get("headway_actual", {})
        degraded = r.get("route_degraded", False)

        for b in r.get("buses", []):
            for s in b.get("stranded_events", []):
                if s.get("reason") == "QUEUE_TIMEOUT":
                    scenario_q_to += 1
                else:
                    scenario_soc_0 += 1

        if degraded:
            continue  # skip degraded routes untuk avg headway
        avg = hw.get("avg_min")
        if avg is not None:
            valid_avgs.append(avg)
        total_wide += hw.get("gap_too_wide", 0)

    avg_headway = round(sum(valid_avgs) / len(valid_avgs), 2) if valid_avgs else None
    return avg_headway, total_wide, scenario_soc_0, scenario_q_to


def process_file(result_file: Path) -> dict:
    with open(result_file, encoding="utf-8") as f:
        data = json.load(f)

    scenario_id = data["scenario_id"]
    charging_mechanism = data.get("charging_mechanism", "")
    route_results = data.get("routes", [])
    summary = data.get("summary", {})

    spklu_locations = summarize_spklu(data)
    extra_bus_total = sum(r.get("extra_bus_count", 0) for r in route_results)

    avg_headway, total_gap_too_wide, soc_zero, q_to = aggregate_headway(route_results)

    total_breach = summary.get("total_breach_hard_limit", 0)
    routes_degraded = summary.get("routes_degraded_count", 0)
    headway_comparable = routes_degraded == 0

    return {
        "scenario_id": scenario_id,
        "charging_mechanism": charging_mechanism,
        "spklu_locations": spklu_locations,
        "extra_bus_total": extra_bus_total,
        "avg_headway_all_routes": avg_headway if avg_headway is not None else "null",
        "total_gap_too_wide": total_gap_too_wide,
        "total_breach_hard_limit": total_breach,
        "soc_zero_count": soc_zero,
        "queue_timeout_count": q_to,
        "routes_degraded_count": routes_degraded,
        "headway_comparable": str(headway_comparable).lower()
    }


def main():
    if not RESULTS_DIR.exists():
        print(f"[ERROR] Folder {RESULTS_DIR} tidak ditemukan. Jalankan simulasi terlebih dahulu.")
        sys.exit(1)

    result_files = sorted(RESULTS_DIR.glob("simulation_result_*.json"))
    if not result_files:
        print(f"[ERROR] Tidak ada file simulation_result_*.json di {RESULTS_DIR}")
        sys.exit(1)

    print(f"Membaca {len(result_files)} file hasil simulasi...")

    rows = []
    errors = []
    for f in result_files:
        try:
            row = process_file(f)
            rows.append(row)
            print(f"  OK: {f.name} -> scenario_id={row['scenario_id']}, "
                  f"headway_comparable={row['headway_comparable']}, "
                  f"routes_degraded={row['routes_degraded_count']}")
        except Exception as e:
            errors.append(f"[ERROR] {f.name}: {e}")
            print(f"  ERROR: {f.name}: {e}")

    if not rows:
        print("[ERROR] Tidak ada data yang berhasil dibaca.")
        sys.exit(1)

    # Urutkan berdasarkan scenario_id
    rows.sort(key=lambda r: r["scenario_id"])

    # Tulis CSV
    fieldnames = [
        "scenario_id", "charging_mechanism", "spklu_locations",
        "extra_bus_total", "avg_headway_all_routes", "total_gap_too_wide",
        "total_breach_hard_limit", "soc_zero_count", "queue_timeout_count",
        "routes_degraded_count", "headway_comparable",
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n[OK] comparison_table.csv tersimpan di: {OUT_CSV}")
    print(f"     {len(rows)} skenario, {len(errors)} error")

    # Cetak tabel ke terminal
    print("\n" + "=" * 105)
    print(f"{'scenario_id':<35} {'mech':<20} {'extra_bus':>9} {'avg_hw':>7} "
          f"{'tot_wide':>9} {'soc0':>5} {'q_to':>5} {'degraded':>8} {'comparable':>10}")
    print("-" * 105)
    for r in rows:
        print(f"{r['scenario_id']:<35} {r['charging_mechanism']:<20} "
              f"{r['extra_bus_total']:>9} {str(r['avg_headway_all_routes']):>7} "
              f"{r['total_gap_too_wide']:>9} {r['soc_zero_count']:>5} {r['queue_timeout_count']:>5} "
              f"{r['routes_degraded_count']:>8} {r['headway_comparable']:>10}")
    print("=" * 105)

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
