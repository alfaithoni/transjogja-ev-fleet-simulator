# -*- coding: utf-8 -*-
"""
tests/test_battery.py
---------------------
Unit test untuk simulation/battery.py (T-04).

Jalankan dengan: python -m pytest tests/test_battery.py -v
atau            : python tests/test_battery.py (standalone)

Test cases:
  1. f(SoC) sesuai piecewise formula design.md §1
  2. SoC monoton turun (tidak pernah naik) sepanjang rit tanpa charging
  3. SoC tidak pernah negatif
  4. Jarak nol tidak menghasilkan drain
  5. SoC awal 100%, rit penuh L-1 (16.44 km) → estimasi SoC akhir masuk akal
  6. first_stop_below_threshold mengembalikan halte yang benar
  7. Deteksi breach hard limit (SoC <= 20%)
  8. Factory from_spec membaca bus_spec.json dengan benar
  9. Konsistensi total_energy_kwh vs total_distance_km (cek konsumsi per km)
"""

from __future__ import annotations
import json
import sys
import math
from pathlib import Path

# Supaya bisa import dari project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulation.battery import BatteryDrainModel, DrainResult, StopSoCRecord

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_simple_model(**kwargs) -> BatteryDrainModel:
    defaults = dict(
        battery_capacity_kwh=138.87,
        c_kwh_per_km=138.87 / 150.0,
        k1=0.005,
        k2=0.02,
    )
    defaults.update(kwargs)
    return BatteryDrainModel(**defaults)


def make_uniform_stops(n_stops: int, dist_each_m: float) -> list[dict]:
    """N halte dengan jarak seragam, pertama dist=0."""
    stops = [{"name": f"Halte-{i}", "dist_from_prev_m": 0 if i == 0 else dist_each_m}
             for i in range(n_stops)]
    return stops


def load_route(route_id: str) -> dict:
    with open(ROOT / "data" / "routes.json", encoding="utf-8") as f:
        routes = json.load(f)
    for r in routes:
        if r["route_id"] == route_id:
            return r
    raise KeyError(f"Route {route_id} not found")


# ---------------------------------------------------------------------------
# Test 1: f(SoC) piecewise formula
# ---------------------------------------------------------------------------

def test_f_soc_at_100():
    m = make_simple_model(k1=0.005, k2=0.02)
    assert m.f_soc(100.0) == 1.0, "SoC=100% harus f=1.0"

def test_f_soc_at_70():
    m = make_simple_model(k1=0.005, k2=0.02)
    assert m.f_soc(70.0) == 1.0, "SoC=70% boundary harus f=1.0"

def test_f_soc_at_50():
    m = make_simple_model(k1=0.005, k2=0.02)
    expected = 1.0 + 0.005 * (70.0 - 50.0)  # = 1.1
    assert abs(m.f_soc(50.0) - expected) < 1e-9, f"SoC=50%: expected {expected}, got {m.f_soc(50.0)}"

def test_f_soc_at_30_boundary():
    """SoC tepat 30% — masuk cabang pertama (30<=SoC<70)."""
    m = make_simple_model(k1=0.005, k2=0.02)
    expected = 1.0 + 0.005 * (70.0 - 30.0)  # = 1.2
    assert abs(m.f_soc(30.0) - expected) < 1e-9

def test_f_soc_below_30():
    m = make_simple_model(k1=0.005, k2=0.02)
    soc = 25.0
    expected = 1.0 + 0.005 * 40.0 + 0.02 * (30.0 - 25.0)  # = 1.2 + 0.1 = 1.3
    assert abs(m.f_soc(soc) - expected) < 1e-9, f"SoC=25%: expected {expected}, got {m.f_soc(soc)}"

def test_f_soc_monotonically_increasing_as_soc_drops():
    """f harus monoton naik ketika SoC menurun (drain semakin berat di SoC rendah)."""
    m = make_simple_model()
    soc_levels = [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0]
    f_values = [m.f_soc(s) for s in soc_levels]
    for i in range(len(f_values) - 1):
        assert f_values[i] <= f_values[i + 1], (
            f"f(SoC) harus monoton naik: f({soc_levels[i]})={f_values[i]:.4f} "
            f"> f({soc_levels[i+1]})={f_values[i+1]:.4f}"
        )

# ---------------------------------------------------------------------------
# Test 2 & 3: SoC monoton turun, tidak negatif
# ---------------------------------------------------------------------------

