# -*- coding: utf-8 -*-
"""
T-02: Normalisasi headway_gmaps_min & headway_dishub_min dari string -> integer menit.
T-03: QA baris _unparsed di routes_raw.json (Rute 3A & 5B).

Output:
  - data/routes.json diperbarui in-place (headway menjadi integer + field baru)
  - laporan QA ke stdout

Konvensi (rules.md §6):
  - ID rute tidak diubah
  - Jarak dalam meter
  - Waktu simulasi dalam menit
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES_JSON = ROOT / "data" / "routes.json"
ROUTES_RAW_JSON = ROOT / "data" / "routes_raw.json"


# ---------------------------------------------------------------------------
# Headway parser
# ---------------------------------------------------------------------------

def parse_headway(value: str | None, route_id: str, field_name: str) -> dict:
    """
    Konversi string headway ke integer menit.
    Returns dict dengan keys:
      - 'value_min'   : int | None
      - 'is_estimated': bool
      - 'raw'         : str (nilai asli, untuk audit)
      - 'parse_note'  : str (kosong jika berhasil; pesan jika ada ketidakpastian)
    """
    result = {"raw": value, "value_min": None, "is_estimated": False, "parse_note": ""}

    if value is None:
        result["parse_note"] = f"[{route_id}/{field_name}] NULL — needs manual review"
        result["is_estimated"] = True
        return result

    s = str(value).strip().lower()

    # Normalkan ± / +- / ±
    s_clean = re.sub(r"[±\+\-]+", "", s)          # hapus ± dan +-
    s_clean = s_clean.replace(" ", "")

    # Pola: angka + "min" (mis. "11min", "25min")
    m = re.match(r"^(\d+)min$", s_clean)
    if m:
        result["value_min"] = int(m.group(1))
        # Jika ada "±" di raw, tandai estimasi
        if "±" in value or "+-" in value or "+/-" in value:
            result["is_estimated"] = True
        return result

    # Pola: angka + "jam" (mis. "1jam")
    m = re.match(r"^(\d+)jam$", s_clean)
    if m:
        result["value_min"] = int(m.group(1)) * 60
        result["is_estimated"] = True
        result["parse_note"] = (
            f"[{route_id}/{field_name}] '{value}' dikonversi ke {result['value_min']} menit — "
            f"perlu konfirmasi manual apakah ini angka Dishub atau estimasi"
        )
        return result

    # Pola: angka saja
    m = re.match(r"^(\d+)$", s_clean)
    if m:
        result["value_min"] = int(m.group(1))
        result["is_estimated"] = True
        result["parse_note"] = f"[{route_id}/{field_name}] '{value}' — angka tanpa satuan, diasumsikan menit"
        return result

    # Tidak berhasil di-parse
    result["is_estimated"] = True
    result["parse_note"] = (
        f"[{route_id}/{field_name}] '{value}' — FORMAT TIDAK DIKENAL, perlu cek manual"
    )
    return result


# ---------------------------------------------------------------------------
# QA untuk _unparsed (T-03)
# ---------------------------------------------------------------------------

def qa_unparsed(routes_raw: list) -> list[dict]:
    """Kumpulkan semua entri _unparsed dari routes_raw.json dan analisis."""
    issues = []
    for route in routes_raw:
        route_id = route.get("id", "?")
        unparsed = route.get("_unparsed", [])
        if not unparsed:
            continue
        for raw_text in unparsed:
            # Coba ekstrak nama halte dan jarak dari teks mentah
            # Pola umum: "Nama Halte [+600m ]" atau "Nama Halte [+1km km]"
            m_m = re.search(r"\[.*?(\d+)\s*m.*?\]", raw_text, re.IGNORECASE)
            m_km = re.search(r"\[.*?(\d+)\s*km.*?\]", raw_text, re.IGNORECASE)

            if m_km:
                dist_m = int(m_km.group(1)) * 1000
                unit_note = "km->m"
            elif m_m:
                dist_m = int(m_m.group(1))
                unit_note = "m"
            else:
                dist_m = None
                unit_note = "tidak terdeteksi"

            # Nama halte: teks sebelum " ["
            stop_name_raw = re.sub(r"\[.*?\]", "", raw_text).strip()

            issues.append({
                "route_id": route_id,
                "raw_text": raw_text,
                "stop_name_extracted": stop_name_raw,
                "dist_from_prev_m_extracted": dist_m,
                "unit_note": unit_note,
                "recommendation": (
                    f"Tambahkan halte '{stop_name_raw}' dengan dist_from_prev_m={dist_m} "
                    f"ke routes.json Rute {route_id} — KONFIRMASI MANUAL sebelum apply"
                    if dist_m is not None
                    else f"Tidak bisa otomatis ekstrak jarak dari '{raw_text}' — cek dokumen sumber"
                ),
            })
    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("T-02/T-03: Normalisasi headway & QA _unparsed")
    print("=" * 60)

    # Load data
    with open(ROUTES_JSON, encoding="utf-8") as f:
        routes = json.load(f)
    with open(ROUTES_RAW_JSON, encoding="utf-8") as f:
        routes_raw = json.load(f)

    # --- T-02: Normalisasi headway ---
    parse_warnings = []
    headway_summary = []

    for route in routes:
        rid = route["route_id"]

        g = parse_headway(route.get("headway_gmaps_min"), rid, "headway_gmaps_min")
        d = parse_headway(route.get("headway_dishub_min"), rid, "headway_dishub_min")

        route["headway_gmaps_min_raw"] = g["raw"]
        route["headway_gmaps_min"] = g["value_min"]

        route["headway_dishub_min_raw"] = d["raw"]
        route["headway_dishub_min"] = d["value_min"]
        route["headway_dishub_is_estimated"] = d["is_estimated"]

        if g["parse_note"]:
            parse_warnings.append(g["parse_note"])
        if d["parse_note"]:
            parse_warnings.append(d["parse_note"])

        headway_summary.append({
            "route_id": rid,
            "headway_gmaps_min": g["value_min"],
            "headway_dishub_min": d["value_min"],
            "dishub_is_estimated": d["is_estimated"],
            "gmaps_raw": g["raw"],
            "dishub_raw": d["raw"],
        })

    # Tulis ulang routes.json
    with open(ROUTES_JSON, "w", encoding="utf-8") as f:
        json.dump(routes, f, ensure_ascii=False, indent=2)

    print("\n[T-02] Hasil normalisasi headway:")
    print(f"{'Route':<8} {'GMaps (min)':<14} {'Dishub (min)':<15} {'Dishub raw':<15} {'Estimated?'}")
    print("-" * 70)
    for s in headway_summary:
        est_flag = "[!] YES" if s["dishub_is_estimated"] else "no"
        print(
            f"{s['route_id']:<8} {str(s['headway_gmaps_min']):<14} "
            f"{str(s['headway_dishub_min']):<15} {str(s['dishub_raw']):<15} {est_flag}"
        )

    if parse_warnings:
        print("\n[T-02] PERINGATAN / Perlu review manual:")
        for w in parse_warnings:
            print(f"  [!]  {w}")
    else:
        print("\n[T-02] Semua headway berhasil di-parse tanpa ambiguitas.")

    # --- T-03: QA _unparsed ---
    print("\n" + "=" * 60)
    print("[T-03] QA baris _unparsed di routes_raw.json:")
    issues = qa_unparsed(routes_raw)
    if not issues:
        print("  Tidak ada baris _unparsed.")
    else:
        for iss in issues:
            print(f"\n  Rute {iss['route_id']}:")
            print(f"    Raw text       : {iss['raw_text']}")
            print(f"    Nama halte     : {iss['stop_name_extracted']}")
            print(f"    Jarak (m)      : {iss['dist_from_prev_m_extracted']} ({iss['unit_note']})")
            print(f"    Rekomendasi    : {iss['recommendation']}")

    print("\n[SELESAI] routes.json telah diperbarui dengan headway sebagai integer.")
    print("Pastikan untuk KONFIRMASI MANUAL sebelum melanjutkan untuk baris [!].")


if __name__ == "__main__":
    main()
