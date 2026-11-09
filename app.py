"""Sistem Sirkulasi Peminjaman Buku Perpustakaan Kampus.

Streamlit + SQLite, tanpa login.
Jalankan: streamlit run app.py
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).with_name("library.db")

LAMA_PINJAM_HARI = 7
DENDA_PER_HARI = 1_000
MAX_BUKU_PER_TRANSAKSI = 3

STATUS_MENUNGGU = "MENUNGGU_PELUNASAN"
STATUS_SELESAI = "SELESAI"

KODE_BUKU_RE = re.compile(r"^BK-[A-Z0-9]+-[0-9]{3}$")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kategori (
    id_kategori   INTEGER PRIMARY KEY AUTOINCREMENT,
    nama_kategori TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS pengarang (
    id_pengarang   INTEGER PRIMARY KEY AUTOINCREMENT,
    nama_pengarang TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS penerbit (
    id_penerbit   INTEGER PRIMARY KEY AUTOINCREMENT,
    nama_penerbit TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS buku (
    id_buku      INTEGER PRIMARY KEY AUTOINCREMENT,
    kode_buku    TEXT NOT NULL UNIQUE,
    judul        TEXT NOT NULL,
    ISBN         TEXT NOT NULL UNIQUE,
    stok_awal    INTEGER NOT NULL DEFAULT 0 CHECK (stok_awal >= 0),
    id_pengarang INTEGER NOT NULL REFERENCES pengarang(id_pengarang),
    id_penerbit  INTEGER NOT NULL REFERENCES penerbit(id_penerbit),
    id_kategori  INTEGER NOT NULL REFERENCES kategori(id_kategori)
);

CREATE TABLE IF NOT EXISTS peminjam (
    nim         TEXT PRIMARY KEY,
    nama        TEXT NOT NULL,
    kelas       TEXT NOT NULL,
    prodi       TEXT NOT NULL,
    jurusan     TEXT NOT NULL,
    no_telp_wa  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transaksi (
    id_transaksi   INTEGER PRIMARY KEY AUTOINCREMENT,
    kode_transaksi TEXT NOT NULL UNIQUE,
    nim            TEXT NOT NULL REFERENCES peminjam(nim) ON UPDATE CASCADE,
    tgl_pinjam     DATE NOT NULL,
    tgl_tenggat    DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS detail_transaksi (
    id_detail_transaksi INTEGER PRIMARY KEY AUTOINCREMENT,
    id_transaksi        INTEGER NOT NULL REFERENCES transaksi(id_transaksi) ON DELETE CASCADE,
    id_buku             INTEGER NOT NULL REFERENCES buku(id_buku)
);

CREATE TABLE IF NOT EXISTS pengembalian (
    id_pengembalian      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_detail_transaksi  INTEGER NOT NULL UNIQUE REFERENCES detail_transaksi(id_detail_transaksi),
    tgl_kembali          DATE NOT NULL,
    kondisi_buku         TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('MENUNGGU_PELUNASAN', 'SELESAI')),
    denda                INTEGER NOT NULL DEFAULT 0 CHECK (denda >= 0),
    tgl_pembayaran_denda DATE
);

CREATE TABLE IF NOT EXISTS pengeluaran_dana (
    id_pengeluaran INTEGER PRIMARY KEY AUTOINCREMENT,
    tanggal        DATE NOT NULL,
    keterangan     TEXT NOT NULL,
    jumlah         INTEGER NOT NULL CHECK (jumlah > 0)
);

-- Stok tersedia = stok_awal - jumlah buku yang belum dikembalikan.
CREATE VIEW IF NOT EXISTS v_buku AS
SELECT
    b.*,
    b.stok_awal - COALESCE(SUM(
        CASE WHEN d.id_detail_transaksi IS NOT NULL AND pg.id_pengembalian IS NULL
             THEN 1 ELSE 0 END
    ), 0) AS stok_tersedia
FROM buku b
LEFT JOIN detail_transaksi d ON d.id_buku = b.id_buku
LEFT JOIN pengembalian pg ON pg.id_detail_transaksi = d.id_detail_transaksi
GROUP BY b.id_buku;

CREATE VIEW IF NOT EXISTS v_detail AS
SELECT
    d.id_detail_transaksi,
    d.id_transaksi,
    t.kode_transaksi,
    t.nim,
    p.nama AS nama_peminjam,
    p.no_telp_wa,
    t.tgl_pinjam,
    t.tgl_tenggat,
    b.id_buku,
    b.kode_buku,
    b.judul,
    pg.id_pengembalian,
    pg.tgl_kembali,
    pg.kondisi_buku,
    pg.status,
    pg.denda,
    pg.tgl_pembayaran_denda
FROM detail_transaksi d
JOIN transaksi t ON t.id_transaksi = d.id_transaksi
JOIN peminjam p ON p.nim = t.nim
JOIN buku b ON b.id_buku = d.id_buku
LEFT JOIN pengembalian pg ON pg.id_detail_transaksi = d.id_detail_transaksi;
"""


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(sql, params).fetchall()


def execute(sql: str, params: tuple = ()) -> int:
    with db() as conn:
        return conn.execute(sql, params).lastrowid


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        seeded = conn.execute("SELECT 1 FROM app_meta WHERE key = 'seeded'").fetchone()
        if not seeded:
            seed_data(conn)
            conn.execute("INSERT INTO app_meta (key, value) VALUES ('seeded', '1')")