def test_soc_monotonically_decreasing():
    m = make_simple_model()
    stops = make_uniform_stops(20, 500)  # 20 halte, 500m per segmen
    result = m.simulate_trip("TEST", stops, initial_soc_pct=100.0)
    soc_values = [rec.soc_after for rec in result.soc_trace]
    for i in range(len(soc_values) - 1):
        assert soc_values[i] >= soc_values[i + 1], (
            f"SoC harus monoton turun: halte {i} SoC={soc_values[i]:.2f}% > "
            f"halte {i+1} SoC={soc_values[i+1]:.2f}%"
        )

def test_soc_never_negative():
    m = make_simple_model()
    # Buat rit sangat panjang (200 km) yang pasti akan drain habis
    stops = make_uniform_stops(200, 1000)  # 199 segmen × 1 km = 199 km
    result = m.simulate_trip("LONG_ROUTE", stops, initial_soc_pct=100.0)
    for rec in result.soc_trace:
        assert rec.soc_after >= 0.0, (
            f"SoC negatif di halte '{rec.stop_name}': {rec.soc_after:.4f}%"
        )

# ---------------------------------------------------------------------------
# Test 4: Jarak nol tidak menghasilkan drain
# ---------------------------------------------------------------------------

def test_zero_distance_no_drain():
    m = make_simple_model()
    stops = [
        {"name": "Halte A", "dist_from_prev_m": 0},
        {"name": "Halte B", "dist_from_prev_m": 0},  # jarak 0
    ]
    result = m.simulate_trip("TEST", stops, initial_soc_pct=80.0)
    # Semua entry harus SoC sama (tidak ada drain)
    for rec in result.soc_trace:
        assert rec.energy_consumed_kwh == 0.0, (
            f"Jarak 0m harus tidak ada energi dikonsumsi: {rec.energy_consumed_kwh}"
        )
    assert result.final_soc_pct == 80.0

# ---------------------------------------------------------------------------
# Test 5: Rit penuh L-1 (~16.44 km), SoC awal 100%
# ---------------------------------------------------------------------------

def test_l1_full_trip_soc_range():
    """
    Dengan k1=0.005, k2=0.02, c=0.9258 kWh/km, baterai 138.87 kWh:
    - 1 rit L-1 ~16.44 km
    - Estimasi kasar: 16.44 km × 0.9258 kWh/km ≈ 15.22 kWh
    - SoC drop ≈ 15.22/138.87 × 100 ≈ 10.96%
    - SoC akhir harus sekitar 89% (jauh di atas 30%)
    - Bus L-1 dengan 2 bus & headway ±45 menit: setiap bus menyelesaikan
      beberapa rit sebelum charging — sanity check bahwa model masuk akal.
    """
    m = make_simple_model()
    route = load_route("L-1")
    result = m.simulate_trip("L-1", route["stops"], initial_soc_pct=100.0)

    # SoC akhir harus antara 85% dan 95% untuk L-1 (1 rit ~16 km)
    assert 80.0 <= result.final_soc_pct <= 99.0, (
        f"SoC akhir L-1 di luar ekspektasi: {result.final_soc_pct:.2f}%"
    )
    # Total jarak harus mendekati 16.44 km (toleransi ±5% karena pembulatan)
    expected_km = route["route_length_km"]
    assert abs(result.total_distance_km - expected_km) < expected_km * 0.05, (
        f"Total jarak L-1: {result.total_distance_km:.2f} km vs expected {expected_km} km"
    )

def test_l1_how_many_trips_before_30pct():
    """
    Hitung berapa rit L-1 sebelum SoC turun ke threshold 30%.
    Kalibrasi: dengan kondisi as-is (charging setelah SoC <=30%),
    bus harus bisa menyelesaikan lebih dari 1 rit sebelum charging.
    """
    m = make_simple_model()
    route = load_route("L-1")
    soc = 100.0
    trip_count = 0
    max_trips = 20  # upper bound

    while soc > 30.0 and trip_count < max_trips:
        result = m.simulate_trip("L-1", route["stops"], initial_soc_pct=soc)
        soc = result.final_soc_pct
        trip_count += 1
        if result.first_stop_below_threshold:
            break

    assert trip_count >= 2, (
        f"Bus L-1 hanya bisa {trip_count} rit sebelum charging — "
        f"terlalu sedikit, cek parameter c_kwh_per_km / k1 / k2"
    )
    print(f"\n  [INFO] L-1: SoC mencapai <=30% setelah {trip_count} rit "
          f"(SoC akhir = {soc:.2f}%)")

# ---------------------------------------------------------------------------
# Test 6: first_stop_below_threshold
# ---------------------------------------------------------------------------

