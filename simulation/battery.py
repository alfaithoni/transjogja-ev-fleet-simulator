# -*- coding: utf-8 -*-
"""
simulation/battery.py
---------------------
Model drain baterai non-linear untuk bus listrik TransJogja.

Implementasi sesuai design.md §1 dan schema.md §2.
Semua parameter dikalibrasi terhadap baseline Rute L-1 (task.md T-05).

Satuan (rules.md §6):
  - Jarak  : meter (m)
  - Waktu  : menit sejak 05:30 = menit ke-0
  - Energi : kWh
  - SoC    : persen (0.0 – 100.0)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class StopSoCRecord(NamedTuple):
    """SoC trace untuk satu halte (dipakai di simulation_result.json)."""
    stop_name: str
    dist_from_prev_m: float   # meter
    energy_consumed_kwh: float
    soc_before: float         # % sebelum segmen ini dikurangi
    soc_after: float          # % setelah segmen ini dikurangi
    f_soc: float              # nilai faktor koreksi f(SoC) yang dipakai


@dataclass
class DrainResult:
    """Hasil simulasi drain 1 rit (trip) tanpa charging."""
    route_id: str
    initial_soc_pct: float
    soc_trace: list[StopSoCRecord] = field(default_factory=list)

    # --- derived properties ---
    @property
    def final_soc_pct(self) -> float:
        if not self.soc_trace:
            return self.initial_soc_pct
        return self.soc_trace[-1].soc_after

    @property
    def total_energy_kwh(self) -> float:
        return sum(r.energy_consumed_kwh for r in self.soc_trace)

    @property
    def total_distance_km(self) -> float:
        return sum(r.dist_from_prev_m for r in self.soc_trace) / 1000.0

    @property
    def min_soc_pct(self) -> float:
        if not self.soc_trace:
            return self.initial_soc_pct
        return min(r.soc_after for r in self.soc_trace)

    @property
    def breach_hard_limit(self) -> bool:
        """True jika SoC menyentuh atau melewati hard limit (20%) selama rit."""
        return self.min_soc_pct <= 20.0

    @property
    def first_stop_below_threshold(self) -> StopSoCRecord | None:
        """
        Halte pertama saat SoC_after <= 30% (ambang charging).
        None jika tidak pernah mencapai threshold.
        """
        for rec in self.soc_trace:
            if rec.soc_after <= 30.0:
                return rec
        return None


# ---------------------------------------------------------------------------
# Core drain model
# ---------------------------------------------------------------------------

class BatteryDrainModel:
    """
    Model drain baterai non-linear sesuai design.md §1.

    Rumus:
        E_base(i)   = c_kwh_per_km * dist_m_i / 1000
        f(SoC):
            >= 70%  -> 1.0
            30-70%  -> 1.0 + k1 * (70 - SoC)
            < 30%   -> 1.0 + k1 * 40 + k2 * (30 - SoC)
        E_actual(i) = E_base(i) * f(SoC_i)
        SoC_i       = SoC_(i-1) - (E_actual(i) / battery_capacity_kwh) * 100

    Parameters
    ----------
    battery_capacity_kwh : float
        Kapasitas baterai dalam kWh. Default = 138.87 (titik tengah spek PT MAB).
    c_kwh_per_km : float
        Konsumsi dasar kWh per km. Default dikalibrasi dari capacity/150 km.
    k1 : float
        Faktor koreksi non-linear untuk rentang SoC 30–70%.
    k2 : float
        Faktor koreksi non-linear untuk SoC < 30% (kondisi darurat).
    """

    DEFAULT_BATTERY_KWH = 138.87
    DEFAULT_C_KWH_PER_KM = 138.87 / 150.0   # = 0.9258 kWh/km
    DEFAULT_K1 = 0.005
    DEFAULT_K2 = 0.02

    def __init__(
        self,
        battery_capacity_kwh: float = DEFAULT_BATTERY_KWH,
        c_kwh_per_km: float = DEFAULT_C_KWH_PER_KM,
        k1: float = DEFAULT_K1,
        k2: float = DEFAULT_K2,
    ):
        if battery_capacity_kwh <= 0:
            raise ValueError("battery_capacity_kwh harus > 0")
        if c_kwh_per_km <= 0:
            raise ValueError("c_kwh_per_km harus > 0")
        if k1 < 0 or k2 < 0:
            raise ValueError("k1 dan k2 harus >= 0")

        self.battery_capacity_kwh = battery_capacity_kwh
        self.c_kwh_per_km = c_kwh_per_km
        self.k1 = k1
        self.k2 = k2

    # ------------------------------------------------------------------
    # Mamarikas Equation 1 (Fase 6)
    # ------------------------------------------------------------------

    def mamarikas_ec(self, v: float) -> float:
        """
        Hitung konsumsi energi (Wh/km) berbasis kecepatan rata-rata (v)
        menggunakan Persamaan 1 dari Mamarikas et al. (2025).
        EC(v) = (a*v^2 + b*v + c + d/v) / (e*v^2 + f*v + g)
        """
        v = max(v, 5.0)  # Pengaman matematis (v_min=5 km/jam)
        
        a = 0.0185
        b = 1.40e-8
        c = 6.91
        d = 1.54
        e = 9.64e-6
        f_coef = 2.79e-4
        g = 1.15e-4
        
        numerator = a*(v**2) + b*v + c + d/v
        denominator = e*(v**2) + f_coef*v + g
        return numerator / denominator

    # ------------------------------------------------------------------
    # Per-segment energy calculation
    # ------------------------------------------------------------------

    def energy_for_segment(self, dist_m: float, soc_pct: float, speed_kmph: float) -> tuple[float, float]:
        """
        Hitung energi yang dikonsumsi untuk 1 segmen (halte ke halte berikutnya).

        Parameters
        ----------
        dist_m     : float  — jarak segmen dalam meter
        soc_pct    : float  — SoC saat memasuki segmen (%) (tidak terpakai lagi di Persamaan 1, dipertahankan untuk signature compatibility)
        speed_kmph : float  — Kecepatan rata-rata segmen (km/jam)

        Returns
        -------
        (energy_kwh, ec_wh_km)
            energy_kwh : energi aktual yang dikonsumsi (kWh)
            ec_wh_km   : nilai EC(v) dalam Wh/km yang dipakai (sebagai pengganti nilai f(SoC) untuk traceability)
        """
        dist_km = dist_m / 1000.0
        ec_wh_km = self.mamarikas_ec(speed_kmph)
        e_actual = (ec_wh_km / 1000.0) * dist_km
        return e_actual, ec_wh_km

    # ------------------------------------------------------------------
    # Full-trip drain simulation
    # ------------------------------------------------------------------

    def simulate_trip(
        self,
        route_id: str,
        stops: list[dict],
        initial_soc_pct: float = 100.0,
        stop_on_hard_limit: bool = False,
        speed_kmph: float = 20.0,
    ) -> DrainResult:
        """
        Simulasi drain baterai untuk satu rit penuh.

        Parameters
        ----------
        route_id        : str   — ID rute (mis. "L-1")
        stops           : list  — daftar dict {"name": str, "dist_from_prev_m": float}
                                   sesuai format routes.json
        initial_soc_pct : float — SoC awal (%), default 100%
        stop_on_hard_limit : bool
            Jika True, simulasi berhenti saat SoC mencapai hard limit (<=20%).
            Jika False, drain tetap dihitung (SoC bisa negatif — untuk analisis saja).

        Returns
        -------
        DrainResult dengan soc_trace lengkap per halte.
        """
        if not (0.0 <= initial_soc_pct <= 100.0):
            raise ValueError(f"initial_soc_pct harus 0–100, dapat: {initial_soc_pct}")

        result = DrainResult(route_id=route_id, initial_soc_pct=initial_soc_pct)
        current_soc = initial_soc_pct

        for stop in stops:
            name = stop["name"]
            dist_m = float(stop.get("dist_from_prev_m", 0))

            if dist_m == 0:
                # Halte pertama (titik awal) — catat SoC tanpa drain
                result.soc_trace.append(StopSoCRecord(
                    stop_name=name,
                    dist_from_prev_m=0.0,
                    energy_consumed_kwh=0.0,
                    soc_before=current_soc,
                    soc_after=current_soc,
                    f_soc=1.0,
                ))
                continue

            e_kwh, f_val = self.energy_for_segment(dist_m, current_soc, speed_kmph)
            soc_before = current_soc
            soc_drop = (e_kwh / self.battery_capacity_kwh) * 100.0
            current_soc = max(current_soc - soc_drop, 0.0)  # clamp ke 0, jangan negatif

            result.soc_trace.append(StopSoCRecord(
                stop_name=name,
                dist_from_prev_m=dist_m,
                energy_consumed_kwh=e_kwh,
                soc_before=soc_before,
                soc_after=current_soc,
                f_soc=f_val,
            ))

            if stop_on_hard_limit and current_soc <= 20.0:
                break  # stop simulasi di titik ini

        return result

    # ------------------------------------------------------------------
    # Klasifikasi segmen kritis
    # ------------------------------------------------------------------

    def charging_points(
        self, drain_result: DrainResult, threshold_pct: float = 30.0
    ) -> list[StopSoCRecord]:
        """
        Kembalikan daftar halte di mana SoC_after pertama kali <= threshold.
        Berguna untuk menentukan di mana bus harus mulai perjalanan ke SPKLU.
        """
        triggered = []
        triggered_once = False
        for rec in drain_result.soc_trace:
            if rec.soc_after <= threshold_pct and not triggered_once:
                triggered.append(rec)
                triggered_once = True
        return triggered

    # ------------------------------------------------------------------
    # Factory dari bus_spec.json
    # ------------------------------------------------------------------

    @classmethod
    def from_spec(cls, spec: dict) -> "BatteryDrainModel":
        """
        Buat BatteryDrainModel dari dict bus_spec.json.

        Parameters
        ----------
        spec : dict — isi bus_spec.json (atau subset-nya)
        """
        dm = spec.get("drain_model", {})
        return cls(
            battery_capacity_kwh=spec.get(
                "battery_capacity_kwh_default", cls.DEFAULT_BATTERY_KWH
            ),
            c_kwh_per_km=dm.get("c_kwh_per_km", cls.DEFAULT_C_KWH_PER_KM),
            k1=dm.get("k1", cls.DEFAULT_K1),
            k2=dm.get("k2", cls.DEFAULT_K2),
        )
