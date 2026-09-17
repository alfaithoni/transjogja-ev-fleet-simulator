# -*- coding: utf-8 -*-
"""
optimize/decision_space.py
---------------------------
Encoding untuk optimasi lokasi + kapasitas + assignment + algoritma charging SPKLU.

Ruang keputusan (sesuai rencana kerja yang disepakati):
  1. active[loc]        : aktif/tidaknya tiap 1 dari 6 kandidat lokasi SPKLU
  2. n_gun[loc]          : jumlah gun/charger di tiap lokasi aktif
  3. assignment[route]   : rute di-assign ke SATU lokasi aktif yang reachable
  4. algo                : algoritma charging GLOBAL ("static" | "dynamic_v1" | "dynamic_v2")

PENTING (baca sebelum menjalankan optimizer):
- `simulation/engine.py` saat ini memberi 1 nilai travel_min/charge_min TETAP per
  SPKLU-id (lihat data/spklu_locations.json), BUKAN per kombinasi rute x lokasi.
  `data/route_spklu_distance_matrix.json` yang sudah dibangun dipakai skeleton ini
  HANYA untuk menentukan REACHABILITY (rute mana boleh di-assign ke lokasi mana),
  bukan untuk override travel_min per-rute -- itu butuh ubah simulation/engine.py
  (BusAgent/compute_charge_duration) yang secara sengaja BELUM disentuh di tahap
  persiapan data sebelumnya. Kalau nanti mau akurasi lebih tinggi (travel_min
  spesifik per rute), itu langkah terpisah -- tandai TODO di bawah.
- `n_gun` dibatasi ke rentang wajar (default 1-30) berdasarkan histori S17b-S35
  (kisaran 2-10 per lokasi, total 20-26 gun) supaya GA/Bayesian tidak buang waktu
  di ruang yang jelas tidak realistis. Sesuaikan MIN_GUN/MAX_GUN kalau perlu.
"""

from __future__ import annotations
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CANDIDATE_LOCATIONS = [
    "SPKLU-ADI", "SPKLU-NGB", "SPKLU-CON",
    "SPKLU-KRI", "SPKLU-JOM", "SPKLU-GIW",
]

MIN_GUN = 1
MAX_GUN = 30

# charging_mechanism selalu "full_opportunity" (konsisten dgn S17b-S35);
# "algo" di sini spesifik ke on/off dynamic_charging + versinya.
ALGO_CHOICES = ["static", "dynamic_v1", "dynamic_v2"]

DEFAULT_DYNAMIC_PARAMS = {
    "peak_target_soc_pct": 80.0,
    "offpeak_target_soc_pct": 100.0,
    "charge_rate_kw": 97.209,  # dikalibrasi dari data/spklu_locations.json (SPKLU-ADI)
}


