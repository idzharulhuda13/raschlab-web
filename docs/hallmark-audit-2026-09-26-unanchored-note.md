# Hallmark audit — catatan "tanpa jangkar" (raschlab-web, analysis.html)

Tanggal: 26 Sep 2026. Auditor: Arc. Mode antislop: **DURING** (kontrak repo `DESIGN.md:14`), ditutup gate ini.
Cakupan: satu blok yang berubah (band `alert--warn` di halaman hasil analisis) + satu aturan CSS pendukung.
Halaman lain, tabel, grafik, dan alur lain tidak disentuh dan tidak diaudit di sini.

## Provenance beku

Byte yang benar-benar dikirim server dicocokkan dengan pohon kerja (sha256, 16 heks pertama):

- `app/static/app.css` dikirim `1af7a5e6d2a7ba39` = file kerja `1af7a5e6d2a7ba39` (identik)
- `page_unanchored.html` dikirim `4a0226ae080872aa` = file render `4a0226ae080872aa` (identik)
- `app/static` adalah symlink ke `/root/projects/raschlab-web/app/static`, jadi tidak ada salinan tersembunyi

Catatan provenance: CSS yang diaudit tidak berubah sesudah audit (`1af7a5e6d2a7ba39` sebelum dan sesudah pin engine naik).
Hash halaman berubah dari `86c5499a1c570632` ke `4a0226ae080872aa` karena satu-satunya bedanya adalah nomor versi
mesin yang dicetak di halaman (`8e8ac67` menjadi `c41c396`); kalimat catatan dan CSS-nya identik, dan pengukuran
ulang sesudah pin naik memberi angka yang sama (375/375 px, nol overflow, uji nama 184 karakter tetap di kartu).

Pohon ini **belum di-commit** saat audit. Kalau ada yang mengubah berkas setelah ini, audit batal dan harus diulang.

## Sel yang diukur (1 halaman x 2 tema x 2 lebar = 4 sel)

| sel | lebar dokumen / viewport | catatan keluar kartu | kontras judul | kontras teks | ukuran teks |
|---|---|---|---|---|---|
| 375 px · terang | 375 / 375 | tidak | 6,92:1 | 15,78:1 | 16 px |
| 375 px · gelap | 375 / 375 | tidak | 10,06:1 | 15,65:1 | 16 px |
| 1440 px · terang | 1425 / 1425 | tidak | 6,92:1 | 15,78:1 | 16 px |
| 1440 px · gelap | 1425 / 1425 | tidak | 10,06:1 | 15,65:1 | 16 px |

Uji tekanan: nama berkas 184 karakter tanpa titik putus.

- sebelum perbaikan (terukur): catatan keluar dari kartu, lebar dokumen **1807 px** di viewport 375 px
- sesudah perbaikan (terukur): catatan membungkus, tepi kanan 329 px < tepi kartu 351 px, lebar dokumen **375 px**

## Temuan per tingkat keseriusan

Format: Tell · Where · Severity · Fix.

CRITICAL: tidak ada. 0 temuan.

MAJOR: tidak ada temuan terbuka. Satu defect nyata ditemukan di perubahan ini dan sudah ditutup:
- Tell: teks keluar dari kartu, dokumen melebar mendatar di mobile
- Where: catatan unanchored, `app/templates/analysis.html:91` + `app/static/app.css:683`
- Severity: MAJOR
- Fix: `.alert .mono { overflow-wrap: anywhere; }` (kelas lama, token lama) + pin di `tests/test_ui_contract.py`; sesudahnya terukur 375/375 px

MINOR: tidak ada temuan terbuka. Dua kandidat diperiksa lalu ditolak dengan ukuran:
- Tell: klaim berlebih "yang bergeser hanya titik nolnya, bukan urutan hasilnya" (temuan reviewer)
  Fix: kalimat ditulis ulang menyebut cakupannya (matriks pembanding, bukan jaminan umum) + pin tes
- Tell: dua band bertema warn di satu halaman (catatan ini + `analysis.html:98`)
  Ditolak: dua-duanya bawa kata yang berbeda dan makna berbeda; keluarga alert di app ini memang kata + border
  (glyph hidup di `chip-glyph` pada chip status), jadi tidak ada drift gaya baru

Jumlah temuan terbuka: **0** (0 critical, 0 major, 0 minor).

## Sidik struktur dan drift terhadap DESIGN.md

- Dial disebut di `DESIGN.md:20`: ENERGY 3 / RHYTHM 3 / MOTION 2. Perubahan ini tidak menambah gerak (aturan bungkus teks bukan animasi) dan tidak mengubah ritme halaman.
- Token: `--warn` `#7A5200` terang 6,92:1 (`DESIGN.md:52`) dan `#E8BE6A` gelap 10,06:1 (`DESIGN.md:69`). Angka ukur sama persis dengan dokumen, dan tidak ada warna baru yang diperkenalkan.
- Kelas: tidak ada nama kelas baru; pin jumlah kelas di `tests/test_ui_contract.py` tetap lolos (suite web 186 lulus).
- Motif identitas ("pita ukur") tidak disentuh.
- Teks terlarang: nol em dash, nol kata pemasaran puffy, diukur pada dua halaman hasil render.