def seed_data(conn: sqlite3.Connection) -> None:
    """Data contoh supaya aplikasi langsung bisa dicoba."""
    today = date.today()

    kategori = {}
    for nama in ["Teknologi Informasi", "Ekonomi & Bisnis", "Sastra", "Sains"]:
        kategori[nama] = conn.execute(
            "INSERT INTO kategori (nama_kategori) VALUES (?)", (nama,)
        ).lastrowid

    pengarang = {}
    for nama in [
        "Rinaldi Munir",
        "Abdul Kadir",
        "Sugiyono",
        "Andrea Hirata",
        "Pramoedya Ananta Toer",
    ]:
        pengarang[nama] = conn.execute(
            "INSERT INTO pengarang (nama_pengarang) VALUES (?)", (nama,)
        ).lastrowid

    penerbit = {}
    for nama in ["Informatika", "Andi Publisher", "Alfabeta", "Bentang Pustaka", "Gramedia"]:
        penerbit[nama] = conn.execute(
            "INSERT INTO penerbit (nama_penerbit) VALUES (?)", (nama,)
        ).lastrowid

    buku_data = [
        ("BK-TI-001", "Algoritma dan Pemrograman", "978-602-1514-01-1", 3, "Rinaldi Munir", "Informatika", "Teknologi Informasi"),
        ("BK-TI-002", "Basis Data Relasional", "978-602-1514-02-8", 2, "Abdul Kadir", "Andi Publisher", "Teknologi Informasi"),
        ("BK-EK-001", "Metodologi Penelitian Bisnis", "978-602-289-01-5", 2, "Sugiyono", "Alfabeta", "Ekonomi & Bisnis"),
        ("BK-SA-001", "Laskar Pelangi", "978-979-3062-79-2", 4, "Andrea Hirata", "Bentang Pustaka", "Sastra"),
        ("BK-SA-002", "Bumi Manusia", "978-979-97312-3-3", 2, "Pramoedya Ananta Toer", "Gramedia", "Sastra"),
    ]
    buku = {}
    for kode, judul, isbn, stok, peng, terbit, kat in buku_data:
        buku[kode] = conn.execute(
            """INSERT INTO buku
               (kode_buku, judul, ISBN, stok_awal, id_pengarang, id_penerbit, id_kategori)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (kode, judul, isbn, stok, pengarang[peng], penerbit[terbit], kategori[kat]),
        ).lastrowid

    peminjam_data = [
        ("4.52.24.3.10", "Febe Galih A.", "TI-2A", "D4 Teknik Informatika", "Teknik Elektro", "081234567810"),
        ("4.52.24.3.24", "Saffa Adeline", "TI-2A", "D4 Teknik Informatika", "Teknik Elektro", "081234567824"),
        ("4.52.24.3.27", "Talitha Dafa A.", "TI-2B", "D4 Teknik Informatika", "Teknik Elektro", "081234567827"),
        ("4.52.24.3.28", "Windi Aprilia S.", "TI-2B", "D4 Teknik Informatika", "Teknik Elektro", "081234567828"),
    ]
    for nim, nama, kelas, prodi, jurusan, wa in peminjam_data:
        conn.execute(
            """INSERT INTO peminjam (nim, nama, kelas, prodi, jurusan, no_telp_wa)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (nim, nama, kelas, prodi, jurusan, wa),
        )

    def add_transaksi(nim: str, kode_buku: list[str], tgl_pinjam: date, nomor: int = 1):
        tgl_tenggat = tgl_pinjam + timedelta(days=LAMA_PINJAM_HARI)
        kode = f"TRX-PJM-{tgl_pinjam.strftime('%Y%m%d')}-{nomor:03d}"
        tid = conn.execute(
            """INSERT INTO transaksi (kode_transaksi, nim, tgl_pinjam, tgl_tenggat)
               VALUES (?, ?, ?, ?)""",
            (kode, nim, tgl_pinjam.isoformat(), tgl_tenggat.isoformat()),
        ).lastrowid
        detail = []
        for bk in kode_buku:
            detail.append(
                conn.execute(
                    "INSERT INTO detail_transaksi (id_transaksi, id_buku) VALUES (?, ?)",
                    (tid, buku[bk]),
                ).lastrowid
            )
        return detail

    # Sedang dipinjam dan sudah terlambat 3 hari.
    add_transaksi("4.52.24.3.10", ["BK-TI-001"], today - timedelta(days=10))
    # Sedang dipinjam, masih dalam tenggat.
    add_transaksi("4.52.24.3.24", ["BK-TI-002", "BK-SA-001"], today - timedelta(days=2))
    # Sudah kembali, denda belum dibayar (telat 3 hari = Rp3.000).
    detail = add_transaksi("4.52.24.3.27", ["BK-SA-002"], today - timedelta(days=12))
    conn.execute(
        """INSERT INTO pengembalian
           (id_detail_transaksi, tgl_kembali, kondisi_buku, status, denda)
           VALUES (?, ?, 'Baik', ?, ?)""",
        (detail[0], (today - timedelta(days=2)).isoformat(), STATUS_MENUNGGU, 3 * DENDA_PER_HARI),
    )
    # Sudah kembali tepat waktu.
    detail = add_transaksi("4.52.24.3.28", ["BK-EK-001"], today - timedelta(days=20))
    conn.execute(
        """INSERT INTO pengembalian
           (id_detail_transaksi, tgl_kembali, kondisi_buku, status, denda, tgl_pembayaran_denda)
           VALUES (?, ?, 'Baik', ?, 0, NULL)""",
        (detail[0], (today - timedelta(days=16)).isoformat(), STATUS_SELESAI),
    )


# ---------------------------------------------------------------------------
# Helper umum
# ---------------------------------------------------------------------------
def rupiah(n: int | float) -> str:
    return "Rp" + f"{int(n):,}".replace(",", ".")


def tgl_id(value: str | date) -> str:
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value.strftime("%d-%m-%Y")


def flash(message: str, kind: str = "success") -> None:
    st.session_state["_flash"] = (message, kind)


def show_flash() -> None:
    item = st.session_state.pop("_flash", None)
    if item:
        message, kind = item
        getattr(st, kind)(message)


def frame(rows: list[sqlite3.Row]) -> pd.DataFrame:
    return pd.DataFrame([dict(r) for r in rows])


def friendly_integrity(err: sqlite3.IntegrityError) -> str:
    msg = str(err)
    if "buku.kode_buku" in msg:
        return "Kode buku sudah digunakan."
    if "buku.ISBN" in msg:
        return "ISBN sudah digunakan."
    if "peminjam.nim" in msg:
        return "NIM sudah terdaftar."
    if "nama_kategori" in msg:
        return "Nama kategori sudah ada."
    return f"Data tidak valid: {msg}"


def wa_link(no_telp: str, pesan: str) -> str | None:
    digits = re.sub(r"\D", "", no_telp or "")
    if not digits:
        return None
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    return f"https://wa.me/{digits}?text={quote(pesan)}"


def denda_berjalan(tgl_tenggat: str | date, hari_ini: date | None = None) -> int:
    hari_ini = hari_ini or date.today()
    if isinstance(tgl_tenggat, str):
        tgl_tenggat = date.fromisoformat(tgl_tenggat)
    telat = max(0, (hari_ini - tgl_tenggat).days)
    return telat * DENDA_PER_HARI


def status_denda(status: str | None) -> str:
    return {
        STATUS_MENUNGGU: "Menunggu Pelunasan",
        STATUS_SELESAI: "Selesai",
    }.get(status or "", "-")


