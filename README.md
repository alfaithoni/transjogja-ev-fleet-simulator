# TransJogja EV Fleet Simulation

**Simulasi Operasional Armada Bus Listrik untuk Perencanaan Infrastruktur SPKLU pada Elektrifikasi Penuh TransJogja**
Muhammad Hanif Al Faithoni (18221135) | Program Studi Sistem dan Teknologi Informasi, Institut Teknologi Bandung

Simulasi *discrete-event* (dengan lapisan Monte Carlo) untuk elektrifikasi
penuh armada bus TransJogja (Yogyakarta), dipakai untuk mengevaluasi skenario
lokasi, kapasitas, dan mekanisme pengisian SPKLU (stasiun pengisian kendaraan
listrik umum). Repo ini menyertai:

- **Laporan TA (Bahasa Indonesia + abstrak Inggris):** [`TA-STI-template-1.0/`](TA-STI-template-1.0/) — lihat `TA.pdf`
- **Paper konferensi (Inggris, format IEEE):** [`paper/`](paper/) — lihat `paper.pdf`

## Isi repo ini (dan yang tidak ada)

Ini adalah salinan bersih dari repo pengembangan, disiapkan untuk orang yang
ingin **menjalankan sendiri simulasinya** tanpa perlu menyusuri seluruh
riwayat pengembangan. Sengaja dihapus:

- `data/results/` dan `data/raw/` — ratusan megabyte output mentah per-skenario,
  per-hari, hasil dari menjalankan script di bawah. Tidak disertakan karena
  bisa dibangkitkan ulang (bukan karena rahasia); jalankan
  `scripts/run_monte_carlo.py` untuk membuatnya ulang untuk skenario mana pun.
- Script pengembangan ad-hoc (`scratch/`, `lab/`, script debug/trace satu-kali
  di root repo) — ini alat eksplorasi selama pengerjaan TA, bukan antarmuka
  yang dijaga/dimaintain. Script yang disimpan di `scripts/` adalah yang
  sesuai dengan metodologi di laporan TA (Bab IV/V).
- `context/` — catatan kerja internal yang dipakai bersama asisten coding AI
  selama pengembangan (requirements, catatan arsitektur, breakdown tugas).
  Tidak diperlukan untuk menjalankan atau memahami simulasinya sendiri.
- `optimize/` (optimizer GA dan Bayesian) **tetap disertakan** untuk
  kelengkapan, tapi perlu dicatat bahwa skenario final TA (Bab VI) **tidak**
  memakai optimasi lokasi otomatis — lihat Batasan Masalah (Bab I) dan
  `optimize/README.md`. Disertakan karena kodenya memang ada dan berjalan,
  bukan karena menjadi sumber angka yang dilaporkan.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Membutuhkan Python 3.10+.

## Menjalankan skenario

Setiap skenario yang dipakai di laporan TA adalah file JSON di
`data/scenarios/` (mis. `s28_s17b_extra_bus_scaled_infra.json` adalah "S28"
di Bab VI). Ada dua cara menjalankannya:

**Simulasi satu hari** (cepat, berguna untuk sanity-check sebuah skenario):

```bash
python scripts/run_simulation.py --scenario-file data/scenarios/s28_s17b_extra_bus_scaled_infra.json
```

Mencetak ringkasan per-rute dan menulis
`data/results/simulation_result_<scenario_id>.json`.

**Agregat Monte Carlo N-hari** (ini yang sebenarnya dilaporkan di TA — setiap
angka headway/degradasi di Bab VI adalah rata-rata dari N=100 hari simulasi,
bukan satu kali jalan):

```bash
python scripts/run_monte_carlo.py --scenario-file data/scenarios/s28_s17b_extra_bus_scaled_infra.json --n-days 100
```

Ini mencetak `avg_headway_mean`, `avg_degraded_routes_per_day_mean`, dan
metrik agregat terkait, lalu menulisnya ke `data/results/mc_<scenario_id>.json`.
**Bandingkan hasilnya dengan baris `scenario_id` yang sama di
`data/comparison_table_stochastic.csv`** — CSV itu adalah tabel agregat persis
yang menjadi dasar seluruh gambar dan tabel di laporan TA. Dengan
`--seed-base` yang sama (default 42, sesuai yang dipakai aslinya), angkanya
seharusnya berada dalam rentang noise simulasi dari nilai yang dipublikasikan;
misalnya N=10 saja sudah berada dalam sekitar 1% dari headway S28 yang
dilaporkan.

Daftar scenario ID kunci yang dirujuk di laporan TA, kalau ingin mereproduksi
hasil tertentu tanpa perlu membaca semua file di `data/scenarios/`:

| Scenario ID | Label di TA | Yang diuji |
|---|---|---|
| `s17b_probabilistic_4loc_prop` | S17b | Baseline 4 lokasi, kapasitas proporsional |
| `s28_s17b_extra_bus_scaled_infra` | S28 | +12% kapasitas dari baseline |
| `s30_s17b_extra_bus_buffer_mid` | S30 | +7% kapasitas dari baseline |
| `s31_s17b_dynamic_v1` | S31 | Kebijakan charging dinamis (time-aware), tanpa tambahan hardware |
| `s32_s17b_dynamic_v2` | S32 | Kebijakan charging dinamis (time+queue-aware) |
| `s33_ultimate` | S33 | Infrastruktur S28 + algoritma S31 digabung |
| `s15_probabilistic_1loc_n20` ... `s24_probabilistic_1loc_n19` | S15, S19–S24 | Sweep kapasitas satu-stasiun (regime shift) |

