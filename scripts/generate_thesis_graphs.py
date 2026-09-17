"""
scripts/generate_thesis_graphs.py
----------------------------------
Regenerate the key charts from the thesis (Bab VI) directly from the
aggregated scenario results in data/comparison_table_stochastic.csv.

NOTE ON SCOPE: the original polished figures embedded in the thesis PDF
(TA-STI-template-1.0/images/fig_*.png) were produced ad hoc during
thesis writing and their generation code was not preserved in this
repository as reusable scripts. This script instead reconstructs the
four most-cited comparisons FAITHFULLY FROM THE SAME UNDERLYING DATA
(data/comparison_table_stochastic.csv, which ships with this repo) so
the substantive numbers and shape of each figure can be verified
independently. Styling (fonts, exact colors, annotations) will differ
from the thesis PDF; the underlying values will not.

Usage:
    python scripts/generate_thesis_graphs.py

Output:
    data/results_figures/regime_shift.png
    data/results_figures/headway_comparison.png
    data/results_figures/degraded_routes_comparison.png
    data/results_figures/location_allocation_comparison.png
"""
from __future__ import annotations

import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "results_figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(ROOT / "data" / "comparison_table_stochastic.csv")
df = df.set_index("scenario_id")


def savefig(name: str):
    path = OUT_DIR / name
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close()
    print(f"[OK] {path}")


# ---------------------------------------------------------------------
# 1. Regime shift: single-station capacity sweep (Bab VI, "Titik Patah
#    Kapasitas pada SPKLU Tunggal")
# ---------------------------------------------------------------------
regime_ids = [
    "s15_probabilistic_1loc_n20",  # 20 gun (baseline)
    "s24_probabilistic_1loc_n19",  # 19 gun
    "s23_probabilistic_1loc_n18",  # 18 gun  <- regime shift here
    "s21_probabilistic_1loc_n16",  # 16 gun
    "s22_probabilistic_1loc_n12",  # 12 gun
]
gun_counts = [20, 19, 18, 16, 12]
degraded = [df.loc[i, "avg_degraded_routes_per_day_mean"] for i in regime_ids]

plt.figure(figsize=(8, 5))
plt.plot(gun_counts, degraded, marker="o", linewidth=2, color="#d94141")
plt.axvspan(18, 19, alpha=0.15, color="red", label="regime shift (19->18 gun)")
plt.gca().invert_xaxis()
plt.xlabel("Number of connectors (gun) at single station")
plt.ylabel("Degraded routes / day (mean of N=100 days)")
plt.title("Capacity Regime Shift (Single-Station Sweep)")
plt.legend()
plt.grid(alpha=0.3)
savefig("regime_shift.png")

# ---------------------------------------------------------------------
# 2 & 3. Headway and degraded-routes comparison across key scenarios
#    (Bab VI, "Perbandingan Skenario Kunci")
# ---------------------------------------------------------------------
key_ids = [
    "s17b_probabilistic_4loc_prop",  # baseline
    "s30_s17b_extra_bus_buffer_mid",  # +7% infra
    "s28_s17b_extra_bus_scaled_infra",  # +12% infra
    "s31_s17b_dynamic_v1",  # dynamic algorithm V1
    "s32_s17b_dynamic_v2",  # dynamic algorithm V2
    "s33_ultimate",  # infra + algorithm combined
]
labels = ["S17b\n(baseline)", "S30\n(+7% hw)", "S28\n(+12% hw)",
          "S31\n(V1 algo)", "S32\n(V2 algo)", "S33\n(S28+V1)"]
headway = [df.loc[i, "avg_headway_mean"] for i in key_ids]
headway_std = [df.loc[i, "avg_headway_std"] for i in key_ids]
deg = [df.loc[i, "avg_degraded_routes_per_day_mean"] for i in key_ids]

plt.figure(figsize=(9, 5))
bars = plt.bar(labels, headway, yerr=headway_std, capsize=4, color="#3d9eff")
plt.ylabel("Mean headway (minutes)")
plt.title("Headway Comparison: Infrastructure vs. Dynamic Algorithm")
for b, v in zip(bars, headway):
    plt.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.2f}",
              ha="center", va="bottom", fontsize=9)
plt.grid(axis="y", alpha=0.3)
savefig("headway_comparison.png")

plt.figure(figsize=(9, 5))
bars = plt.bar(labels, deg, color="#ff5252")
plt.ylabel("Degraded routes / day")
plt.title("Route Degradation Comparison: Infrastructure vs. Dynamic Algorithm")
for b, v in zip(bars, deg):
    plt.text(b.get_x() + b.get_width() / 2, v + 0.05, f"{v:.2f}",
              ha="center", va="bottom", fontsize=9)
plt.grid(axis="y", alpha=0.3)
savefig("degraded_routes_comparison.png")

# ---------------------------------------------------------------------
# 4. Location count / allocation comparison (Bab VI, "Perbandingan
#    Jumlah Lokasi SPKLU")
# ---------------------------------------------------------------------
loc_ids = ["s15_probabilistic_1loc_n20", "s16_probabilistic_2loc",
           "s17_probabilistic_4loc", "s17b_probabilistic_4loc_prop"]
loc_labels = ["S15\n1 site", "S16\n2 sites", "S17\n4 sites (even)",
              "S17b\n4 sites (proportional)"]
loc_deg = [df.loc[i, "avg_degraded_routes_per_day_mean"] for i in loc_ids]

plt.figure(figsize=(8, 5))
bars = plt.bar(loc_labels, loc_deg, color="#7a5cf0")
plt.ylabel("Degraded routes / day")
plt.title("Station Count vs. Allocation Strategy at Equal Total Capacity")
for b, v in zip(bars, loc_deg):
    plt.text(b.get_x() + b.get_width() / 2, v + 0.1, f"{v:.2f}",
              ha="center", va="bottom", fontsize=9)
plt.grid(axis="y", alpha=0.3)
savefig("location_allocation_comparison.png")

print("\nDone. 4 figures written to data/results_figures/.")
print("These reconstruct the substantive results of Bab VI Figs.; they are")
print("not pixel-identical to the thesis PDF's manually-styled originals.")