# ---------------------------------------------------------------------------
# Halaman: Dashboard
# ---------------------------------------------------------------------------
def page_dashboard() -> None:
    st.title("📊 Dashboard")
    st.caption("Ringkasan sirkulasi perpustakaan hari ini.")

    today = date.today()
    m = query(
        """
        SELECT
          (SELECT COUNT(*) FROM buku) AS judul,
          (SELECT COALESCE(SUM(stok_awal), 0) FROM buku) AS total_stok,
          (SELECT COALESCE(SUM(stok_tersedia), 0) FROM v_buku) AS tersedia,
          (SELECT COUNT(*) FROM peminjam) AS peminjam,
          (SELECT COUNT(*) FROM v_detail WHERE id_pengembalian IS NULL) AS dipinjam,
          (SELECT COUNT(*) FROM v_detail
            WHERE id_pengembalian IS NULL AND tgl_tenggat < ?) AS terlambat,
          (SELECT COALESCE(SUM(denda), 0) FROM pengembalian
            WHERE status = ?) AS tunggakan,
          (SELECT COALESCE(SUM(denda), 0) FROM pengembalian
            WHERE tgl_pembayaran_denda IS NOT NULL) AS terkumpul,
          (SELECT COALESCE(SUM(jumlah), 0) FROM pengeluaran_dana) AS pengeluaran
        """,
        (today.isoformat(), STATUS_MENUNGGU),
    )[0]
    saldo = m["terkumpul"] - m["pengeluaran"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Judul Buku", m["judul"])
    c2.metric("Buku Tersedia", m["tersedia"], help=f"Dari total {m['total_stok']} buku")
    c3.metric("Peminjam", m["peminjam"])
    c4.metric("Buku Sedang Dipinjam", m["dipinjam"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Peminjaman Terlambat", m["terlambat"], delta="perlu tindak lanjut" if m["terlambat"] else None, delta_color="inverse")
    c2.metric("Denda Belum Tertagih", rupiah(m["tunggakan"]))
    c3.metric("Dana Denda Terkumpul", rupiah(m["terkumpul"]))
    c4.metric("Saldo Dana Denda", rupiah(saldo))

    st.divider()

    aktif = query(
        """SELECT * FROM v_detail WHERE id_pengembalian IS NULL
           ORDER BY tgl_tenggat, kode_transaksi"""
    )
    df = frame(aktif)
    if df.empty:
        st.info("Belum ada buku yang sedang dipinjam.")
    else:
        df["status"] = df["tgl_tenggat"].apply(
            lambda t: "Terlambat" if date.fromisoformat(t) < today else "Dalam tenggat"
        )
        df["denda_berjalan"] = df["tgl_tenggat"].apply(lambda t: rupiah(denda_berjalan(t, today)))
        df = df.rename(
            columns={
                "kode_transaksi": "Kode Transaksi",
                "nim": "NIM",
                "nama_peminjam": "Peminjam",
                "judul": "Judul Buku",
                "tgl_pinjam": "Tgl Pinjam",
                "tgl_tenggat": "Tenggat",
                "status": "Status",
                "denda_berjalan": "Denda Berjalan",
            }
        )
        st.subheader("🔄 Peminjaman Aktif")
        st.dataframe(
            df[["Kode Transaksi", "NIM", "Peminjam", "Judul Buku", "Tgl Pinjam", "Tenggat", "Status", "Denda Berjalan"]],
            hide_index=True,
            width="stretch",
        )

    st.divider()
    populer = query(
        """SELECT b.judul, COUNT(*) AS jumlah
           FROM detail_transaksi d
           JOIN buku b ON b.id_buku = d.id_buku
           GROUP BY b.id_buku
           ORDER BY jumlah DESC, b.judul
           LIMIT 5"""
    )
    if populer:
        st.subheader("🏆 Buku Paling Sering Dipinjam")
        st.bar_chart(
            frame(populer),
            x="judul",
            y="jumlah",
            x_label="Judul Buku",
            y_label="Jumlah Peminjaman",
            height=300,
        )


# ---------------------------------------------------------------------------
# Halaman: Master Buku
# ---------------------------------------------------------------------------
def page_buku() -> None:
    st.title("📚 Master Data Buku")
    tab_buku, tab_kategori, tab_pengarang, tab_penerbit = st.tabs(
        ["Buku", "Kategori", "Pengarang", "Penerbit"]
    )
    with tab_buku:
        tab_daftar_buku()
    with tab_kategori:
        crud_lookup("Kategori", "kategori", "id_kategori", "nama_kategori", "id_kategori", "kategori")
    with tab_pengarang:
        crud_lookup("Pengarang", "pengarang", "id_pengarang", "nama_pengarang", "id_pengarang", "pengarang")
    with tab_penerbit:
        crud_lookup("Penerbit", "penerbit", "id_penerbit", "nama_penerbit", "id_penerbit", "penerbit")


def tab_daftar_buku() -> None:
    kategori = query("SELECT * FROM kategori ORDER BY nama_kategori")
    pengarang = query("SELECT * FROM pengarang ORDER BY nama_pengarang")
    penerbit = query("SELECT * FROM penerbit ORDER BY nama_penerbit")

    if not (kategori and pengarang and penerbit):
        st.warning("Lengkapi dulu data Kategori, Pengarang, dan Penerbit di tab sebelah.")
        return

    def nama_kategori(i: int) -> str:
        return next(r["nama_kategori"] for r in kategori if r["id_kategori"] == i)

    def nama_pengarang(i: int) -> str:
        return next(r["nama_pengarang"] for r in pengarang if r["id_pengarang"] == i)

    def nama_penerbit(i: int) -> str:
        return next(r["nama_penerbit"] for r in penerbit if r["id_penerbit"] == i)

    st.subheader("Tambah Buku")
    with st.form("form_tambah_buku", clear_on_submit=True):
        c1, c2 = st.columns(2)
        kode = c1.text_input("Kode buku", placeholder="BK-TI-001")
        isbn = c2.text_input("ISBN", placeholder="978-602-0000-00-0")
        judul = st.text_input("Judul buku")
        c1, c2, c3, c4 = st.columns(4)
        kat = c1.selectbox("Kategori", [r["id_kategori"] for r in kategori], format_func=nama_kategori)
        peng = c2.selectbox("Pengarang", [r["id_pengarang"] for r in pengarang], format_func=nama_pengarang)
        terbit = c3.selectbox("Penerbit", [r["id_penerbit"] for r in penerbit], format_func=nama_penerbit)
        stok = c4.number_input("Stok awal", min_value=0, step=1, value=1)
        submitted = st.form_submit_button("Simpan Buku", type="primary")

    if submitted:
        kode = kode.strip().upper()
        isbn = isbn.strip()
        judul = judul.strip()
        if not KODE_BUKU_RE.match(kode):
            st.error("Format kode buku harus BK-[KOD]-[NOMOR], contoh: BK-TI-001.")
        elif not judul:
            st.error("Judul buku wajib diisi.")
        elif not isbn:
            st.error("ISBN wajib diisi.")
        else:
            try:
                execute(
                    """INSERT INTO buku
                       (kode_buku, judul, ISBN, stok_awal, id_pengarang, id_penerbit, id_kategori)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (kode, judul, isbn, int(stok), peng, terbit, kat),
                )
                flash(f"Buku '{judul}' berhasil ditambahkan.")
                st.rerun()
            except sqlite3.IntegrityError as e:
                st.error(friendly_integrity(e))

    rows = query(
        """SELECT v.id_buku, v.kode_buku, v.judul, v.ISBN, v.stok_awal, v.stok_tersedia,
                  v.id_pengarang, v.id_penerbit, v.id_kategori,
                  k.nama_kategori, a.nama_pengarang, p.nama_penerbit
           FROM v_buku v
           JOIN kategori k ON k.id_kategori = v.id_kategori
           JOIN pengarang a ON a.id_pengarang = v.id_pengarang
           JOIN penerbit p ON p.id_penerbit = v.id_penerbit
           ORDER BY v.judul"""
    )

    st.divider()
    st.subheader("Daftar Buku")
    if not rows:
        st.info("Belum ada buku.")
        return

    df = frame(rows).rename(
        columns={
            "kode_buku": "Kode",
            "judul": "Judul",
            "ISBN": "ISBN",
            "nama_kategori": "Kategori",
            "nama_pengarang": "Pengarang",
            "nama_penerbit": "Penerbit",
            "stok_awal": "Stok Awal",
            "stok_tersedia": "Tersedia",
        }
    )
    c1, c2 = st.columns([2, 1])
    cari = c1.text_input("Cari judul / kode / ISBN", placeholder="Ketik untuk memfilter…")
    filter_kat = c2.selectbox(
        "Filter kategori", ["Semua"] + sorted(r["nama_kategori"] for r in kategori)
    )
    if cari:
        mask = (
            df["Judul"].str.contains(cari, case=False, na=False)
            | df["Kode"].str.contains(cari, case=False, na=False)
            | df["ISBN"].str.contains(cari, case=False, na=False)
        )
        df = df[mask]
    if filter_kat != "Semua":
        df = df[df["Kategori"] == filter_kat]

    st.dataframe(
        df[["Kode", "Judul", "ISBN", "Kategori", "Pengarang", "Penerbit", "Stok Awal", "Tersedia"]],
        hide_index=True,
        width="stretch",
    )
    st.caption("Stok tersedia dihitung otomatis: stok awal − buku yang sedang dipinjam.")

    with st.expander("✏️ Ubah / Hapus Buku"):
        pilihan = st.selectbox(
            "Pilih buku",
            options=[f"{r['kode_buku']} — {r['judul']}" for r in rows],
        )
        row = next(r for r in rows if f"{r['kode_buku']} — {r['judul']}" == pilihan)
        bid = row["id_buku"]

        with st.form(f"form_edit_buku_{bid}"):
            c1, c2 = st.columns(2)
            e_kode = c1.text_input("Kode buku", value=row["kode_buku"], key=f"ekode_{bid}")
            e_isbn = c2.text_input("ISBN", value=row["ISBN"], key=f"eisbn_{bid}")
            e_judul = st.text_input("Judul buku", value=row["judul"], key=f"ejudul_{bid}")
            c1, c2, c3, c4 = st.columns(4)
            e_kat = c1.selectbox(
                "Kategori",
                [r["id_kategori"] for r in kategori],
                index=[r["id_kategori"] for r in kategori].index(row["id_kategori"]),
                format_func=nama_kategori,
                key=f"ekat_{bid}",
            )
            e_peng = c2.selectbox(
                "Pengarang",
                [r["id_pengarang"] for r in pengarang],
                index=[r["id_pengarang"] for r in pengarang].index(row["id_pengarang"]),
                format_func=nama_pengarang,
                key=f"epeng_{bid}",
            )
            e_terbit = c3.selectbox(
                "Penerbit",
                [r["id_penerbit"] for r in penerbit],
                index=[r["id_penerbit"] for r in penerbit].index(row["id_penerbit"]),
                format_func=nama_penerbit,
                key=f"eterbit_{bid}",
            )
            e_stok = c4.number_input(
                "Stok awal", min_value=0, step=1, value=int(row["stok_awal"]), key=f"estok_{bid}"
            )
            simpan = st.form_submit_button("Simpan Perubahan", type="primary")

        if simpan:
            e_kode = e_kode.strip().upper()
            if not KODE_BUKU_RE.match(e_kode):
                st.error("Format kode buku harus BK-[KOD]-[NOMOR], contoh: BK-TI-001.")
            elif not e_judul.strip() or not e_isbn.strip():
                st.error("Judul dan ISBN wajib diisi.")
            else:
                try:
                    execute(
                        """UPDATE buku SET kode_buku = ?, judul = ?, ISBN = ?, stok_awal = ?,
                           id_pengarang = ?, id_penerbit = ?, id_kategori = ?
                           WHERE id_buku = ?""",
                        (e_kode, e_judul.strip(), e_isbn.strip(), int(e_stok), e_peng, e_terbit, e_kat, bid),
                    )
                    flash(f"Buku '{e_judul.strip()}' berhasil diperbarui.")
                    st.rerun()
                except sqlite3.IntegrityError as e:
                    st.error(friendly_integrity(e))

        st.divider()
        aktif = query(
            "SELECT COUNT(*) AS c FROM v_detail WHERE id_buku = ? AND id_pengembalian IS NULL",
            (bid,),
        )[0]["c"]
        st.caption(
            "Buku hanya bisa dihapus jika belum pernah dipakai dalam transaksi."
            + (f" Saat ini sedang dipinjam {aktif} kali." if aktif else "")
        )
        if st.button("Hapus buku ini", key=f"hapus_buku_{bid}"):
            if aktif:
                st.error("Buku sedang dipinjam sehingga tidak boleh dihapus.")
            else:
                try:
                    execute("DELETE FROM buku WHERE id_buku = ?", (bid,))
                    flash(f"Buku '{row['judul']}' berhasil dihapus.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Buku sudah memiliki riwayat transaksi sehingga tidak boleh dihapus.")


def crud_lookup(label: str, table: str, pk: str, col: str, fk_buku: str, key: str) -> None:
    st.subheader(f"Tambah {label}")
    with st.form(f"form_add_{key}", clear_on_submit=True):
        nama = st.text_input(f"Nama {label}")
        submitted = st.form_submit_button("Tambah", type="primary")

    if submitted:
        nama = nama.strip()
        if not nama:
            st.error(f"Nama {label} wajib diisi.")
        else:
            try:
                execute(f"INSERT INTO {table} ({col}) VALUES (?)", (nama,))
                flash(f"{label} '{nama}' berhasil ditambahkan.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error(f"{label} '{nama}' sudah ada.")

    rows = query(f"SELECT * FROM {table} ORDER BY {col}")
    st.divider()
    st.subheader(f"Daftar {label}")
    if not rows:
        st.info(f"Belum ada data {label}.")
        return

    st.dataframe(
        frame(rows).rename(columns={col: label})[[label]],
        hide_index=True,
        width="stretch",
    )

    st.markdown(f"**Ubah / Hapus {label}**")
    ids = [r[pk] for r in rows]
    chosen = st.selectbox(
        label,
        ids,
        format_func=lambda i: next(r[col] for r in rows if r[pk] == i),
        key=f"pilih_{key}",
    )
    current = next(r[col] for r in rows if r[pk] == chosen)
    new_name = st.text_input("Nama baru", value=current, key=f"ubah_{key}_{chosen}")
    c1, c2 = st.columns([1, 1])
    if c1.button("Simpan Perubahan", key=f"simpan_{key}"):
        new_name = new_name.strip()
        if not new_name:
            st.error(f"Nama {label} wajib diisi.")
        else:
            try:
                execute(f"UPDATE {table} SET {col} = ? WHERE {pk} = ?", (new_name, chosen))
                flash(f"{label} berhasil diperbarui.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error(f"{label} '{new_name}' sudah ada.")
    if c2.button("Hapus", key=f"hapus_{key}"):
        used = query(f"SELECT COUNT(*) AS c FROM buku WHERE {fk_buku} = ?", (chosen,))[0]["c"]
        if used:
            st.error(f"{label} tidak bisa dihapus karena dipakai oleh {used} buku.")
        else:
            execute(f"DELETE FROM {table} WHERE {pk} = ?", (chosen,))
            flash(f"{label} '{current}' berhasil dihapus.")
            st.rerun()


# ---------------------------------------------------------------------------
# Halaman: Master Peminjam
# ---------------------------------------------------------------------------
def page_peminjam() -> None:
    st.title("👥 Master Data Peminjam")

    st.subheader("Tambah Peminjam")
    with st.form("form_tambah_peminjam", clear_on_submit=True):
        c1, c2 = st.columns(2)
        nim = c1.text_input("NIM", placeholder="4.52.24.3.10")
        nama = c2.text_input("Nama lengkap")
        c1, c2, c3 = st.columns(3)
        kelas = c1.text_input("Kelas", placeholder="TI-2A")
        prodi = c2.text_input("Prodi", placeholder="D4 Teknik Informatika")
        jurusan = c3.text_input("Jurusan", placeholder="Teknik Elektro")
        wa = st.text_input("No. WhatsApp", placeholder="08xxxxxxxxxx")
        submitted = st.form_submit_button("Simpan Peminjam", type="primary")

    if submitted:
        nim = nim.strip()
        nama = nama.strip()
        kelas = kelas.strip()
        prodi = prodi.strip()
        jurusan = jurusan.strip()
        wa_bersih = re.sub(r"\D", "", wa)
        if not nim or " " in nim:
            st.error("NIM wajib diisi dan tidak boleh mengandung spasi.")
        elif not all([nama, kelas, prodi, jurusan]):
            st.error("Nama, kelas, prodi, dan jurusan wajib diisi.")
        elif len(wa_bersih) < 9:
            st.error("Nomor WhatsApp tidak valid.")
        else:
            try:
                execute(
                    """INSERT INTO peminjam (nim, nama, kelas, prodi, jurusan, no_telp_wa)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (nim, nama, kelas, prodi, jurusan, wa.strip()),
                )
                flash(f"Peminjam '{nama}' berhasil ditambahkan.")
                st.rerun()
            except sqlite3.IntegrityError as e:
                st.error(friendly_integrity(e))

    rows = query("SELECT * FROM peminjam ORDER BY nama")
    st.divider()
    st.subheader("Daftar Peminjam")
    if not rows:
        st.info("Belum ada data peminjam.")
        return

    df = frame(rows).rename(
        columns={
            "nim": "NIM",
            "nama": "Nama",
            "kelas": "Kelas",
            "prodi": "Prodi",
            "jurusan": "Jurusan",
            "no_telp_wa": "No. WhatsApp",
        }
    )
    cari = st.text_input("Cari NIM / nama", placeholder="Ketik untuk memfilter…")
    if cari:
        mask = (
            df["NIM"].str.contains(cari, case=False, na=False)
            | df["Nama"].str.contains(cari, case=False, na=False)
        )
        df = df[mask]
    st.dataframe(df, hide_index=True, width="stretch")

    with st.expander("✏️ Ubah / Hapus Peminjam"):
        pilihan = st.selectbox(
            "Pilih peminjam",
            options=[f"{r['nim']} — {r['nama']}" for r in rows],
        )
        row = next(r for r in rows if f"{r['nim']} — {r['nama']}" == pilihan)
        nim = row["nim"]

        with st.form(f"form_edit_peminjam_{nim}"):
            c1, c2 = st.columns(2)
            e_nim = c1.text_input("NIM", value=row["nim"], key=f"enim_{nim}")
            e_nama = c2.text_input("Nama lengkap", value=row["nama"], key=f"enama_{nim}")
            c1, c2, c3 = st.columns(3)
            e_kelas = c1.text_input("Kelas", value=row["kelas"], key=f"ekelas_{nim}")
            e_prodi = c2.text_input("Prodi", value=row["prodi"], key=f"eprodi_{nim}")
            e_jurusan = c3.text_input("Jurusan", value=row["jurusan"], key=f"ejurusan_{nim}")
            e_wa = st.text_input("No. WhatsApp", value=row["no_telp_wa"], key=f"ewa_{nim}")
            simpan = st.form_submit_button("Simpan Perubahan", type="primary")

        if simpan:
            e_nim = e_nim.strip()
            e_nama = e_nama.strip()
            if not e_nim or " " in e_nim:
                st.error("NIM wajib diisi dan tidak boleh mengandung spasi.")
            elif not all([e_nama, e_kelas.strip(), e_prodi.strip(), e_jurusan.strip()]):
                st.error("Nama, kelas, prodi, dan jurusan wajib diisi.")
            elif len(re.sub(r"\D", "", e_wa)) < 9:
                st.error("Nomor WhatsApp tidak valid.")
            else:
                try:
                    execute(
                        """UPDATE peminjam SET nim = ?, nama = ?, kelas = ?, prodi = ?,
                           jurusan = ?, no_telp_wa = ? WHERE nim = ?""",
                        (e_nim, e_nama, e_kelas.strip(), e_prodi.strip(), e_jurusan.strip(), e_wa.strip(), nim),
                    )
                    flash(f"Peminjam '{e_nama}' berhasil diperbarui.")
                    st.rerun()
                except sqlite3.IntegrityError as e:
                    st.error(friendly_integrity(e))

        st.divider()
        aktif = query(
            "SELECT COUNT(*) AS c FROM v_detail WHERE nim = ? AND id_pengembalian IS NULL",
            (nim,),
        )[0]["c"]
        riwayat = query(
            "SELECT COUNT(*) AS c FROM transaksi WHERE nim = ?", (nim,)
        )[0]["c"]
        st.caption(
            "Peminjam hanya bisa dihapus jika belum memiliki transaksi."
            + (f" Saat ini ada {aktif} buku yang belum dikembalikan." if aktif else "")
        )
        if st.button("Hapus peminjam ini", key=f"hapus_peminjam_{nim}"):
            if aktif:
                st.error("Peminjam masih memiliki buku yang belum dikembalikan.")
            elif riwayat:
                st.error("Peminjam sudah memiliki riwayat transaksi sehingga tidak boleh dihapus.")
            else:
                execute("DELETE FROM peminjam WHERE nim = ?", (nim,))
                flash(f"Peminjam '{row['nama']}' berhasil dihapus.")
                st.rerun()


# ---------------------------------------------------------------------------
# Halaman: Peminjaman
# ---------------------------------------------------------------------------
def page_peminjaman() -> None:
    st.title("🔄 Transaksi Peminjaman")

    peminjam = query("SELECT * FROM peminjam ORDER BY nama")
    buku = query(
        "SELECT id_buku, kode_buku, judul, stok_tersedia FROM v_buku WHERE stok_tersedia > 0 ORDER BY judul"
    )

    if not peminjam:
        st.warning("Belum ada data peminjam. Tambahkan dulu di menu Peminjam.")
        return
    if not buku:
        st.warning("Tidak ada buku dengan stok tersedia. Tambahkan stok buku di menu Master Buku.")
        return

    def label_peminjam(nim: str) -> str:
        r = next(x for x in peminjam if x["nim"] == nim)
        return f"{nim} — {r['nama']}"

    def label_buku(bid: int) -> str:
        r = next(x for x in buku if x["id_buku"] == bid)
        return f"{r['kode_buku']} — {r['judul']} (stok {r['stok_tersedia']})"

    st.subheader("Catat Peminjaman Baru")
    with st.form("form_pinjam", clear_on_submit=True):
        c1, c2 = st.columns([2, 1])
        nim = c1.selectbox("Peminjam", [r["nim"] for r in peminjam], format_func=label_peminjam)
        tgl_pinjam = c2.date_input("Tanggal pinjam", value=date.today(), max_value=date.today())
        pilihan = st.multiselect(
            f"Buku (maks. {MAX_BUKU_PER_TRANSAKSI})",
            options=[r["id_buku"] for r in buku],
            format_func=label_buku,
        )
        submitted = st.form_submit_button("Simpan Peminjaman", type="primary")

    st.caption(
        f"Tenggat otomatis {LAMA_PINJAM_HARI} hari setelah tanggal pinjam. "
        f"Denda keterlambatan {rupiah(DENDA_PER_HARI)} per hari."
    )

    if submitted:
        if not pilihan:
            st.error("Pilih minimal satu buku.")
        elif len(pilihan) > MAX_BUKU_PER_TRANSAKSI:
            st.error(f"Maksimal {MAX_BUKU_PER_TRANSAKSI} buku per transaksi.")
        else:
            try:
                info = create_peminjaman(nim, pilihan, tgl_pinjam)
                st.success(
                    f"Peminjaman **{info['kode']}** berhasil dicatat. "
                    f"Tenggat: **{tgl_id(info['tenggat'])}**."
                )
                pesan = (
                    f"Halo {info['nama']}, peminjaman buku di Perpustakaan Kampus telah dicatat.\n"
                    f"Kode transaksi: {info['kode']}\n"
                    f"Buku: {', '.join(info['judul'])}\n"
                    f"Tenggat pengembalian: {tgl_id(info['tenggat'])}\n"
                    f"Mohon kembalikan tepat waktu. Denda {rupiah(DENDA_PER_HARI)}/hari."
                )
                link = wa_link(info["wa"], pesan)
                if link:
                    st.link_button("💬 Kirim Konfirmasi via WhatsApp", link)
            except ValueError as e:
                st.error(str(e))
            except sqlite3.IntegrityError as e:
                st.error(friendly_integrity(e))

    st.divider()
    render_peminjaman_aktif()


def create_peminjaman(nim: str, buku_ids: list[int], tgl_pinjam: date) -> dict:
    with db() as conn:
        peminjam = conn.execute("SELECT * FROM peminjam WHERE nim = ?", (nim,)).fetchone()
        if not peminjam:
            raise ValueError("NIM tidak ditemukan.")

        judul_buku = []
        for bid in buku_ids:
            b = conn.execute(
                "SELECT kode_buku, judul, stok_tersedia FROM v_buku WHERE id_buku = ?", (bid,)
            ).fetchone()
            if not b:
                raise ValueError("Buku tidak ditemukan.")
            if b["stok_tersedia"] <= 0:
                raise ValueError(f"Stok buku '{b['judul']}' habis.")
            judul_buku.append(b["judul"])

        tgl_tenggat = tgl_pinjam + timedelta(days=LAMA_PINJAM_HARI)
        prefix = f"TRX-PJM-{tgl_pinjam.strftime('%Y%m%d')}-"
        seq = conn.execute(
            "SELECT COUNT(*) AS c FROM transaksi WHERE kode_transaksi LIKE ?", (prefix + "%",)
        ).fetchone()["c"] + 1
        kode = f"{prefix}{seq:03d}"
        while conn.execute(
            "SELECT 1 FROM transaksi WHERE kode_transaksi = ?", (kode,)
        ).fetchone():
            seq += 1
            kode = f"{prefix}{seq:03d}"

        tid = conn.execute(
            """INSERT INTO transaksi (kode_transaksi, nim, tgl_pinjam, tgl_tenggat)
               VALUES (?, ?, ?, ?)""",
            (kode, nim, tgl_pinjam.isoformat(), tgl_tenggat.isoformat()),
        ).lastrowid
        conn.executemany(
            "INSERT INTO detail_transaksi (id_transaksi, id_buku) VALUES (?, ?)",
            [(tid, bid) for bid in buku_ids],
        )
        return {
            "kode": kode,
            "tenggat": tgl_tenggat,
            "nama": peminjam["nama"],
            "wa": peminjam["no_telp_wa"],
            "judul": judul_buku,
        }


def render_peminjaman_aktif() -> None:
    rows = query(
        """SELECT * FROM v_detail WHERE id_pengembalian IS NULL
           ORDER BY tgl_tenggat, kode_transaksi"""
    )
    st.subheader("Peminjaman Aktif")
    if not rows:
        st.info("Tidak ada buku yang sedang dipinjam.")
        return

    groups: dict[int, list[sqlite3.Row]] = {}
    for r in rows:
        groups.setdefault(r["id_transaksi"], []).append(r)

    today = date.today()
    for items in groups.values():
        head = items[0]
        telat = max(0, (today - date.fromisoformat(head["tgl_tenggat"])).days)
        status = f"⚠️ Terlambat {telat} hari" if telat else "✅ Dalam tenggat"
        label = f"{head['kode_transaksi']} · {head['nama_peminjam']} · {status}"
        with st.expander(label):
            c1, c2, c3 = st.columns(3)
            c1.write(f"**NIM:** {head['nim']}")
            c2.write(f"**Tgl pinjam:** {tgl_id(head['tgl_pinjam'])}")
            c3.write(f"**Tenggat:** {tgl_id(head['tgl_tenggat'])}")
            st.write("**Buku:**")
            for r in items:
                st.write(f"- {r['kode_buku']} — {r['judul']}")
            if telat:
                st.warning(
                    f"Denda berjalan: **{rupiah(telat * DENDA_PER_HARI)}** "
                    f"({telat} hari × {rupiah(DENDA_PER_HARI)})"
                )
            pesan = (
                f"Halo {head['nama_peminjam']}, pengingat dari Perpustakaan Kampus.\n"
                f"Transaksi {head['kode_transaksi']} memiliki tenggat "
                f"{tgl_id(head['tgl_tenggat'])}.\n"
                f"Buku: {', '.join(r['judul'] for r in items)}.\n"
                f"Mohon kembalikan tepat waktu. Denda {rupiah(DENDA_PER_HARI)}/hari."
            )
            link = wa_link(head["no_telp_wa"], pesan)
            if link:
                st.link_button("💬 Kirim Pengingat WhatsApp", link, key=f"wa_{head['id_transaksi']}")


# ---------------------------------------------------------------------------
# Halaman: Pengembalian & Denda
# ---------------------------------------------------------------------------
def page_pengembalian() -> None:
    st.title("📥 Pengembalian & Denda")

    aktif = query(
        """SELECT * FROM v_detail WHERE id_pengembalian IS NULL
           ORDER BY tgl_tenggat, kode_transaksi"""
    )

    if not aktif:
        st.success("Tidak ada buku yang sedang dipinjam.")
    else:
        st.subheader("Catat Pengembalian")
        pilihan = st.selectbox(
            "Pilih buku yang dikembalikan",
            options=[r["id_detail_transaksi"] for r in aktif],
            format_func=lambda i: next(
                f"{r['kode_transaksi']} — {r['judul']} ({r['nama_peminjam']})"
                for r in aktif
                if r["id_detail_transaksi"] == i
            ),
        )
        row = next(r for r in aktif if r["id_detail_transaksi"] == pilihan)
        tenggat = date.fromisoformat(row["tgl_tenggat"])
        telat_hari_ini = max(0, (date.today() - tenggat).days)

        c1, c2, c3 = st.columns(3)
        c1.metric("Tanggal Pinjam", tgl_id(row["tgl_pinjam"]))
        c2.metric("Tenggat", tgl_id(row["tgl_tenggat"]))
        c3.metric("Denda Jika Kembali Hari Ini", rupiah(telat_hari_ini * DENDA_PER_HARI))

        with st.form("form_kembali"):
            c1, c2 = st.columns(2)
            tgl_kembali = c1.date_input(
                "Tanggal kembali",
                value=date.today(),
                min_value=date.fromisoformat(row["tgl_pinjam"]),
                max_value=date.today(),
            )
            kondisi = c2.selectbox(
                "Kondisi buku", ["Baik", "Rusak Ringan", "Rusak Berat", "Hilang"]
            )
            submitted = st.form_submit_button("Proses Pengembalian", type="primary")

        if submitted:
            telat = max(0, (tgl_kembali - tenggat).days)
            denda = telat * DENDA_PER_HARI
            status = STATUS_MENUNGGU if denda > 0 else STATUS_SELESAI
            try:
                execute(
                    """INSERT INTO pengembalian
                       (id_detail_transaksi, tgl_kembali, kondisi_buku, status, denda)
                       VALUES (?, ?, ?, ?, ?)""",
                    (row["id_detail_transaksi"], tgl_kembali.isoformat(), kondisi, status, denda),
                )
                if denda:
                    flash(
                        f"Buku '{row['judul']}' dikembalikan. Terlambat {telat} hari, "
                        f"denda {rupiah(denda)} menunggu pelunasan."
                    )
                else:
                    flash(f"Buku '{row['judul']}' dikembalikan tepat waktu. Tidak ada denda.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("Buku ini sudah tercatat kembali.")

    st.divider()
    render_tunggakan_denda()

    st.divider()
    render_riwayat_pengembalian()


def render_tunggakan_denda() -> None:
    st.subheader("💸 Denda Menunggu Pelunasan")
    rows = query(
        """SELECT pg.id_pengembalian, pg.denda, pg.tgl_kembali,
                  t.kode_transaksi, p.nim, p.nama, b.judul
           FROM pengembalian pg
           JOIN detail_transaksi d ON d.id_detail_transaksi = pg.id_detail_transaksi
           JOIN transaksi t ON t.id_transaksi = d.id_transaksi
           JOIN peminjam p ON p.nim = t.nim
           JOIN buku b ON b.id_buku = d.id_buku
           WHERE pg.status = ?
           ORDER BY pg.tgl_kembali""",
        (STATUS_MENUNGGU,),
    )
    if not rows:
        st.success("Tidak ada denda yang menunggu pelunasan.")
        return

    for r in rows:
        c1, c2 = st.columns([4, 1])
        c1.write(
            f"**{r['nama']}** ({r['nim']}) — {r['judul']}  \n"
            f"{r['kode_transaksi']} · kembali {tgl_id(r['tgl_kembali'])} · "
            f"denda **{rupiah(r['denda'])}**"
        )
        if c2.button("Tandai Lunas", key=f"lunas_{r['id_pengembalian']}", type="primary"):
            execute(
                """UPDATE pengembalian
                   SET status = ?, tgl_pembayaran_denda = ?
                   WHERE id_pengembalian = ?""",
                (STATUS_SELESAI, date.today().isoformat(), r["id_pengembalian"]),
            )
            flash(f"Denda {rupiah(r['denda'])} dari {r['nama']} telah dilunasi.")
            st.rerun()


def render_riwayat_pengembalian() -> None:
    st.subheader("📜 Riwayat Pengembalian")
    rows = query(
        """SELECT * FROM v_detail WHERE id_pengembalian IS NOT NULL
           ORDER BY tgl_kembali DESC, kode_transaksi"""
    )
    if not rows:
        st.info("Belum ada riwayat pengembalian.")
        return

    df = frame(rows)
    df["tgl_pinjam"] = df["tgl_pinjam"].apply(tgl_id)
    df["tgl_tenggat"] = df["tgl_tenggat"].apply(tgl_id)
    df["tgl_kembali"] = df["tgl_kembali"].apply(tgl_id)
    df["denda"] = df["denda"].apply(rupiah)
    df["status"] = df["status"].apply(status_denda)
    df["tgl_pembayaran_denda"] = df["tgl_pembayaran_denda"].apply(
        lambda v: tgl_id(v) if isinstance(v, str) and v else "-"
    )
    df = df.rename(
        columns={
            "kode_transaksi": "Kode Transaksi",
            "nim": "NIM",
            "nama_peminjam": "Peminjam",
            "judul": "Judul Buku",
            "tgl_pinjam": "Tgl Pinjam",
            "tgl_tenggat": "Tenggat",
            "tgl_kembali": "Tgl Kembali",
            "kondisi_buku": "Kondisi",
            "status": "Status",
            "denda": "Denda",
            "tgl_pembayaran_denda": "Tgl Bayar Denda",
        }
    )
    st.dataframe(
        df[["Kode Transaksi", "NIM", "Peminjam", "Judul Buku", "Tgl Pinjam", "Tenggat",
            "Tgl Kembali", "Kondisi", "Denda", "Status", "Tgl Bayar Denda"]],
        hide_index=True,
        width="stretch",
    )


# ---------------------------------------------------------------------------
# Halaman: Dana Denda
# ---------------------------------------------------------------------------
def page_dana() -> None:
    st.title("💰 Dana Denda")
    st.caption("Pantau denda terkumpul, tunggakan, dan pengeluaran dana.")

    today = date.today()
    m = query(
        """
        SELECT
          (SELECT COALESCE(SUM(denda), 0) FROM pengembalian) AS total_denda,
          (SELECT COALESCE(SUM(denda), 0) FROM pengembalian
            WHERE tgl_pembayaran_denda IS NOT NULL) AS terkumpul,
          (SELECT COALESCE(SUM(denda), 0) FROM pengembalian
            WHERE status = ?) AS tunggakan,
          (SELECT COALESCE(SUM(jumlah), 0) FROM pengeluaran_dana) AS pengeluaran
        """,
        (STATUS_MENUNGGU,),
    )[0]
    saldo = m["terkumpul"] - m["pengeluaran"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Denda", rupiah(m["total_denda"]))
    c2.metric("Terkumpul", rupiah(m["terkumpul"]))
    c3.metric("Tunggakan", rupiah(m["tunggakan"]))
    c4.metric("Saldo Dana", rupiah(saldo))

    st.divider()
    st.subheader("Catat Pengeluaran Dana")
    with st.form("form_pengeluaran", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 2, 1])
        tanggal = c1.date_input("Tanggal", value=today, max_value=today)
        keterangan = c2.text_input("Keterangan", placeholder="Contoh: Pembelian sampul buku")
        jumlah = c3.number_input("Jumlah (Rp)", min_value=0, step=1000, value=0)
        submitted = st.form_submit_button("Simpan Pengeluaran", type="primary")

    if submitted:
        if not keterangan.strip():
            st.error("Keterangan wajib diisi.")
        elif jumlah <= 0:
            st.error("Jumlah pengeluaran harus lebih dari 0.")
        elif jumlah > saldo:
            st.error(
                f"Pengeluaran melebihi saldo dana. Saldo saat ini {rupiah(saldo)}."
            )
        else:
            execute(
                "INSERT INTO pengeluaran_dana (tanggal, keterangan, jumlah) VALUES (?, ?, ?)",
                (tanggal.isoformat(), keterangan.strip(), int(jumlah)),
            )
            flash(f"Pengeluaran {rupiah(jumlah)} berhasil dicatat.")
            st.rerun()

    rows = query("SELECT * FROM pengeluaran_dana ORDER BY tanggal DESC, id_pengeluaran DESC")
    st.divider()
    st.subheader("Riwayat Pengeluaran")
    if not rows:
        st.info("Belum ada pengeluaran dana.")
        return

    df = frame(rows).rename(
        columns={"tanggal": "Tanggal", "keterangan": "Keterangan", "jumlah": "Jumlah"}
    )
    df["Tanggal"] = df["Tanggal"].apply(tgl_id)
    df["Jumlah"] = df["Jumlah"].apply(rupiah)
    st.dataframe(df[["Tanggal", "Keterangan", "Jumlah"]], hide_index=True, width="stretch")

    pilihan = st.selectbox(
        "Hapus pengeluaran",
        options=[r["id_pengeluaran"] for r in rows],
        format_func=lambda i: next(
            f"{tgl_id(r['tanggal'])} — {r['keterangan']} ({rupiah(r['jumlah'])})"
            for r in rows
            if r["id_pengeluaran"] == i
        ),
    )
    if st.button("Hapus pengeluaran ini"):
        execute("DELETE FROM pengeluaran_dana WHERE id_pengeluaran = ?", (pilihan,))
        flash("Pengeluaran dana berhasil dihapus.")
        st.rerun()


# ---------------------------------------------------------------------------
# Aplikasi
# ---------------------------------------------------------------------------
def inject_css() -> None:
    st.markdown(
        """
        <style>
            .block-container { padding-top: 2rem; padding-bottom: 3rem; }
            [data-testid="stSidebar"] { background: #f3f7f3; }
            [data-testid="stMetric"] {
                background: #ffffff;
                border: 1px solid #e2e8e2;
                border-radius: 12px;
                padding: 14px 16px;
            }
            [data-testid="stMetricValue"] { font-size: 1.45rem; }
            [data-testid="stMetricLabel"] { font-size: 0.85rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Perpustakaan Kampus",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    init_db()

    st.sidebar.title("📚 Perpustakaan")
    st.sidebar.caption("Sistem Sirkulasi Kampus")
    menu = st.sidebar.radio(
        "Menu",
        [
            "Dashboard",
            "Master Buku",
            "Peminjam",
            "Peminjaman",
            "Pengembalian & Denda",
            "Dana Denda",
        ],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    st.sidebar.caption(
        f"Tenggat {LAMA_PINJAM_HARI} hari · Denda {rupiah(DENDA_PER_HARI)}/hari · "
        f"Maks. {MAX_BUKU_PER_TRANSAKSI} buku"
    )
    st.sidebar.caption("Kelompok 3 · Pemrograman Bisnis & Perancangan Sistem Administrasi")

    show_flash()

    pages = {
        "Dashboard": page_dashboard,
        "Master Buku": page_buku,
        "Peminjam": page_peminjam,
        "Peminjaman": page_peminjaman,
        "Pengembalian & Denda": page_pengembalian,
        "Dana Denda": page_dana,
    }
    pages[menu]()


if __name__ == "__main__":
    main()