## Membuat grafik

```bash
python scripts/generate_thesis_graphs.py
```

Menulis empat grafik ke `data/results_figures/` (regime shift, perbandingan
headway, perbandingan rute terdegradasi, perbandingan lokasi/alokasi),
dibangun langsung dari `data/comparison_table_stochastic.csv`.

**Catatan cakupan penting:** gambar final yang tertanam di PDF laporan TA
(`TA-STI-template-1.0/images/fig_*.png`) dibuat secara ad hoc saat penulisan
TA, dan kode pembuatannya tidak disimpan sebagai script yang bisa dipakai
ulang di repo ini. `generate_thesis_graphs.py` merekonstruksi ulang empat
perbandingan yang paling banyak dikutip dari data dasar yang sama, sehingga
angka dan tren substantifnya bisa diverifikasi secara independen — nilainya
akan cocok, tapi styling-nya (font, warna, layout persis) tidak akan identik
piksel-demi-piksel dengan PDF TA. Gambar TA lainnya (peta demand
spasial/temporal, kurva konvergensi Monte Carlo, trace ketahanan 14 hari,
tabel deviasi per-rute) membutuhkan data mentah terkait yang dibangkitkan
ulang lewat `run_monte_carlo.py` dengan logging per-hari/per-rute
diaktifkan; pipeline itu belum dirangkai jadi satu script tunggal saat ini.

## Dashboard interaktif

```bash
python dashboard/app.py
```

Menyajikan visualisasi lokal state rute/bus/SPKLU per skenario, seperti
dijelaskan di Bab V laporan TA. Buka URL lokal yang tercetak di terminal
lewat browser.

## Menjalankan test

```bash
python -m pytest tests/
```

**Kondisi saat ini:** 10 dari 17 test lolos. 7 kegagalan ada di
`test_battery.py` dan menyasar model baterai heuristik `k1`/`k2` versi awal
yang disebut di Bab IV sebagai langkah antara yang ditinggalkan — model itu
digantikan oleh model rational-polynomial $EC(v)$ dari Mamarikas dkk. sebelum
skenario final TA dijalankan, dan test case terkait tidak pernah diperbarui
atau dihapus. Ini adalah jejak transisi tersebut, bukan regresi pada
simulasi saat ini; perilaku model yang dipakai sekarang sudah teruji secara
tidak langsung lewat `run_simulation.py` dan `run_monte_carlo.py` di atas.

## Meng-compile laporan TA dan paper

Keduanya memakai XeLaTeX + Biber (bukan pdfLaTeX + BibTeX). Kalau memakai
VS Code dengan ekstensi LaTeX Workshop, tambahkan recipe ini ke settings:

```json
"latex-workshop.latex.recipes": [
    { "name": "xelatex -> biber -> xelatex*2",
      "tools": ["xelatex", "biber", "xelatex", "xelatex"] }
]
```

Atau lewat command line, di dalam `TA-STI-template-1.0/` (laporan TA) atau
`paper/` (paper konferensi):

```bash
xelatex -interaction=nonstopmode <file>.tex
biber <file>          # hanya untuk laporan TA; paper.tex pakai thebibliography biasa
xelatex -interaction=nonstopmode <file>.tex
xelatex -interaction=nonstopmode <file>.tex
```

Laporan TA (`TA.tex`) membutuhkan font Times New Roman terpasang di sistem
(lewat `fontspec`) dan distribusi LaTeX yang lengkap (`texlive-full` di
Linux, MacTeX di macOS, atau TeX Live/MiKTeX di Windows) — instalasi minimal
akan kehilangan paket seperti `tracklang` dan `biblatex-chicago`. Paper
(`paper.tex`) bisa di-compile dengan instalasi `pdflatex` standar dan
`IEEEtran.cls`/`IEEEtran.bst` yang sudah disertakan.

## Kamus data (referensi cepat)

| File | Isinya |
|---|---|
| `data/routes.json` | 20 koridor TransJogja: halte, jarak antar-halte, jumlah bus, target headway |
| `data/bus_spec.json` | Kapasitas baterai dan parameter model konsumsi energi |
| `data/spklu_locations.json` | Lokasi kandidat/terpilih untuk stasiun charging |
| `data/scenarios/*.json` | Satu file per skenario simulasi (konfigurasi yang dikirim ke `GlobalSimulator`) |
| `data/comparison_table_stochastic.csv` | Tabel hasil agregat N=100, dasar semua angka di Bab VI |
| `data/headway_vs_dishub_target.csv`, `data/headway_deviation_summary.md` | Headway per-rute vs. target resmi dari operator |
| `data/dashboard_traces/` | Contoh trace kecil yang dipakai dashboard |

## Konteks akademik

Ini adalah software riset untuk Tugas Akhir dan paper konferensi program
Sarjana Sistem dan Teknologi Informasi, Institut Teknologi Bandung. Bukan
produk resmi TransJogja/Dishub DIY. Data rute dan operasional disediakan oleh
penulis untuk keperluan riset.