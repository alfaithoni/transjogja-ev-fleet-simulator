# -*- coding: utf-8 -*-
"""
scripts/test_all_routes.py
--------------------------
T-06: Uji drain model pada seluruh 20 rute (tanpa charging) untuk memastikan
      tidak ada error/edge-case.

Checks:
  - Tidak ada exception saat simulate_trip dijalankan
  - SoC tidak pernah negatif
  - SoC monoton turun (tidak pernah naik)
  - total_distance_km mendekati route_length_km (toleransi +-5%)
  - Rute L-1 (pendek ~16km) dan Rute 14 (panjang ~41km) diuji secara detail

Output: tabel ringkasan per rute + flag warning/error.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulation.battery import BatteryDrainModel

# ---------------------------------------------------------------------------

def load_data() -> tuple[list[dict], dict]:
    with open(ROOT / "data" / "routes.json", encoding="utf-8") as f:
        routes = json.load(f)
    with open(ROOT / "data" / "bus_spec.json", encoding="utf-8") as f:
        spec = json.load(f)
    return routes, spec


def check_monotone_decreasing(soc_trace) -> bool:
    """Return True jika SoC_after monoton turun (atau flat) sepanjang trace."""
    for i in range(len(soc_trace) - 1):
        if soc_trace[i].soc_after < soc_trace[i + 1].soc_after:
            return False
    return True


def main():
    print("=" * 75)
    print("T-06: Uji Drain Model Seluruh 20 Rute")
    print("=" * 75)

    routes, spec = load_data()
    model = BatteryDrainModel.from_spec(spec)

    print(f"\nModel params: battery={model.battery_capacity_kwh:.2f}kWh, "
          f"c={model.c_kwh_per_km:.4f}kWh/km, k1={model.k1}, k2={model.k2}")

    header = (
        f"{'Route':<8} {'KM deklarasi':>13} {'KM parsed':>10} "
        f"{'Delta%':>7} {'SoC akhir':>10} {'Monoton':>8} "
        f"{'Negatif':>8} {'Warnings'}"
    )
    print(f"\n{header}")
    print("-" * 95)

    all_passed = True
    route_results = []

    for route in routes:
        rid = route["route_id"]
        stops = route["stops"]
        declared_km = route.get("route_length_km", 0)
        warnings = []
        errors = []

        try:
            result = model.simulate_trip(rid, stops, initial_soc_pct=100.0)

            parsed_km = result.total_distance_km
            delta_pct = abs(parsed_km - declared_km) / declared_km * 100 if declared_km > 0 else 0
            final_soc = result.final_soc_pct
            monotone = check_monotone_decreasing(result.soc_trace)
            has_negative = any(rec.soc_after < 0 for rec in result.soc_trace)

            # Check tolerance jarak
            if delta_pct > 5.0:
                warnings.append(f"Jarak parsed vs deklarasi: {parsed_km:.2f}km vs {declared_km}km ({delta_pct:.1f}%)")

            if not monotone:
                errors.append("SoC TIDAK monoton turun!")

            if has_negative:
                errors.append("SoC NEGATIF terdeteksi!")

            if final_soc <= 30.0:
                warnings.append(f"SoC akhir <= 30% setelah 1 rit ({final_soc:.1f}%) — cek c_kwh_per_km")

            flag = "OK"
            if errors:
                flag = "ERROR"
                all_passed = False
            elif warnings:
                flag = "WARN"

            warn_str = "; ".join(errors + warnings) if (errors or warnings) else ""
            print(
                f"{rid:<8} {declared_km:>13.2f} {parsed_km:>10.2f} "
                f"{delta_pct:>7.1f}% {final_soc:>9.2f}% "
                f"{'YES' if monotone else 'NO!':>8} "
                f"{'NO' if not has_negative else 'YES!':>8} "
                f"{warn_str}"
            )

            route_results.append({
                "route_id": rid,
                "declared_km": declared_km,
                "parsed_km": round(parsed_km, 3),
                "delta_pct": round(delta_pct, 2),
                "final_soc_pct": round(final_soc, 2),
                "monotone": monotone,
                "has_negative_soc": has_negative,
                "status": flag,
                "warnings": warnings,
                "errors": errors,
            })

        except Exception as e:
            print(f"{rid:<8} {'':>13} {'':>10} {'':>7} {'':>10} {'':>8} {'':>8} "
                  f"[EXCEPTION] {type(e).__name__}: {e}")
            all_passed = False
            route_results.append({
                "route_id": rid, "status": "EXCEPTION", "exception": str(e)
            })

    print("-" * 95)

    # Ringkasan
    n_ok = sum(1 for r in route_results if r.get("status") == "OK")
    n_warn = sum(1 for r in route_results if r.get("status") == "WARN")
    n_err = sum(1 for r in route_results if r.get("status") in ("ERROR", "EXCEPTION"))

    print(f"\n[RINGKASAN] {n_ok} OK | {n_warn} WARNING | {n_err} ERROR")

    # Detail rute ekstrem
    if route_results:
        valid = [r for r in route_results if "parsed_km" in r]
        if valid:
            shortest = min(valid, key=lambda x: x["parsed_km"])
            longest = max(valid, key=lambda x: x["parsed_km"])
            lowest_soc = min(valid, key=lambda x: x["final_soc_pct"])

            print(f"\n[Detail Rute Ekstrem]")
            print(f"  Terpendek : Rute {shortest['route_id']} "
                  f"({shortest['parsed_km']:.2f} km, SoC akhir {shortest['final_soc_pct']:.2f}%)")
            print(f"  Terpanjang: Rute {longest['route_id']} "
                  f"({longest['parsed_km']:.2f} km, SoC akhir {lowest_soc['final_soc_pct']:.2f}%)")
            print(f"  SoC akhir terendah: Rute {lowest_soc['route_id']} "
                  f"= {lowest_soc['final_soc_pct']:.2f}%")

    print(f"\n[VERDICT] {'SEMUA RUTE LULUS (tidak ada error)' if all_passed else 'ADA ERROR — cek baris di atas'}")

    # Berapa rit sebelum charging per rute (estimasi cepat, hanya 1 bus)
    print(f"\n[Estimasi rit sebelum charging (SoC<=30%), 1 bus mulai 100%]:")
    print(f"  {'Route':<8} {'Km/rit':>7} {'Rit ke-':>8} {'SoC saat charging':>18}")
    print(f"  {'-'*48}")
    for route in routes:
        rid = route["route_id"]
        soc = 100.0
        stops = route["stops"]
        for n in range(1, 25):
            r = model.simulate_trip(rid, stops, soc)
            soc = r.final_soc_pct
            if soc <= 30.0:
                parsed_km = r.total_distance_km
                print(f"  {rid:<8} {parsed_km:>7.2f} {n:>8} {soc:>17.2f}%")
                break
        else:
            print(f"  {rid:<8} {'':>7} {'>=25':>8} {'belum charging':>18}")


if __name__ == "__main__":
    main()
