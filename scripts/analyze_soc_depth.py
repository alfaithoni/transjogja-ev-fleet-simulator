# -*- coding: utf-8 -*-
"""
scripts/analyze_soc_depth.py
-----------------------------
Poin 4: Hitung min SoC yang benar-benar tercapai di dalam soc_trace tiap rit
        untuk 20 rute (bukan SoC di akhir rit saja).
Poin 5: Analisis perilaku floor/clamp dan f(SoC) saat SoC hipotetis <= 0%.

Untuk rute 5B, 8, 9, 15 yang sebelumnya menunjukkan SoC "0%" atau sangat
rendah saat charging: verifikasi apakah soc_trace sempat menyentuh negatif
sebelum clamp, dan berapa margin ke hard limit (20%).
"""

from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulation.battery import BatteryDrainModel

# ---------------------------------------------------------------------------
# Poin 5 - Analisis f(SoC) saat SoC di bawah 0% (hipotetis tanpa clamp)
# ---------------------------------------------------------------------------

def analyze_floor_behavior():
    """
    Jika clamp tidak ada, f(SoC) dengan SoC < 0% akan terus meningkat
    karena cabang 'soc < 30' menggunakan (30 - SoC) yang semakin besar.
    Ini bisa menyebabkan efek bola salju: drain semakin cepat -> SoC semakin
    negatif -> f semakin besar -> drain lebih cepat lagi.

    Dokumentasikan perilaku ini dan konfirmasi bahwa clamp di 0% sudah ada.
    """
    m = BatteryDrainModel(k1=0.005, k2=0.020)
    soc_test = [10, 5, 1, 0, -5, -10, -20]
    print("[Poin 5] Analisis f(SoC) di rentang kritis dan hipotetis:")
    print(f"  {'SoC (%)':>10}  {'f(SoC)':>8}  {'Catatan'}")
    print(f"  {'-'*55}")
    for s in soc_test:
        f = m.f_soc(s)
        note = ""
        if s == 20:
            note = "<-- hard limit (AC mati)"
        elif s == 0:
            note = "<-- floor clamp titik ini"
        elif s < 0:
            note = "HIPOTETIS (tidak bisa terjadi karena clamp di 0%)"
        print(f"  {s:>10}  {f:>8.4f}  {note}")

    print()
    print("  [KESIMPULAN Poin 5]")
    print("  battery.py baris 230: current_soc = max(current_soc - soc_drop, 0.0)")
    print("  -> Clamp di 0.0% SUDAH ADA. SoC tidak bisa negatif di soc_trace.")
    print()
    print("  [DAMPAK f(SoC) saat SoC=0%]:")
    f_at_0 = m.f_soc(0.0)
    print(f"  f(0%) = {f_at_0:.4f} = 1.0 + {m.k1}*40 + {m.k2}*30 = {1.0 + m.k1*40 + m.k2*30:.4f}")
    print("  -> Ketika SoC sudah 0% dan bus masih bergerak (darurat/bug),")
    print("     energi tetap dihitung tapi SoC tidak turun (sudah di floor).")
    print("  -> Di simulasi normal, ini TIDAK AKAN TERJADI karena bus harus")
    print("     sudah charging atau berhenti sebelum SoC mencapai 0%.")
    print()
    print("  [CONCERN]: Test T-06 sebelumnya (sebelum fix data 3A/5B) melaporkan")
    print("  'SoC saat charging = 0.00%' untuk Rute 5B bukan karena SoC negatif,")
    print("  tapi karena threshold 30% terlewat antar-rit sehingga seluruh")
    print("  cadangan terkuras habis. Clamp bekerja benar, tapi ini tetap")
    print("  menunjukkan masalah di Charging Decision Module (Fase 2).")


# ---------------------------------------------------------------------------
# Poin 4 - Min SoC di dalam soc_trace, bukan akhir rit saja
# ---------------------------------------------------------------------------

