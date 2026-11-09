# 📚 Sistem Sirkulasi Perpustakaan Kampus

Aplikasi web sederhana untuk mengelola peminjaman buku perpustakaan kampus.
Dibuat dengan **Python + Streamlit + SQLite**, tanpa login.

## Menjalankan

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

Aplikasi terbuka otomatis di browser (biasanya `http://localhost:8501`).
Database `library.db` dibuat otomatis saat pertama kali dijalankan, lengkap
dengan data contoh.

## Fitur

| Menu | Isi |
|------|-----|
| **Dashboard** | Statistik judul/stok, peminjaman aktif, keterlambatan, denda, saldo dana, grafik buku populer |
| **Master Buku** | CRUD buku, kategori, pengarang, penerbit + filter & pencarian |
| **Peminjam** | CRUD data peminjam (NIM, nama, kelas, prodi, jurusan, WhatsApp) |
| **Peminjaman** | Catat peminjaman maks. 3 buku, tenggat otomatis 7 hari, konfirmasi WhatsApp |
| **Pengembalian & Denda** | Catat pengembalian, denda otomatis Rp1.000/hari, pelunasan, riwayat |
| **Dana Denda** | Rekap denda terkumpul/tunggakan, catat & hapus pengeluaran dana |

## Aturan bisnis yang diterapkan

- NIM sebagai primary key, tidak boleh duplikat.
- Kode buku wajib berformat `BK-[KOD]-[NOMOR]`, contoh `BK-TI-001`.
- Tenggat otomatis **7 hari** sejak tanggal pinjam.
- Denda **Rp1.000 per hari** keterlambatan.
- Stok tersedia dihitung otomatis: `stok_awal − buku yang belum dikembalikan`.
- Peminjaman ditolak jika stok habis.
- Buku yang kembali terlambat berstatus `MENUNGGU_PELUNASAN`; menjadi `SELESAI`
  setelah denda dilunasi.
- Peminjam/buku dengan transaksi aktif tidak bisa dihapus.
- Pengeluaran dana tidak boleh melebihi saldo dana terkumpul.

## Struktur database

`kategori`, `pengarang`, `penerbit`, `buku`, `peminjam`, `transaksi`,
`detail_transaksi`, `pengembalian`, `pengeluaran_dana`.

Stok dan detail transaksi diakses lewat view `v_buku` dan `v_detail` agar
perhitungan selalu konsisten.

## Reset data

Hentikan aplikasi, hapus file `library.db`, lalu jalankan ulang. Data contoh
akan dibuat kembali dari awal.
