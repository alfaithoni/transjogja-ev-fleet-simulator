# -*- coding: utf-8 -*-
"""
scripts/calibrate_l1.py
-----------------------
T-05: Kalibrasi parameter k1, k2 model drain baterai terhadap baseline Rute L-1.

Target kalibrasi (dari wawancara + design.md §5):
  - 2 bus beroperasi di L-1 (loop 16.44 km, headway target ~45 menit Dishub)
  - Charging terpicu saat SoC <= 30%
  - Total downtime 1 sesi charging (as-is Adisucipto): ~120 menit (30 tempuh + 60 isi)
  - Setelah charging, SoC kembali ke 100%
  - Jam operasional 05:30-20:30 (900 menit)

Metodologi kalibrasi:
  1. Estimasi kecepatan rata-rata L-1 dari panjang rute & headway
  2. Hitung berapa rit yang bisa diselesaikan 1 bus dalam 900 menit operasional
  3. Cari k1, k2 sehingga pola charging (kapan SoC mencapai 30%, berapa sesi/hari)
     konsisten secara kualitatif dengan deskripsi lapangan.
  4. Output: nilai k1, k2 yang direkomendasikan + tabel sanity check.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulation.battery import BatteryDrainModel

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def load_l1() -> dict:
    with open(ROOT / "data" / "routes.json", encoding="utf-8") as f:
        routes = json.load(f)
    for r in routes:
        if r["route_id"] == "L-1":
            return r
    raise KeyError("Route L-1 not found")


def load_spec() -> dict:
    with open(ROOT / "data" / "bus_spec.json", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Simulasi 1 hari operasional (simple, tanpa charging decision module penuh)
# ---------------------------------------------------------------------------

def simulate_one_day_l1(
    model: BatteryDrainModel,
    stops: list[dict],
    n_bus: int = 2,
    operating_min: int = 900,
    trip_time_min: int | None = None,
    travel_to_spklu_min: int = 30,
    charging_duration_min: int = 60,
    soc_threshold: float = 30.0,
    verbose: bool = False,
) -> dict:
    """
    Simulasi 1 hari operasional untuk n_bus bus di rute L-1 dengan
    mekanisme opportunity charging sederhana (tidak ada antrian SPKLU).

    Parameters
    ----------
    trip_time_min : waktu 1 rit (menit). Jika None, dihitung otomatis dari
                    panjang rute / estimasi kecepatan rata-rata (~20 km/jam).

    Returns dict berisi statistik per bus & ringkasan.
    """
    # Estimasi waktu 1 rit jika tidak diberikan
    if trip_time_min is None:
        route_km = sum(s.get("dist_from_prev_m", 0) for s in stops) / 1000.0
        avg_speed_kmh = 20.0  # estimasi kecepatan rata-rata bus kota Yogyakarta
        trip_time_min = int((route_km / avg_speed_kmh) * 60)

    if verbose:
        route_km = sum(s.get("dist_from_prev_m", 0) for s in stops) / 1000.0
        print(f"  Panjang rute L-1  : {route_km:.2f} km")
        print(f"  Waktu 1 rit       : {trip_time_min} menit")
        print(f"  Total operasional : {operating_min} menit")

    bus_stats = []
    for bus_idx in range(n_bus):
        soc = 100.0
        current_time = 0  # menit ke-0 = 05:30
        trip_count = 0
        charging_sessions = 0
        soc_history = [(0, soc)]
        charging_events = []
        breach_events = []

        while current_time + trip_time_min <= operating_min:
            # Jalankan 1 rit
            result = model.simulate_trip("L-1", stops, initial_soc_pct=soc)
            soc_after_trip = result.final_soc_pct
            trip_count += 1
            current_time += trip_time_min
            soc = soc_after_trip
            soc_history.append((current_time, soc))

            if soc <= 20.0:
                breach_events.append({"time_min": current_time, "soc_pct": soc})

            # Cek apakah perlu charging
            if soc <= soc_threshold:
                downtime = travel_to_spklu_min + charging_duration_min
                if current_time + downtime <= operating_min:
                    charging_events.append({
                        "triggered_at_time_min": current_time,
                        "triggered_at_soc_pct": round(soc, 2),
                        "travel_min": travel_to_spklu_min,
                        "charging_min": charging_duration_min,
                        "downtime_total_min": downtime,
                        "resume_at_time_min": current_time + downtime,
                    })
                    current_time += downtime
                    soc = 100.0  # charge penuh
                    soc_history.append((current_time, soc))
                    charging_sessions += 1
                else:
                    # Tidak cukup waktu untuk charging → catat
                    charging_events.append({
                        "triggered_at_time_min": current_time,
                        "triggered_at_soc_pct": round(soc, 2),
                        "note": "Waktu operasional tidak cukup untuk charging — akhir hari"
                    })

        bus_stats.append({
            "bus_id": f"L-1-{bus_idx+1:02d}",
            "trips_completed": trip_count,
            "charging_sessions": charging_sessions,
            "final_soc_pct": round(soc, 2),
            "breach_hard_limit_count": len(breach_events),
            "soc_history": soc_history,
            "charging_events": charging_events,
        })

    return {
        "n_bus": n_bus,
        "trip_time_min": trip_time_min,
        "operating_min": operating_min,
        "buses": bus_stats,
        "total_trips": sum(b["trips_completed"] for b in bus_stats),
        "total_charging_sessions": sum(b["charging_sessions"] for b in bus_stats),
        "total_breaches": sum(b["breach_hard_limit_count"] for b in bus_stats),
    }


# ---------------------------------------------------------------------------
# Grid search kalibrasi
# ---------------------------------------------------------------------------

def calibrate(stops: list[dict], spec: dict) -> dict:
    """
    Cari kombinasi k1, k2 yang menghasilkan pola charging konsisten
    dengan data lapangan L-1.

    Target kualitatif:
    - Bus bisa menyelesaikan >= 5 rit sebelum charging pertama (dari 100%)
    - Jumlah sesi charging per bus per hari: 1-3 sesi
    - Tidak ada breach hard limit (SoC tidak menyentuh 20% saat beroperasi normal)
    - SoC akhir rit pertama: 85-93% (untuk L-1 ~16.44 km)
    """
    battery_kwh = spec["battery_capacity_kwh_default"]
    c_kwh_per_km = spec["drain_model"]["c_kwh_per_km"]

    # Grid search
    k1_values = [0.002, 0.003, 0.004, 0.005, 0.006, 0.008, 0.010]
    k2_values = [0.010, 0.015, 0.020, 0.025, 0.030]

    results = []
    for k1 in k1_values:
        for k2 in k2_values:
            m = BatteryDrainModel(
                battery_capacity_kwh=battery_kwh,
                c_kwh_per_km=c_kwh_per_km,
                k1=k1,
                k2=k2,
            )
            # Rit tunggal dari 100% untuk cek SoC akhir
            single = m.simulate_trip("L-1", stops, initial_soc_pct=100.0)
            soc_after_1_trip = single.final_soc_pct

            # Simulasi 1 hari (1 bus)
            day = simulate_one_day_l1(m, stops, n_bus=1, verbose=False)
            bus = day["buses"][0]

            score = 0
            notes = []

            # Kriteria 1: SoC akhir rit pertama 85-93%
            if 85.0 <= soc_after_1_trip <= 93.0:
                score += 2
                notes.append("OK: SoC akhir rit-1 normal")
            elif 80.0 <= soc_after_1_trip <= 95.0:
                score += 1
                notes.append("~OK: SoC akhir rit-1 dalam batas lebar")
            else:
                notes.append(f"X: SoC akhir rit-1 = {soc_after_1_trip:.1f}%")

            # Kriteria 2: Jumlah sesi charging 1-3/hari/bus
            cs = bus["charging_sessions"]
            if 1 <= cs <= 3:
                score += 2
                notes.append(f"OK: {cs} sesi charging/hari")
            elif cs == 0:
                score += 0
                notes.append("X: Tidak ada charging (model terlalu efisien?)")
            else:
                score += 0
                notes.append(f"X: {cs} sesi charging/hari (terlalu banyak)")

            # Kriteria 3: Tidak ada breach hard limit saat normal operation
            if bus["breach_hard_limit_count"] == 0:
                score += 1
                notes.append("OK: Tidak ada breach hard limit")
            else:
                notes.append(f"X: {bus['breach_hard_limit_count']} breach")

            # Kriteria 4: Trip count per hari masuk akal (3-10 rit per bus)
            tc = bus["trips_completed"]
            if 3 <= tc <= 12:
                score += 1
                notes.append(f"OK: {tc} rit/hari")
            else:
                notes.append(f"?: {tc} rit/hari (cek)")

            results.append({
                "k1": k1,
                "k2": k2,
                "soc_after_1_trip": round(soc_after_1_trip, 2),
                "trips_per_day_1bus": tc,
                "charging_sessions_1bus": cs,
                "breach_count": bus["breach_hard_limit_count"],
                "score": score,
                "notes": "; ".join(notes),
            })

    # Sort by score descending
    results.sort(key=lambda x: (-x["score"], x["k1"], x["k2"]))
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 65)
    print("T-05: Kalibrasi k1, k2 — Baseline Rute L-1")
    print("=" * 65)

    route = load_l1()
    spec = load_spec()
    stops = route["stops"]

    print(f"\nRute L-1: {route['path_label']}")
    print(f"  Panjang          : {route['route_length_km']} km")
    print(f"  Jumlah bus       : {route['bus_count']}")
    print(f"  Headway Dishub   : {route['headway_dishub_min']} menit")
    print(f"  Baterai default  : {spec['battery_capacity_kwh_default']} kWh")
    print(f"  c_kwh_per_km     : {spec['drain_model']['c_kwh_per_km']:.4f} kWh/km")

    # Jalankan kalibrasi grid search
    print("\n[Grid Search] Mencari k1, k2 optimal...")
    results = calibrate(stops, spec)

    print(f"\n{'k1':>6} {'k2':>6} {'SoC rit-1':>10} {'Rit/hr':>7} {'Cas/hr':>7} {'Breach':>7} {'Score':>6}")
    print("-" * 65)
    for r in results[:15]:  # tampilkan top-15
        print(
            f"{r['k1']:>6.3f} {r['k2']:>6.3f} "
            f"{r['soc_after_1_trip']:>10.2f}% "
            f"{r['trips_per_day_1bus']:>7d} "
            f"{r['charging_sessions_1bus']:>7d} "
            f"{r['breach_count']:>7d} "
            f"{r['score']:>6}"
        )

    best = results[0]
    print(f"\n[BEST] k1={best['k1']}, k2={best['k2']} (score={best['score']})")
    print(f"       {best['notes']}")

    # Simulasi detail dengan parameter terbaik
    print(f"\n[Detail] Simulasi 2-bus L-1 dengan k1={best['k1']}, k2={best['k2']}:")
    m_best = BatteryDrainModel(
        battery_capacity_kwh=spec["battery_capacity_kwh_default"],
        c_kwh_per_km=spec["drain_model"]["c_kwh_per_km"],
        k1=best["k1"],
        k2=best["k2"],
    )
    day_result = simulate_one_day_l1(m_best, stops, n_bus=2, verbose=True)

    for bus in day_result["buses"]:
        print(f"\n  Bus {bus['bus_id']}:")
        print(f"    Rit selesai       : {bus['trips_completed']}")
        print(f"    Sesi charging     : {bus['charging_sessions']}")
        print(f"    Breach hard limit : {bus['breach_hard_limit_count']}")
        print(f"    SoC akhir hari    : {bus['final_soc_pct']}%")
        if bus["charging_events"]:
            print(f"    Charging events:")
            for ev in bus["charging_events"]:
                if "note" in ev:
                    print(f"      t={ev['triggered_at_time_min']}min "
                          f"(SoC={ev['triggered_at_soc_pct']}%) -> {ev['note']}")
                else:
                    print(f"      t={ev['triggered_at_time_min']}min "
                          f"(SoC={ev['triggered_at_soc_pct']}%) "
                          f"-> downtime={ev['downtime_total_min']}min, "
                          f"resume t={ev['resume_at_time_min']}min")

    # Rekomendasi update bus_spec.json
    print(f"\n[REKOMENDASI] Update bus_spec.json drain_model:")
    print(f'    "k1": {best["k1"]},')
    print(f'    "k2": {best["k2"]}')
    print(f"\n[INFO] Target kalibrasi:")
    print(f"  - SoC akhir rit-1 (L-1 ~16km dari 100%) : {best['soc_after_1_trip']}%")
    print(f"  - Rit/hari per bus                       : {best['trips_per_day_1bus']}")
    print(f"  - Sesi charging/hari per bus             : {best['charging_sessions_1bus']}")
    print(f"  - Downtime per sesi (as-is)              : 120 menit")
    print(f"  - Total downtime 2 bus/hari              : "
          f"{day_result['total_charging_sessions'] * 120} menit")


if __name__ == "__main__":
    main()