@dataclass
class DecisionSpace:
    routes: list          # data/routes.json (list of route dict)
    spklu_static: dict     # data/spklu_locations.json (untuk nama & fallback travel_min/charge_min)
    distance_matrix: dict  # data/route_spklu_distance_matrix.json

    route_ids: list = field(init=False)
    reachable: dict = field(init=False)  # route_id -> list[loc_id] yang reachable

    def __post_init__(self):
        self.route_ids = [r["route_id"] for r in self.routes]
        self.reachable = {}
        for rid in self.route_ids:
            entry = self.distance_matrix.get(rid, {})
            opts = [loc for loc in CANDIDATE_LOCATIONS if entry.get(loc)]
            if not opts:
                # Tidak ada kandidat yang reachable -> fallback ke SEMUA kandidat
                # (jangan biarkan rute tanpa opsi valid; tandai supaya kelihatan
                # saat debug, karena ini kondisi anomali data yang perlu dicek manual)
                print(f"[decision_space] WARNING: rute {rid} tidak reachable oleh "
                      f"kandidat manapun di distance matrix -- fallback ke semua kandidat")
                opts = list(CANDIDATE_LOCATIONS)
            self.reachable[rid] = opts

    @classmethod
    def from_files(cls, routes_path: str, spklu_locations_path: str, distance_matrix_path: str) -> "DecisionSpace":
        routes = json.loads(Path(routes_path).read_text(encoding="utf-8"))
        spklu_static = json.loads(Path(spklu_locations_path).read_text(encoding="utf-8"))
        distance_matrix = json.loads(Path(distance_matrix_path).read_text(encoding="utf-8"))
        return cls(routes=routes, spklu_static=spklu_static, distance_matrix=distance_matrix)

    # -----------------------------------------------------------------
    # Chromosome: dict mudah dibaca/di-serialize (bukan array bit) supaya
    # GA custom & Optuna dua-duanya bisa pakai representasi yang sama.
    # {
    #   "active": {"SPKLU-ADI": True, ...},
    #   "n_gun": {"SPKLU-ADI": 3, ...},        # hanya relevan kalau active
    #   "assignment": {"1A": "SPKLU-ADI", ...},
    #   "algo": "dynamic_v1",
    # }
    # -----------------------------------------------------------------

    def random_chromosome(self, rng: random.Random) -> dict:
        active = {loc: rng.random() < 0.6 for loc in CANDIDATE_LOCATIONS}
        # pastikan minimal 2 lokasi aktif (0-1 lokasi jelas tidak masuk akal
        # untuk 20 rute x ~144 bus, buang-buang evaluasi kalau dibiarkan)
        while sum(active.values()) < 2:
            active[rng.choice(CANDIDATE_LOCATIONS)] = True

        n_gun = {loc: rng.randint(MIN_GUN, MAX_GUN) for loc in CANDIDATE_LOCATIONS}

        assignment = {}
        for rid in self.route_ids:
            choices = [loc for loc in self.reachable[rid] if active[loc]]
            if not choices:
                choices = self.reachable[rid]  # repair akan aktifkan salah satu di bawah
            assignment[rid] = rng.choice(choices)

        chromo = {
            "active": active,
            "n_gun": n_gun,
            "assignment": assignment,
            "algo": rng.choice(ALGO_CHOICES),
        }
        return self.repair(chromo, rng)

    def repair(self, chromo: dict, rng: Optional[random.Random] = None) -> dict:
        """Pastikan tiap rute di-assign ke lokasi yang (a) reachable dan (b) aktif.
        Kalau tidak ada lokasi aktif yang reachable untuk suatu rute, aktifkan
        salah satu kandidat reachable untuk rute itu (paksa, supaya tidak ada
        rute yatim tanpa opsi charging)."""
        rng = rng or random.Random()
        active = dict(chromo["active"])
        assignment = dict(chromo["assignment"])

        for rid in self.route_ids:
            reach = self.reachable[rid]
            cur = assignment.get(rid)
            valid_now = [loc for loc in reach if active.get(loc)]
            if cur not in valid_now:
                if valid_now:
                    assignment[rid] = rng.choice(valid_now)
                else:
                    forced = rng.choice(reach)
                    active[forced] = True
                    assignment[rid] = forced

        if sum(active.values()) < 2:
            # jaga minimal 2 lokasi aktif setelah repair juga
            inactive = [loc for loc in CANDIDATE_LOCATIONS if not active[loc]]
            if inactive:
                active[rng.choice(inactive)] = True

        chromo["active"] = active
        chromo["assignment"] = assignment
        return chromo

    def total_gun(self, chromo: dict) -> int:
        return sum(chromo["n_gun"][loc] for loc in CANDIDATE_LOCATIONS if chromo["active"][loc])

    def n_active_locations(self, chromo: dict) -> int:
        return sum(1 for loc in CANDIDATE_LOCATIONS if chromo["active"][loc])

    # -----------------------------------------------------------------
    # Decode -> scenario dict yang kompatibel dengan GlobalSimulator
    # (format sama seperti data/scenarios/s17b_probabilistic_4loc_prop.json)
    # -----------------------------------------------------------------

    def decode_to_scenario(self, chromo: dict, scenario_id: str = "ga_candidate") -> dict:
        active_locs = [loc for loc in CANDIDATE_LOCATIONS if chromo["active"][loc]]

        assignment_map = {loc: [] for loc in active_locs}
        for rid, loc in chromo["assignment"].items():
            assignment_map[loc].append(rid)

        spklu_details = {}
        for loc in active_locs:
            base = self.spklu_static.get("spklu_locations", {}).get(loc, {})
            spklu_details[loc] = {
                "name": base.get("name", loc),
                "n_gun": int(chromo["n_gun"][loc]),
                # TODO(akurasi): travel_min masih diambil flat dari spklu_locations.json,
                # bukan dari route_spklu_distance_matrix.json per-rute (lihat catatan modul
                # di atas). Ganti ke lookup per-rute kalau engine.py sudah diubah utk itu.
                "travel_min": base.get("travel_min", 30),
                "charge_min": base.get("charge_min", 60),
            }

        scenario = {
            "scenario_id": scenario_id,
            "scenario_name": f"GA/Bayesian candidate ({scenario_id})",
            "charging_mechanism": "full_opportunity",
            "spklu_assignment": "multi_by_route",
            "spklu_assignment_map": assignment_map,
            "spklu_details": spklu_details,
        }

        if chromo["algo"] in ("dynamic_v1", "dynamic_v2"):
            scenario["dynamic_charging"] = True
            params = dict(DEFAULT_DYNAMIC_PARAMS)
            params["dynamic_version"] = "v1" if chromo["algo"] == "dynamic_v1" else "v2"
            scenario["dynamic_charging_params"] = params
        else:
            scenario["dynamic_charging"] = False

        return scenario