def analyze_min_soc_per_trip():
    with open(ROOT / "data" / "routes.json", encoding="utf-8") as f:
        routes = json.load(f)
    with open(ROOT / "data" / "bus_spec.json", encoding="utf-8") as f:
        spec = json.load(f)

    model = BatteryDrainModel.from_spec(spec)

    highlight_routes = {"5B", "8", "9", "15"}

    print("[Poin 4] Min SoC di dalam soc_trace per rit (bukan hanya akhir rit)")
    print("         Simulasi hingga SoC akhir rit <= 30% atau mencapai rit ke-20")
    print()

    all_rows = []

    for route in routes:
        rid = route["route_id"]
        stops = route["stops"]
        soc = 100.0
        rit = 0
        found_threshold = False

        while soc > 0.0 and rit < 20:
            result = model.simulate_trip(rid, stops, initial_soc_pct=soc)
            rit += 1

            # Min SoC dari soc_trace (per-halte, bukan akhir rit)
            min_soc_in_trace = min(rec.soc_after for rec in result.soc_trace)
            # Halte di mana min terjadi
            min_stop = next(
                rec.stop_name for rec in result.soc_trace
                if rec.soc_after == min_soc_in_trace
            )
            soc = result.final_soc_pct

            # Apakah ada halte yang soc_after < 0 sebelum clamp?
            # Kita hitung "raw drop" untuk segmen terakhir saat SoC terendah
            # = apakah ada segmen yang raw_soc_drop > soc_before_segment?
            potential_negative = False
            for rec in result.soc_trace:
                raw_drop = (rec.energy_consumed_kwh / model.battery_capacity_kwh) * 100
                if rec.soc_before > 0 and rec.soc_before - raw_drop < -0.01:
                    potential_negative = True

            row = {
                "route_id": rid,
                "rit": rit,
                "min_soc_in_trace": round(min_soc_in_trace, 3),
                "min_at_stop": min_stop,
                "soc_after_trip": round(soc, 3),
                "breach_hard_limit": min_soc_in_trace <= 20.0,
                "soc_would_be_negative_without_clamp": potential_negative,
            }
            all_rows.append(row)

            if soc <= 30.0:
                found_threshold = True
                break

    # Print tabel: focus rute kritis dulu
    print(f"  {'Rute':<6} {'Rit':>4} {'Min SoC trace':>14} {'SoC akhir rit':>14} "
          f"{'Breach?':>8} {'Would-neg?':>11}  {'Min di halte'}")
    print(f"  {'-'*90}")

    critical = [r for r in all_rows if r["route_id"] in highlight_routes]
    others = [r for r in all_rows if r["route_id"] not in highlight_routes]

    for row in critical:
        breach = "YES(!)" if row["breach_hard_limit"] else "no"
        neg = "YES(!)" if row["soc_would_be_negative_without_clamp"] else "no"
        flag = " <<< KRITIS" if row["breach_hard_limit"] else ""
        print(f"  {row['route_id']:<6} {row['rit']:>4} {row['min_soc_in_trace']:>13.3f}% "
              f"{row['soc_after_trip']:>13.3f}% {breach:>8} {neg:>11}  "
              f"{row['min_at_stop'][:30]}{flag}")

    print(f"  {'-'*90}")
    print(f"  --- 16 rute lainnya ---")
    for row in others:
        breach = "YES(!)" if row["breach_hard_limit"] else "no"
        neg = "YES(!)" if row["soc_would_be_negative_without_clamp"] else "no"
        flag = " <<< KRITIS" if row["breach_hard_limit"] else ""
        print(f"  {row['route_id']:<6} {row['rit']:>4} {row['min_soc_in_trace']:>13.3f}% "
              f"{row['soc_after_trip']:>13.3f}% {breach:>8} {neg:>11}  "
              f"{row['min_at_stop'][:30]}{flag}")

    # Summary
    total_breach = sum(1 for r in all_rows if r["breach_hard_limit"])
    total_neg = sum(1 for r in all_rows if r["soc_would_be_negative_without_clamp"])
    print(f"\n  [RINGKASAN Poin 4]")
    print(f"  Rute dengan min SoC <= 20% (breach hard limit): {total_breach}")
    print(f"  Rute yang TANPA clamp SoC bisa negatif       : {total_neg}")
    print()
    print("  [INTERPRETASI]:")
    print("  - 'Min SoC trace' adalah titik terendah SoC di tengah rit, per-halte.")
    print("  - 'Would-neg' = True jika suatu segmen tunggal memiliki raw energy drop")
    print("    > soc_before, artinya TANPA clamp SoC akan negatif di halte itu.")
    print("  - Ini TIDAK mempengaruhi hasil sekarang (clamp ada), tapi menandai")
    print("    rute yang drain-nya sangat dalam di segmen tertentu -> prioritas")
    print("    untuk dimonitor di Charging Decision Module (Fase 2).")

    return all_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 65)
    print("Analisis SoC Mendalam — Poin 4 & 5")
    print("=" * 65)

    print()
    analyze_floor_behavior()

    print("=" * 65)
    print()
    all_rows = analyze_min_soc_per_trip()
    print()
    print("=" * 65)
    print("[SELESAI] Jalankan T-06 ulang untuk tabel lengkap semua rit.")


if __name__ == "__main__":
    main()