def test_first_stop_below_threshold_found():
    m = make_simple_model()
    # Buat rute singkat dengan SoC awal 32% — pasti cepat menyentuh 30%
    stops = make_uniform_stops(10, 1000)  # 10 km total
    result = m.simulate_trip("TEST", stops, initial_soc_pct=32.0)
    cp = result.first_stop_below_threshold
    # Seharusnya ada charging point
    assert cp is not None, "Harus ada charging point saat SoC awal 32% dan jarak 10 km"
    assert cp.soc_after <= 30.0

def test_first_stop_below_threshold_not_triggered():
    m = make_simple_model()
    stops = make_uniform_stops(3, 100)  # hanya 200 m total — tidak akan drain banyak
    result = m.simulate_trip("TEST", stops, initial_soc_pct=100.0)
    cp = result.first_stop_below_threshold
    assert cp is None, "Tidak ada charging point untuk rute 200m dengan SoC=100%"

# ---------------------------------------------------------------------------
# Test 7: Breach hard limit detection
# ---------------------------------------------------------------------------

def test_breach_hard_limit_true():
    m = make_simple_model()
    stops = make_uniform_stops(50, 1000)  # 49 km
    result = m.simulate_trip("TEST", stops, initial_soc_pct=20.0)
    # Dengan SoC awal 20% dan 49 km, pasti breach
    assert result.breach_hard_limit, "Harus terdeteksi breach hard limit (SoC<=20%)"

def test_breach_hard_limit_false():
    m = make_simple_model()
    stops = make_uniform_stops(3, 100)  # 200 m
    result = m.simulate_trip("TEST", stops, initial_soc_pct=100.0)
    assert not result.breach_hard_limit, "Rute 200m dari 100% tidak boleh breach hard limit"

# ---------------------------------------------------------------------------
# Test 8: Factory from_spec
# ---------------------------------------------------------------------------

def test_from_spec():
    spec_path = ROOT / "data" / "bus_spec.json"
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    m = BatteryDrainModel.from_spec(spec)
    assert abs(m.battery_capacity_kwh - spec["battery_capacity_kwh_default"]) < 1e-6
    assert abs(m.k1 - spec["drain_model"]["k1"]) < 1e-9
    assert abs(m.k2 - spec["drain_model"]["k2"]) < 1e-9
    assert m.battery_capacity_kwh > 0

# ---------------------------------------------------------------------------
# Test 9: Konsistensi energi vs jarak
# ---------------------------------------------------------------------------

def test_energy_distance_consistency():
    """
    Pada SoC >= 70% (f=1.0), total energi = c_kwh_per_km * total_distance_km.
    """
    c = 0.9258
    m = make_simple_model(c_kwh_per_km=c, k1=0.0, k2=0.0)  # k=0 matikan non-linear
    dist_each = 1000.0
    n = 5
    stops = make_uniform_stops(n, dist_each)
    result = m.simulate_trip("TEST", stops, initial_soc_pct=100.0)

    total_dist_km = result.total_distance_km
    expected_energy = c * total_dist_km
    assert abs(result.total_energy_kwh - expected_energy) < 1e-6, (
        f"Energi tidak konsisten: {result.total_energy_kwh:.6f} vs {expected_energy:.6f} kWh"
    )

# ---------------------------------------------------------------------------
# Test runner (tanpa pytest)
# ---------------------------------------------------------------------------

def run_all_tests():
    tests = [
        test_f_soc_at_100,
        test_f_soc_at_70,
        test_f_soc_at_50,
        test_f_soc_at_30_boundary,
        test_f_soc_below_30,
        test_f_soc_monotonically_increasing_as_soc_drops,
        test_soc_monotonically_decreasing,
        test_soc_never_negative,
        test_zero_distance_no_drain,
        test_l1_full_trip_soc_range,
        test_l1_how_many_trips_before_30pct,
        test_first_stop_below_threshold_found,
        test_first_stop_below_threshold_not_triggered,
        test_breach_hard_limit_true,
        test_breach_hard_limit_false,
        test_from_spec,
        test_energy_distance_consistency,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  [PASS] {test_fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {test_fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {test_fn.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Hasil: {passed} PASS, {failed} FAIL (dari {len(tests)} tests)")
    return failed == 0


if __name__ == "__main__":
    print("=" * 50)
    print("Unit Test: simulation/battery.py (T-04)")
    print("=" * 50)
    success = run_all_tests()
    sys.exit(0 if success else 1)
