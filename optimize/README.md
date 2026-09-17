# optimize/ — Kerangka Optimasi Lokasi + Kapasitas + Algoritma SPKLU

Langkah 3+ dari rencana kerja (lanjutan setelah persiapan data selesai). Sudah
di-smoke-test end-to-end lewat `simulation/engine.py` yang asli (GA jalan tanpa
error, output masuk akal: 0 degraded di kondisi gun berlebih).

## Isi

| File | Fungsi |
|---|---|
| `decision_space.py` | Encoding: 6 kandidat lokasi, n_gun, assignment rute↔lokasi (dibatasi reachability dari `route_spklu_distance_matrix.json`), pilihan algoritma charging. Fungsi `decode_to_scenario()` mengubah 1 kandidat solusi jadi scenario JSON yang format-nya sama persis dengan `data/scenarios/s17b_probabilistic_4loc_prop.json` dkk. |
| `fitness.py` | `run_monte_carlo()` — 1:1 meniru pola aggregasi di `scratch/run_all_final_31.py` (headway rute non-degraded, degraded count/hari, dst) supaya angka bisa dibandingkan langsung dgn `comparison_table_stochastic.csv`. `scalarize()` gabungkan jadi 1 angka fitness (degraded routes >> total gun). |
| `ga_optimizer.py` | GA custom (tournament selection, uniform crossover, mutasi per-gene, elitism). **Tidak butuh dependency eksternal.** |
| `bayesian_optimizer.py` | Alternatif pakai Optuna (TPE sampler). Butuh `pip install optuna` dulu. |

## Cara pakai

```bash
cd transjogja-ev-sim  # root repo
# taruh folder optimize/ di sini (sejajar dgn simulation/, data/, scratch/)

# GA (tanpa dependency tambahan) — smoke test dulu, cepat:
python -m optimize.ga_optimizer --pop 4 --gens 2 --n-days 2

# GA "beneran" (baru jalankan setelah smoke test OK, ini BISA lama):
python -m optimize.ga_optimizer --pop 30 --gens 25 --n-days 20

# Bayesian (opsional, perlu: pip install optuna):
python -m optimize.bayesian_optimizer --n-trials 300 --n-days 20
```

Kedua optimizer menyimpan kandidat terbaik ke `optimize/results/*_best_scenario.json`
berisi `scenario` (siap ditaruh di `data/scenarios/`), `chromosome` (encoding mentah),
dan `metrics_at_search_n` (metrik dari N kecil yang dipakai SAAT SEARCH — bukan angka
final).

## WAJIB sebelum dipakai sebagai angka final TA

1. **Confirmation run N=100** di kandidat terbaik (search pakai N=20-30 biar cepat,
   sesuai rencana kerja yang disepakati). Bisa pakai `fitness.run_monte_carlo()`
   langsung dengan `n_days=100`, atau taruh scenario hasil optimizer di
   `data/scenarios/` lalu jalankan lewat script bergaya
   `scratch/run_all_final_31.py`.
2. **Verifikasi hasil optimizer masuk akal**, bukan cuma "fitness bagus" — cek
   pola kerja proyek yang sudah berlaku selama ini: std dev persis 0,00 curiga
   bug, hasil "terlalu rapi" perlu dicurigai, dst.

## Simplifikasi/asumsi yang perlu diketahui (bukan bug, tapi keputusan desain)

- **`travel_min` per SPKLU masih FLAT (1 angka per lokasi), bukan per kombinasi
  rute×lokasi.** `route_spklu_distance_matrix.json` di skeleton ini dipakai HANYA
  untuk menentukan rute mana boleh di-assign ke lokasi mana (reachability), bukan
  untuk override waktu tempuh spesifik per rute — karena itu butuh ubah
  `simulation/engine.py` (BusAgent/`compute_charge_duration`), yang sengaja belum
  disentuh di tahap persiapan data. Kalau nanti ingin akurasi lebih tinggi, ini
  langkah terpisah yang perlu didiskusikan dulu (mengubah signature/kontrak
  `spklu_dict` di `GlobalSimulator.run()`).
- Ditemukan saat baca `engine.py`: field `bus_details` (per-route extra bus count)
  yang ada di `data/scenarios/s35_sweet_spot.json` **tidak dibaca sama sekali**
  oleh `GlobalSimulator` — hanya `extra_bus_per_route` (1 angka global) yang
  dipakai. Kemungkinan sisa eksperimen yang tidak jadi diimplementasi. Optimizer
  ini juga tidak memakainya (assumsi: jumlah bus per rute tetap seperti
  `routes.json`, tidak dioptimasi). Tandai buat dicek — kalau memang dead field,
  sebaiknya dibersihkan/didokumentasikan di TA.
- Rentang `n_gun` dibatasi `MIN_GUN=1, MAX_GUN=30` per lokasi (`decision_space.py`)
  berdasarkan histori S17b-S35 (2-10 gun/lokasi, total 20-26). Longgarkan kalau mau
  eksplorasi lebih luas.
- Fitness scalar (`scalarize()`) pakai weighted-sum sederhana (degraded routes
  dikali 1000, ditambah total gun) — bukan Pareto front. Kalau mau eksplisit
  multi-objective (trade-off degraded vs biaya infrastruktur, bukan 1 angka),
  ganti ke NSGA-II (custom) atau `optuna.create_study(directions=["minimize","minimize"])`
  di sisi Bayesian.