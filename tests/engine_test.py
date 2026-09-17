# -*- coding: utf-8 -*-
"""
simulation/engine.py
---------------------
T-07/T-10/T-11/T-12: Simulation Engine — state machine bus dengan pengecekan SoC per-halte.

Mendukung 3 mekanisme charging:
  1. full_opportunity : charging di SPKLU saat SoC<=30% (di tengah rit)
  2. full_depot       : TIDAK charging di tengah rit; charging hanya di pool akhir shift.
                        Jika SoC<=20% saat EN_ROUTE -> state STRANDED (bus berhenti sisa hari).
  3. mix              : opportunity charging (ke SPKLU) saat SoC<=30% + depot charging akhir shift.

State machine tiap bus:
  IDLE_AT_POOL -> EN_ROUTE -> (cek SoC tiap halte)
     -> SoC > threshold            : lanjut EN_ROUTE
     -> SoC <= threshold (oppty)   : TRAVEL_TO_SPKLU -> CHARGING -> rejoin EN_ROUTE
     -> SoC <= 20% (full_depot)    : STRANDED (bus berhenti, tidak rit lagi)
  (akhir waktu operasional)        : RETURN_TO_POOL -> DONE

Kelas utama:
  - BusState      : Enum status bus
  - ChargingEvent : rekam satu sesi charging
  - TripRecord    : rekam satu rit bus
  - BusAgent      : state machine 1 bus
  - HeadwayEvaluator : hitung headway aktual vs target
  - RouteSimulator: orkestrasikan seluruh bus pada 1 rute, 1 skenario
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
import json
import math
import heapq
import itertools
from pathlib import Path

from simulation.battery import BatteryDrainModel, StopSoCRecord


# ---------------------------------------------------------------------------
# Enum & Dataclasses
# ---------------------------------------------------------------------------


class SPKLUResource:
    def __init__(self, spklu_id: str, name: str, n_gun: int):
        self.spklu_id = spklu_id
        self.name = name
        self.n_gun = n_gun
        self.gun_free_times = [0] * n_gun
        
    def request_charge(self, bus_id: str, arrival_time_min: int, charge_duration_min: int) -> tuple[int, int]:
        earliest_free_time = min(self.gun_free_times)
        gun_idx = self.gun_free_times.index(earliest_free_time)
        
        actual_start_time_min = max(arrival_time_min, earliest_free_time)
        queue_wait_min = actual_start_time_min - arrival_time_min
        
        finish_time_min = actual_start_time_min + charge_duration_min
        self.gun_free_times[gun_idx] = finish_time_min
        
        return actual_start_time_min, queue_wait_min

class BusState(Enum):
    IDLE_AT_POOL    = auto()
    EN_ROUTE        = auto()
    TRAVEL_TO_SPKLU = auto()
    CHARGING        = auto()
    RETURN_TO_POOL  = auto()
    DEPOT_CHARGING  = auto()
    STRANDED        = auto()   # full_depot: SoC <= hard_limit di tengah rit
    DONE            = auto()


@dataclass
class ChargingEvent:
    """Satu sesi charging yang terjadi selama simulasi."""
    triggered_at_stop: str
    triggered_at_soc_pct: float
    triggered_at_time_min: int
    travel_to_spklu_min: int
    charging_duration_min: int
    spklu_id: str
    queue_wait_min: int = 0
    is_depot: bool = False          # True jika ini depot charging (akhir shift)

    @property
    def total_downtime_min(self) -> int:
        return self.travel_to_spklu_min + self.charging_duration_min + self.queue_wait_min

    def to_dict(self) -> dict:
        return {
            "triggered_at_stop": self.triggered_at_stop,
            "triggered_at_soc_pct": round(self.triggered_at_soc_pct, 3),
            "triggered_at_time_min": self.triggered_at_time_min,
            "travel_to_spklu_min": self.travel_to_spklu_min,
            "charging_duration_min": self.charging_duration_min,
            "spklu_id": self.spklu_id,
            "queue_wait_min": self.queue_wait_min,
            "total_downtime_min": self.total_downtime_min,
            "is_depot": self.is_depot,
        }


@dataclass
class StrandedEvent:
    """Bus mogok (SoC <= hard limit di full_depot, tidak ada SPKLU mid-day)."""
    at_stop: str
    at_soc_pct: float
    at_time_min: int
    trip_index: int

    def to_dict(self) -> dict:
        return {
            "at_stop": self.at_stop,
            "at_soc_pct": round(self.at_soc_pct, 3),
            "at_time_min": self.at_time_min,
            "trip_index": self.trip_index,
        }


@dataclass
class TripRecord:
    """Satu rit penuh bus (dari titik awal kembali ke titik awal)."""
    trip_index: int
    start_time_min: int
    end_time_min: int
    initial_soc_pct: float
    final_soc_pct: float
    soc_trace: list[dict]
    charging_event: Optional[ChargingEvent] = None   # charging yang terpicu di rit ini
    stranded_event: Optional[StrandedEvent] = None   # bus mogok di rit ini (full_depot)

    def to_dict(self) -> dict:
        d = {
            "trip_index": self.trip_index,
            "start_time_min": self.start_time_min,
            "end_time_min": self.end_time_min,
            "initial_soc_pct": round(self.initial_soc_pct, 3),
            "final_soc_pct": round(self.final_soc_pct, 3),
            "soc_trace": self.soc_trace,
        }
        if self.charging_event:
            d["charging_event"] = self.charging_event.to_dict()
        if self.stranded_event:
            d["stranded_event"] = self.stranded_event.to_dict()
        return d


@dataclass
class BusAgent:
    """
    Satu bus pada koridor tertentu.
    Mengelola state machine, jadwal, dan rekaman rit + charging.
    """
    bus_id: str
    route_id: str
    stops: list[dict]
    model: BatteryDrainModel
    spklu: dict                       # {"id": str, "travel_min": int, "charge_min": int}
    charging_mechanism: str = "full_opportunity"   # full_opportunity | full_depot | mix
    soc_threshold_pct: float = 30.0
    hard_limit_pct: float = 20.0      # SoC di bawah ini -> STRANDED (full_depot)
    speed_kmph: float = 20.0
    charge_to_pct: float = 100.0
    depot_config: dict = field(default_factory=dict)

    # Runtime state
    current_soc: float = field(default=100.0, init=False)
    current_time: int = field(default=0, init=False)
    state: BusState = field(default=BusState.IDLE_AT_POOL, init=False)
    trip_counter: int = field(default=0, init=False)
    is_stranded: bool = field(default=False, init=False)
    stranded_at_time_min: Optional[int] = field(default=None, init=False)

    # Output
    trips: list[TripRecord] = field(default_factory=list, init=False)
    charging_sessions: list[ChargingEvent] = field(default_factory=list, init=False)
    breach_hard_limit_count: int = field(default=0, init=False)
    stranded_events: list[StrandedEvent] = field(default_factory=list, init=False)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _route_km(self) -> float:
        return sum(s.get("dist_from_prev_m", 0) for s in self.stops) / 1000.0

    def _trip_duration_min(self) -> int:
        """Estimasi waktu tempuh 1 rit (menit), pembulatan atas."""
        return math.ceil(self._route_km() / self.speed_kmph * 60)

    def _can_charge_midday(self) -> bool:
        """Apakah mekanisme ini membolehkan opportunity charging di tengah rit?"""
        return self.charging_mechanism in ("full_opportunity", "mix")

    # -----------------------------------------------------------------------
    # Core: jalankan 1 rit dan periksa SoC per-halte
    # -----------------------------------------------------------------------

    def _run_trip(self, op_end_min: int, start_time: int = None) -> dict:
        """
        Jalankan 1 rit. Pada setiap halte, cek apakah SoC <= threshold.
        - full_opportunity/mix: jika ya, catat charging event dan keluar dari loop rit.
        - full_depot: jika SoC <= hard_limit, catat stranded event dan berhenti total.

        Returns TripRecord jika rit selesai, atau None jika waktunya habis.
        """
        if start_time is not None:
            self.current_time = start_time

        if self.current_time >= op_end_min or self.is_stranded:
            self.state = BusState.DONE
            return {"status": "DONE", "trip_record": None}

        trip_start = self.current_time
        self.trip_counter += 1
        trip_idx = self.trip_counter
        initial_soc = self.current_soc

        soc_trace_out: list[dict] = []
        charging_event: Optional[ChargingEvent] = None
        stranded_event: Optional[StrandedEvent] = None
        time_at_stop = trip_start
        current_soc = self.current_soc

        km_per_min = self.speed_kmph / 60.0

        for i, stop in enumerate(self.stops):
            dist_m = float(stop.get("dist_from_prev_m", 0))
            stop_name = stop["name"]

            if dist_m > 0:
                travel_min = math.ceil((dist_m / 1000.0) / km_per_min)
                time_at_stop += travel_min

            # Hitung drain untuk segmen ini
            if dist_m > 0:
                e_kwh, f_val = self.model.energy_for_segment(dist_m, current_soc, self.speed_kmph)
                soc_before = current_soc
                soc_drop = (e_kwh / self.model.battery_capacity_kwh) * 100.0
                current_soc = max(current_soc - soc_drop, 0.0)
            else:
                e_kwh, f_val, soc_before = 0.0, 1.0, current_soc

            soc_trace_out.append({
                "stop_name": stop_name,
                "stop_index": i,
                "time_min": time_at_stop,
                "soc_pct": round(current_soc, 3),
                "energy_consumed_kwh": round(e_kwh, 4),
                "dist_from_prev_m": dist_m,
            })

            # Cek hard limit (selalu dicatat)
            if current_soc <= self.hard_limit_pct and dist_m > 0:
                self.breach_hard_limit_count += 1

                if self.charging_mechanism == "full_depot":
                    # STRANDED: bus berhenti operasi sisa hari
                    stranded_event = StrandedEvent(
                        at_stop=stop_name,
                        at_soc_pct=round(current_soc, 3),
                        at_time_min=time_at_stop,
                        trip_index=trip_idx,
                    )
                    self.stranded_events.append(stranded_event)
                    self.is_stranded = True
                    self.stranded_at_time_min = time_at_stop
                    self.state = BusState.STRANDED
                    self.current_time = time_at_stop
                    self.current_soc = current_soc
                    
                    trip = TripRecord(
                        trip_index=trip_idx,
                        start_time_min=trip_start,
                        end_time_min=time_at_stop,
                        initial_soc_pct=initial_soc,
                        final_soc_pct=current_soc,
                        soc_trace=soc_trace_out,
                        stranded_event=stranded_event,
                    )
                    self.trips.append(trip)
                    return {"status": "STRANDED", "trip_record": trip}

            # [KEY T-07] Pengecekan SoC per-halte — trigger opportunity charging segera
            if (current_soc <= self.soc_threshold_pct
                    and dist_m > 0
                    and self._can_charge_midday()):
                charging_event = ChargingEvent(
                    triggered_at_stop=stop_name,
                    triggered_at_soc_pct=round(current_soc, 3),
                    triggered_at_time_min=time_at_stop,
                    travel_to_spklu_min=self.spklu["travel_min"],
                    charging_duration_min=self.spklu["charge_min"],
                    spklu_id=self.spklu["id"],
                    queue_wait_min=0,
                    is_depot=False,
                )
                # Do not apply charging downtime yet, return request
                self.current_time = time_at_stop
                self.current_soc = current_soc
                
                partial_trip = TripRecord(
                    trip_index=trip_idx,
                    start_time_min=trip_start,
                    end_time_min=time_at_stop,
                    initial_soc_pct=initial_soc,
                    final_soc_pct=current_soc,
                    soc_trace=soc_trace_out,
                    charging_event=charging_event,
                )
                self.trips.append(partial_trip)
                return {"status": "CHARGING_REQUEST", "charging_event": charging_event, "time_min": time_at_stop, "trip_record": partial_trip}

        else:
            # Loop rit selesai penuh (tanpa charging/stranded di tengah)
            self.current_time = time_at_stop

        self.current_soc = current_soc

        trip = TripRecord(
            trip_index=trip_idx,
            start_time_min=trip_start,
            end_time_min=self.current_time,
            initial_soc_pct=initial_soc,
            final_soc_pct=self.current_soc,
            soc_trace=soc_trace_out,
            charging_event=charging_event,
            stranded_event=stranded_event,
        )
        self.trips.append(trip)
        return {"status": "FINISHED", "trip_record": trip}

    # -----------------------------------------------------------------------
    # Public: jalankan bus selama window operasional
    # -----------------------------------------------------------------------

    def run(self, op_end_min: int = 900) -> None:
        """
        Jalankan state machine bus dari menit ke-0 hingga op_end_min.
        op_end_min: akhir jam operasional (default 900 = 20:30).
        """
        self.state = BusState.EN_ROUTE
        while self.current_time < op_end_min and not self.is_stranded:
            trip = self._run_trip(op_end_min)
            if trip is None:
                break
            if self.current_time >= op_end_min:
                break
        
        if not self.is_stranded and self.charging_mechanism == "mix" and self.current_soc < self.charge_to_pct:
            dur = self.depot_config.get("charge_min", 240)
            depot_id = self.depot_config.get("id", "DEPOT-UNKNOWN")
            
            chg_ev = ChargingEvent(
                triggered_at_stop="Pool",
                triggered_at_soc_pct=round(self.current_soc, 3),
                triggered_at_time_min=self.current_time,
                travel_to_spklu_min=0,
                charging_duration_min=dur,
                spklu_id=depot_id,
                queue_wait_min=0,
                is_depot=True,
            )
            self.charging_sessions.append(chg_ev)
            self.current_time += dur
            self.current_soc = self.charge_to_pct
            self.state = BusState.DEPOT_CHARGING
            
            if self.trips and self.trips[-1].charging_event is None:
                self.trips[-1].charging_event = chg_ev
                
        elif not self.is_stranded:
            self.state = BusState.DONE
        else:
            self.state = BusState.STRANDED

    # -----------------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict:
        d = {
            "bus_id": self.bus_id,
            "route_id": self.route_id,
            "total_trips": len(self.trips),
            "total_charging_sessions": len(self.charging_sessions),
            "breach_hard_limit_count": self.breach_hard_limit_count,
            "is_stranded": self.is_stranded,
            "trips": [t.to_dict() for t in self.trips],
        }
        if self.stranded_at_time_min is not None:
            d["stranded_at_time_min"] = self.stranded_at_time_min
        if self.stranded_events:
            d["stranded_events"] = [s.to_dict() for s in self.stranded_events]
        return d


# ---------------------------------------------------------------------------
# T-08: Headway Evaluator
# ---------------------------------------------------------------------------

@dataclass
class HeadwayEvaluator:
    """
    T-08: Hitung headway aktual dari rekaman waktu mulai tiap rit per bus,
    bandingkan vs target headway_dishub_min dari routes.json.

    Headway aktual didefinisikan sebagai selisih waktu mulai rit yang berurutan
    dari semua bus pada koridor yang sama (sorted ascending).

    Penanganan STRANDED:
    - Jika ada bus yang STRANDED, gap yang terjadi setelah waktu stranded pertama
      diberi flag is_post_degradation=True dan dikecualikan dari avg_headway.
    - Jika tidak ada 2 departure pre-degradation, avg_headway = None.
    """

    route_id: str
    target_headway_min: Optional[int]
    tolerance_pct: float = 20.0   # toleransi ±20% dari target

    def compute(self, buses: list[BusAgent]) -> dict:
        # Kumpulkan semua titik keberangkatan + waktu stranded (jika ada)
        departures: list[int] = []
        for bus in buses:
            for trip in bus.trips:
                departures.append(trip.start_time_min)

        departures.sort()

        # Temukan waktu stranded pertama (terkecil) di koridor ini
        stranded_times = [
            bus.stranded_at_time_min
            for bus in buses
            if bus.stranded_at_time_min is not None
        ]
        first_stranded_time: Optional[int] = min(stranded_times) if stranded_times else None
        route_degraded = first_stranded_time is not None

        if len(departures) < 2:
            return {
                "route_id": self.route_id,
                "target_headway_min": self.target_headway_min,
                "n_departures": len(departures),
                "headway_gaps_min": [],
                "avg_min": None,
                "min_min": None,
                "max_min": None,
                "gap_too_wide": 0,
                "gap_too_narrow": 0,
                "tolerance_pct": self.tolerance_pct,
                "route_degraded": route_degraded,
                "first_stranded_time_min": first_stranded_time,
                "note": "Tidak cukup data (< 2 keberangkatan)",
            }

        # Bangun gaps dengan flag is_post_degradation
        gaps_full = []
        for i in range(len(departures) - 1):
            gap_val = departures[i+1] - departures[i]
            if gap_val <= 0:
                continue
            is_post = (
                first_stranded_time is not None
                and departures[i] >= first_stranded_time
            )
            gaps_full.append({"gap_min": gap_val, "is_post_degradation": is_post})

        # Pre-degradation gaps saja untuk metrik headway utama
        pre_gaps = [g["gap_min"] for g in gaps_full if not g["is_post_degradation"]]
        all_gaps = [g["gap_min"] for g in gaps_full]

        avg_gap = sum(pre_gaps) / len(pre_gaps) if pre_gaps else None
        min_gap = min(pre_gaps) if pre_gaps else None
        max_gap = max(pre_gaps) if pre_gaps else None

        gap_too_wide = 0
        gap_too_narrow = 0
        if self.target_headway_min and pre_gaps:
            upper_bound = self.target_headway_min * (1.0 + self.tolerance_pct / 100.0)
            lower_bound = self.target_headway_min * (1.0 - self.tolerance_pct / 100.0)
            gap_too_wide = sum(1 for g in pre_gaps if g > upper_bound)
            gap_too_narrow = sum(1 for g in pre_gaps if g < lower_bound)

        return {
            "route_id": self.route_id,
            "target_headway_min": self.target_headway_min,
            "n_departures": len(departures),
            "headway_gaps_min": all_gaps,
            "avg_min": round(avg_gap, 2) if avg_gap is not None else None,
            "min_min": min_gap,
            "max_min": max_gap,
            "gap_too_wide": gap_too_wide,
            "gap_too_narrow": gap_too_narrow,
            "tolerance_pct": self.tolerance_pct,
            "route_degraded": route_degraded,
            "first_stranded_time_min": first_stranded_time,
            "n_pre_degradation_gaps": len(pre_gaps),
            "n_post_degradation_gaps": len(gaps_full) - len(pre_gaps),
        }


# ---------------------------------------------------------------------------
# RouteSimulator: orkestrasikan semua bus 1 rute
# ---------------------------------------------------------------------------

@dataclass
class RouteSimulator:
    """
    Orkestrasikan simulasi 1 rute dengan 1 skenario charging.
    Input: route dict (dari routes.json), spec (dari bus_spec.json),
           spklu config, scenario config.
    Output: dict yang kompatibel dengan schema.md §5 (field "routes"[i]).
    """
    route: dict
    spec: dict
    spklu: dict            # {\"id\": str, \"travel_min\": int, \"charge_min\": int}
    scenario_id: str = "full_opportunity_as_is"
    charging_mechanism: str = "full_opportunity"
    extra_bus_per_route: int = 0
    op_start_min: int = 0
    op_end_min: int = 900
    speed_kmph: float = 20.0
    stagger_min: int = 0
    depot_config: dict = field(default_factory=dict)

    def run(self) -> dict:
        route_id = self.route["route_id"]
        stops = self.route["stops"]
        base_bus_count = self.route.get("bus_count", 1)
        total_bus_count = base_bus_count + self.extra_bus_per_route
        target_hw = self.route.get("headway_dishub_min")

        model = BatteryDrainModel.from_spec(self.spec)
        soc_threshold = self.spec["soc_thresholds"]["min_to_charge_pct"]
        hard_limit = self.spec["soc_thresholds"].get("hard_limit_pct", 20.0)

        # Mapping rute -> depot berdasarkan rules.md (bisa diekstrak dari spklu_locations jika ideal, hardcode for simplicity as per rules)
        pool_banguntapan_routes = ["1A","1B","2A","2B","12","13","14"]
        pool_key = "pool_banguntapan" if route_id in pool_banguntapan_routes else "pool_gamping"
        my_depot = self.depot_config.get(pool_key, {})

        # Inisialisasi semua bus
        buses: list[BusAgent] = []
        for i in range(total_bus_count):
            is_extra = i >= base_bus_count
            bus = BusAgent(
                bus_id=f"{route_id}-{i+1:02d}{'x' if is_extra else ''}",
                route_id=route_id,
                stops=stops,
                model=model,
                spklu=self.spklu,
                charging_mechanism=self.charging_mechanism,
                soc_threshold_pct=soc_threshold,
                hard_limit_pct=hard_limit,
                speed_kmph=self.speed_kmph,
                charge_to_pct=self.spec["soc_thresholds"]["charge_to_pct"],
                depot_config=my_depot,
            )
            # Stagger: bus ke-i mulai i*stagger_min menit setelah menit ke-0
            if self.stagger_min > 0:
                bus.current_time = i * self.stagger_min
            buses.append(bus)

        # Jalankan semua bus
        for bus in buses:
            bus.run(op_end_min=self.op_end_min)

        # T-08: Headway Evaluator
        hw_eval = HeadwayEvaluator(
            route_id=route_id,
            target_headway_min=target_hw,
        )
        headway_result = hw_eval.compute(buses)

        # Summary
        total_sessions = sum(len(b.charging_sessions) for b in buses)
        total_breach = sum(b.breach_hard_limit_count for b in buses)
        total_trips = sum(len(b.trips) for b in buses)
        total_stranded = sum(1 for b in buses if b.is_stranded)
        route_degraded = headway_result["route_degraded"]

        return {
            "route_id": route_id,
            "scenario_id": self.scenario_id,
            "target_headway_min": target_hw,
            "bus_count": total_bus_count,
            "extra_bus_count": self.extra_bus_per_route,
            "stagger_min_used": self.stagger_min,
            "buses": [b.to_dict() for b in buses],
            "headway_actual": headway_result,
            "route_degraded": route_degraded,
            "summary": {
                "total_trips": total_trips,
                "total_charging_sessions": total_sessions,
                "total_breach_hard_limit": total_breach,
                "total_stranded_buses": total_stranded,
                "route_degraded": route_degraded,
                "soc_zero_incidents": sum(
                    1 for b in buses
                    for t in b.trips
                    for s in t.soc_trace
                    if s["soc_pct"] == 0.0
                ),
            },
        }


@dataclass
class GlobalSimulator:
    routes: list[dict]
    spec: dict
    scenario: dict
    spklu_locations: dict
    op_start_min: int = 0
    op_end_min: int = 900
    speed_kmph: float = 20.0

    def run(self) -> list[dict]:
        from simulation.engine import BusState, BatteryDrainModel, BusAgent, HeadwayEvaluator, ChargingEvent
        
        self.spklu_resources = {}
        for spklu_id, spklu_data in self.spklu_locations.get("spklu_locations", {}).items():
            n_gun = spklu_data.get("n_gun", 2) # Default 2 if not found
            # Override from scenario if exists
            if "spklu_n_gun_override" in self.scenario:
                n_gun = self.scenario["spklu_n_gun_override"].get(spklu_id, n_gun)
            self.spklu_resources[spklu_id] = SPKLUResource(spklu_id, spklu_data["name"], n_gun)
            
        self.depot_resources = {}
        for depot_id, depot_data in self.spklu_locations.get("depot_locations", {}).items():
            self.depot_resources[depot_id] = SPKLUResource(depot_id, depot_data["name"], 999)
            
        self.event_queue = []
        self.counter = itertools.count()
        self.buses = []
        self.route_buses = {}
        
        # Initialize buses
        for route in self.routes:
            route_id = route["route_id"]
            self.route_buses[route_id] = []
            
            # Resolve SPKLU assignment
            assignment = self.scenario.get("spklu_assignment", "single")
            if assignment == "none":
                spklu_dict = {"id": "NONE", "name": "No SPKLU", "travel_min": 0, "charge_min": 0}
            elif assignment == "single":
                spklu_dict = self.scenario["single_spklu"]
            elif assignment == "multi_by_route":
                assignment_map = self.scenario["spklu_assignment_map"]
                spklu_details = self.scenario["spklu_details"]
                spklu_dict = {"id": "SPKLU-ADI", "name": "SPKLU Adisucipto (fallback)", "travel_min": 30, "charge_min": 60}
                for spklu_id, route_list in assignment_map.items():
                    if route_id in route_list:
                        spklu_dict = {"id": spklu_id, "name": spklu_details[spklu_id]["name"], "travel_min": spklu_details[spklu_id]["travel_min"], "charge_min": spklu_details[spklu_id]["charge_min"]}
                        break
                        
            pool_banguntapan_routes = ["1A","1B","2A","2B","12","13","14"]
            pool_key = "pool_banguntapan" if route_id in pool_banguntapan_routes else "pool_gamping"
            my_depot = self.scenario.get("depot_config", {}).get(pool_key, {})
            
            base_bus_count = route.get("bus_count", 1)
            extra_bus = self.scenario.get("extra_bus_per_route", 0)
            total_bus_count = base_bus_count + extra_bus
            
            target_hw = route.get("headway_dishub_min")
            stagger = 0
            if target_hw and total_bus_count > 1:
                stagger = round(target_hw / total_bus_count)
                
            model = BatteryDrainModel.from_spec(self.spec)
            soc_threshold = self.spec["soc_thresholds"]["min_to_charge_pct"]
            hard_limit = self.spec["soc_thresholds"].get("hard_limit_pct", 20.0)
            
            for i in range(total_bus_count):
                is_extra = i >= base_bus_count
                bus = BusAgent(
                    bus_id=f"{route_id}-{i+1:02d}{'x' if is_extra else ''}",
                    route_id=route_id,
                    stops=route["stops"],
                    model=model,
                    spklu=spklu_dict,
                    charging_mechanism=self.scenario["charging_mechanism"],
                    soc_threshold_pct=soc_threshold,
                    hard_limit_pct=hard_limit,
                    speed_kmph=self.speed_kmph,
                    charge_to_pct=self.spec["soc_thresholds"]["charge_to_pct"],
                    depot_config=my_depot,
                )
                start_time = i * stagger
                bus.stagger_min = stagger # store for reference
                self.buses.append(bus)
                self.route_buses[route_id].append(bus)
                
                heapq.heappush(self.event_queue, (start_time, next(self.counter), "START_TRIP", bus, None))
                
        # Run Discrete Event Simulation
        while self.event_queue:
            time_min, _, event_type, bus, data = heapq.heappop(self.event_queue)
            
            if event_type == "START_TRIP":
                res = bus._run_trip(self.op_end_min, start_time=time_min)
                status = res["status"]
                
                if status == "CHARGING_REQUEST":
                    chg_ev = res["charging_event"]
                    arrival_time = time_min + chg_ev.travel_to_spklu_min
                    heapq.heappush(self.event_queue, (arrival_time, next(self.counter), "ARRIVE_AT_SPKLU", bus, chg_ev))
                    
                elif status == "FINISHED":
                    heapq.heappush(self.event_queue, (res["trip_record"].end_time_min, next(self.counter), "START_TRIP", bus, None))
                    
                elif status == "DONE":
                    # Shift over, do depot charging if mix
                    if bus.charging_mechanism == "mix" and bus.current_soc < bus.charge_to_pct:
                        dur = bus.depot_config.get("charge_min", 240)
                        depot_id = bus.depot_config.get("id", "DEPOT-UNKNOWN")
                        
                        chg_ev = ChargingEvent(
                            triggered_at_stop="Pool",
                            triggered_at_soc_pct=round(bus.current_soc, 3),
                            triggered_at_time_min=time_min,
                            travel_to_spklu_min=0,
                            charging_duration_min=dur,
                            spklu_id=depot_id,
                            queue_wait_min=0,
                            is_depot=True,
                        )
                        bus.charging_sessions.append(chg_ev)
                        if bus.trips and bus.trips[-1].charging_event is None:
                            bus.trips[-1].charging_event = chg_ev
                            
                        bus.current_time = time_min + dur
                        bus.current_soc = bus.charge_to_pct
                        bus.state = BusState.DEPOT_CHARGING
                    
            elif event_type == "ARRIVE_AT_SPKLU":
                chg_ev = data
                spklu = self.spklu_resources.get(chg_ev.spklu_id)
                if not spklu:
                    # fallback if SPKLU not found
                    spklu = SPKLUResource(chg_ev.spklu_id, "Fallback", 999)
                    self.spklu_resources[chg_ev.spklu_id] = spklu
                    
                actual_start, wait_time = spklu.request_charge(bus.bus_id, time_min, chg_ev.charging_duration_min)
                
                # Apply wait time
                chg_ev.queue_wait_min = wait_time
                bus.charging_sessions.append(chg_ev)
                bus.current_soc = bus.charge_to_pct
                
                # Return to pool/route
                return_time = actual_start + chg_ev.charging_duration_min
                bus.current_time = return_time
                heapq.heappush(self.event_queue, (return_time, next(self.counter), "START_TRIP", bus, None))
                
        # Build Results
        results = []
        for route in self.routes:
            route_id = route["route_id"]
            buses = self.route_buses[route_id]
            target_hw = route.get("headway_dishub_min")
            
            hw_eval = HeadwayEvaluator(route_id=route_id, target_headway_min=target_hw)
            headway_result = hw_eval.compute(buses)
            
            total_sessions = sum(len(b.charging_sessions) for b in buses)
            total_breach = sum(b.breach_hard_limit_count for b in buses)
            total_trips = sum(len(b.trips) for b in buses)
            total_stranded = sum(1 for b in buses if b.is_stranded)
            route_degraded = headway_result["route_degraded"]
            
            stagger = buses[0].stagger_min if buses else 0
            
            results.append({
                "route_id": route_id,
                "scenario_id": self.scenario["scenario_id"],
                "target_headway_min": target_hw,
                "bus_count": len(buses),
                "extra_bus_count": self.scenario.get("extra_bus_per_route", 0),
                "stagger_min_used": stagger,
                "buses": [b.to_dict() for b in buses],
                "headway_actual": headway_result,
                "route_degraded": route_degraded,
                "summary": {
                    "total_trips": total_trips,
                    "total_charging_sessions": total_sessions,
                    "total_queue_wait_min": sum(c.queue_wait_min for b in buses for c in b.charging_sessions),
                    "total_breach_hard_limit": total_breach,
                    "total_stranded_buses": total_stranded,
                    "route_degraded": route_degraded,
                    "soc_zero_incidents": sum(1 for b in buses for t in b.trips for s in t.soc_trace if s["soc_pct"] == 0.0),
                },
            })
        return results
