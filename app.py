import calendar
import sqlite3
from datetime import date

# from flask import Flask, flash, g, redirect, render_template, request, url_for
from flask import Flask, abort, flash, g, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = "ganti-dengan-kunci-rahasia"
DB = "cashflow.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transaksi (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tanggal    TEXT    NOT NULL,
    tipe       TEXT    NOT NULL CHECK (tipe IN ('masuk', 'keluar')),
    kategori   TEXT    NOT NULL,
    keterangan TEXT,
    jumlah     INTEGER NOT NULL CHECK (jumlah > 0)
);
CREATE INDEX IF NOT EXISTS idx_transaksi_tanggal ON transaksi (tanggal);

CREATE TABLE IF NOT EXISTS tabungan (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nama    TEXT    NOT NULL,
    target  INTEGER NOT NULL CHECK (target > 0),
    tenggat TEXT                                    -- YYYY-MM-DD, boleh kosong
);
CREATE TABLE IF NOT EXISTS setoran_tabungan (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tabungan_id INTEGER NOT NULL REFERENCES tabungan (id),
    tanggal     TEXT    NOT NULL,
    jumlah      INTEGER NOT NULL CHECK (jumlah > 0),
    catatan     TEXT
);
CREATE TABLE IF NOT EXISTS anggaran (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kategori TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    batas    INTEGER NOT NULL CHECK (batas > 0)      -- batas per bulan, berlaku tiap bulan
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


@app.template_filter("rupiah")
def rupiah(n):
    n = int(n)
    teks = f"{abs(n):,}".replace(",", ".")
    return f"-Rp {teks}" if n < 0 else f"Rp {teks}"


@app.route("/")
def index():
    bulan = request.args.get("bulan") or date.today().strftime("%Y-%m")
    db = get_db()

    transaksi = db.execute(
        """
        SELECT * FROM (
            SELECT id, tanggal, tipe, kategori, keterangan, jumlah,
                   SUM(CASE WHEN tipe = 'masuk' THEN jumlah ELSE -jumlah END)
                       OVER (ORDER BY tanggal, id) AS saldo
            FROM transaksi
        )
        WHERE substr(tanggal, 1, 7) = ?
        ORDER BY tanggal DESC, id DESC
        """,
        (bulan,),
    ).fetchall()

    total = db.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN tipe = 'masuk'  THEN jumlah END), 0) AS masuk,
               COALESCE(SUM(CASE WHEN tipe = 'keluar' THEN jumlah END), 0) AS keluar
        FROM transaksi WHERE substr(tanggal, 1, 7) = ?
        """,
        (bulan,),
    ).fetchone()

    saldo_awal = db.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN tipe = 'masuk' THEN jumlah ELSE -jumlah END), 0)
        FROM transaksi WHERE substr(tanggal, 1, 7) < ?
        """,
        (bulan,),
    ).fetchone()[0]

    kategori = db.execute(
        """
        SELECT kategori, SUM(jumlah) AS total FROM transaksi
        WHERE tipe = 'keluar' AND substr(tanggal, 1, 7) = ?
        GROUP BY kategori ORDER BY total DESC
        """,
        (bulan,),
    ).fetchall()

    daftar_kategori = [
        r[0] for r in db.execute("SELECT DISTINCT kategori FROM transaksi ORDER BY kategori")
    ]

    return render_template(
        "index.html",
        bulan=bulan,
        hari_ini=date.today().isoformat(),
        transaksi=transaksi,
        masuk=total["masuk"],
        keluar=total["keluar"],
        saldo_awal=saldo_awal,
        saldo_akhir=saldo_awal + total["masuk"] - total["keluar"],
        kategori=kategori,
        maks_kategori=kategori[0]["total"] if kategori else 1,
        daftar_kategori=daftar_kategori,
    )


@app.post("/tambah")
def tambah():
    f = request.form
    try:
        jumlah = int(f["jumlah"].replace(".", "").replace(",", "").strip())
        assert jumlah > 0 and f["tipe"] in ("masuk", "keluar")
        date.fromisoformat(f["tanggal"])
        kategori = f["kategori"].strip()
        assert kategori
    except (ValueError, KeyError, AssertionError):
        flash("Data tidak valid. Periksa tanggal, kategori, dan jumlah.")
        return redirect(url_for("index"))

    db = get_db()
    db.execute(
        "INSERT INTO transaksi (tanggal, tipe, kategori, keterangan, jumlah) VALUES (?, ?, ?, ?, ?)",
        (f["tanggal"], f["tipe"], kategori, f.get("keterangan", "").strip(), jumlah),
    )
    db.commit()
    if f["tipe"] == "keluar":
        a = db.execute("SELECT batas FROM anggaran WHERE kategori = ?", (kategori,)).fetchone()
        if a:
            terpakai = db.execute(
                "SELECT COALESCE(SUM(jumlah), 0) FROM transaksi "
                "WHERE tipe = 'keluar' AND lower(kategori) = lower(?) AND substr(tanggal, 1, 7) = ?",
                (kategori, f["tanggal"][:7]),
            ).fetchone()[0]
            if terpakai > a["batas"]:
                flash(f"Anggaran {kategori} terlampaui. Terpakai {rupiah(terpakai)} dari batas {rupiah(a['batas'])}.")
            elif terpakai * 100 >= a["batas"] * 80:
                flash(f"Anggaran {kategori} hampir habis. Terpakai {rupiah(terpakai)} dari batas {rupiah(a['batas'])}.")
    return redirect(url_for("index", bulan=f["tanggal"][:7]))


@app.post("/hapus/<int:id>")
def hapus(id):
    db = get_db()
    db.execute("DELETE FROM transaksi WHERE id = ?", (id,))
    db.commit()
    return redirect(request.referrer or url_for("index"))

NAMA_BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
              "Agustus", "September", "Oktober", "November", "Desember"]


def total_per_kategori(db, tipe, tahun):
    return db.execute(
        """
        SELECT kategori, SUM(jumlah) AS total FROM transaksi
        WHERE tipe = ? AND substr(tanggal, 1, 4) = ?
        GROUP BY kategori ORDER BY total DESC
        """,
        (tipe, str(tahun)),
    ).fetchall()


@app.route("/laporan")
def laporan():
    tahun = request.args.get("tahun", type=int) or date.today().year
    db = get_db()

    baris = db.execute(
        """
        SELECT substr(tanggal, 6, 2) AS bln,
               COALESCE(SUM(CASE WHEN tipe = 'masuk'  THEN jumlah END), 0) AS masuk,
               COALESCE(SUM(CASE WHEN tipe = 'keluar' THEN jumlah END), 0) AS keluar,
               COALESCE(SUM(CASE WHEN tipe = 'keluar' AND lower(kategori) = 'tabungan'
                                 THEN jumlah END), 0) AS nabung
        FROM transaksi WHERE substr(tanggal, 1, 4) = ?
        GROUP BY bln
        """,
        (str(tahun),),
    ).fetchall()
    data = {r["bln"]: r for r in baris}

    per_bulan = []
    for i in range(1, 13):
        r = data.get(f"{i:02d}")
        masuk = r["masuk"] if r else 0
        keluar = r["keluar"] if r else 0
        nabung = r["nabung"] if r else 0
        per_bulan.append({
            "nama": NAMA_BULAN[i - 1],
            "singkat": NAMA_BULAN[i - 1][:3],
            "kode": f"{tahun}-{i:02d}",
            "masuk": masuk,
            "keluar": keluar,
            "selisih": masuk - keluar,
            "tabungan": nabung,
            "keluar_lain": keluar - nabung,
        })

    total_masuk = sum(b["masuk"] for b in per_bulan)
    total_keluar = sum(b["keluar"] for b in per_bulan)
    bulan_aktif = sum(1 for b in per_bulan if b["masuk"] or b["keluar"])

    saldo_akhir = db.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN tipe = 'masuk' THEN jumlah ELSE -jumlah END), 0)
        FROM transaksi WHERE substr(tanggal, 1, 4) <= ?
        """,
        (str(tahun),),
    ).fetchone()[0]

    keluar_kat = total_per_kategori(db, "keluar", tahun)
    masuk_kat = total_per_kategori(db, "masuk", tahun)

    return render_template(
        "laporan.html",
        tahun=tahun,
        per_bulan=per_bulan,
        # maks_bulan=max([b["masuk"] for b in per_bulan] + [b["keluar"] for b in per_bulan] + [1]),
        maks_bulan=max([b["masuk"] for b in per_bulan] + [b["keluar_lain"] for b in per_bulan] + [b["tabungan"] for b in per_bulan] + [1]),
        total_masuk=total_masuk,
        total_keluar=total_keluar,
        rata_keluar=total_keluar // bulan_aktif if bulan_aktif else 0,
        saldo_akhir=saldo_akhir,
        keluar_kat=keluar_kat,
        masuk_kat=masuk_kat,
        maks_keluar=keluar_kat[0]["total"] if keluar_kat else 1,
        maks_masuk=masuk_kat[0]["total"] if masuk_kat else 1,
    )

def ke_angka(teks):
    return int(teks.replace(".", "").replace(",", "").strip())


@app.route("/tabungan")
def tabungan():
    lihat = request.args.get("lihat") == "tercapai"
    db = get_db()
    hari_ini = date.today()
    baris = db.execute(
        """
        SELECT t.id, t.nama, t.target, t.tenggat, COALESCE(SUM(s.jumlah), 0) AS terkumpul
        FROM tabungan t LEFT JOIN setoran_tabungan s ON s.tabungan_id = t.id
        GROUP BY t.id ORDER BY t.id DESC
        """
    ).fetchall()

    daftar = []
    for t in baris:
        sisa = max(t["target"] - t["terkumpul"], 0)
        saran, lewat = None, False
        if t["tenggat"] and sisa:
            tg = date.fromisoformat(t["tenggat"])
            if tg < hari_ini:
                lewat = True
            else:
                bulan = (tg.year - hari_ini.year) * 12 + tg.month - hari_ini.month
                saran = -(-sisa // max(bulan, 1))
        daftar.append({**dict(t), "sisa": sisa, "saran": saran, "lewat": lewat,
                       "persen": min(t["terkumpul"] * 100 // t["target"], 100), "setoran": []})

    per_id = {d["id"]: d for d in daftar}
    for s in db.execute(
        "SELECT id, tabungan_id, tanggal, jumlah, catatan FROM setoran_tabungan ORDER BY tanggal DESC, id DESC"
    ):
        per_id[s["tabungan_id"]]["setoran"].append(s)

    for d in daftar:
        d["tercapai_pada"] = None
        if d["persen"] >= 100:
            kum = 0
            for s in reversed(d["setoran"]):   # dari setoran terlama
                kum += s["jumlah"]
                if kum >= d["target"]:
                    d["tercapai_pada"] = s["tanggal"]
                    break

    aktif = [d for d in daftar if d["persen"] < 100]
    tercapai = [d for d in daftar if d["persen"] >= 100]

    return render_template(
        "tabungan.html",
        daftar=tercapai if lihat else aktif,
        lihat=lihat,
        jumlah_tercapai=len(tercapai),
        # total=sum(d["terkumpul"] for d in daftar),
        total=sum(d["terkumpul"] for d in aktif),
        hari_ini=hari_ini.isoformat(),
    )


@app.post("/tabungan/baru")
def tabungan_baru():
    f = request.form
    try:
        nama = f["nama"].strip()
        target = ke_angka(f["target"])
        tenggat = f.get("tenggat") or None
        assert nama and target > 0
        if tenggat:
            date.fromisoformat(tenggat)
    except (ValueError, KeyError, AssertionError):
        flash("Data tabungan tidak valid. Periksa nama dan target.")
        return redirect(url_for("tabungan"))
    db = get_db()
    db.execute("INSERT INTO tabungan (nama, target, tenggat) VALUES (?, ?, ?)", (nama, target, tenggat))
    db.commit()
    return redirect(url_for("tabungan"))


@app.post("/tabungan/<int:id>/setor")
def tabungan_setor(id):
    db = get_db()
    tab = db.execute("SELECT nama FROM tabungan WHERE id = ?", (id,)).fetchone()
    if not tab:
        abort(404)
    f = request.form
    try:
        jumlah = ke_angka(f["jumlah"])
        assert jumlah > 0
        date.fromisoformat(f["tanggal"])
    except (ValueError, KeyError, AssertionError):
        flash("Setoran tidak valid. Periksa tanggal dan jumlah.")
        return redirect(url_for("tabungan"))

    saldo = db.execute(
        "SELECT COALESCE(SUM(CASE WHEN tipe = 'masuk' THEN jumlah ELSE -jumlah END), 0) FROM transaksi"
    ).fetchone()[0]
    if jumlah > saldo:
        flash(f"Saldo tidak cukup. Saldo akhir saat ini {rupiah(saldo)}.")
        return redirect(url_for("tabungan"))

    cur = db.execute(
        "INSERT INTO transaksi (tanggal, tipe, kategori, keterangan, jumlah) VALUES (?, 'keluar', 'Tabungan', ?, ?)",
        (f["tanggal"], f"Setor ke {tab['nama']}", jumlah),
    )
    db.execute(
        "INSERT INTO setoran_tabungan (tabungan_id, tanggal, jumlah, catatan, transaksi_id) VALUES (?, ?, ?, ?, ?)",
        (id, f["tanggal"], jumlah, f.get("catatan", "").strip(), cur.lastrowid),
    )
    db.commit()
    return redirect(url_for("tabungan"))

@app.post("/tabungan/<int:id>/hapus")
def tabungan_hapus(id):
    db = get_db()
    db.execute(
        """
        DELETE FROM transaksi WHERE id IN (
            SELECT transaksi_id FROM setoran_tabungan
            WHERE tabungan_id = ? AND transaksi_id IS NOT NULL)
        """,
        (id,),
    )
    db.execute("DELETE FROM setoran_tabungan WHERE tabungan_id = ?", (id,))
    db.execute("DELETE FROM tabungan WHERE id = ?", (id,))
    db.commit()
    return redirect(request.referrer or url_for("tabungan"))


@app.post("/tabungan/setoran/<int:id>/hapus")
def setoran_hapus(id):
    db = get_db()
    s = db.execute("SELECT transaksi_id FROM setoran_tabungan WHERE id = ?", (id,)).fetchone()
    if s and s["transaksi_id"]:
        db.execute("DELETE FROM transaksi WHERE id = ?", (s["transaksi_id"],))
    db.execute("DELETE FROM setoran_tabungan WHERE id = ?", (id,))
    db.commit()
    return redirect(request.referrer or url_for("tabungan"))

def geser_bulan(bulan, n):
    y, m = map(int, bulan.split("-"))
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12}-{idx % 12 + 1:02d}"


@app.route("/anggaran")
def anggaran():
    hari_ini = date.today()
    bulan = request.args.get("bulan") or hari_ini.strftime("%Y-%m")
    try:
        date.fromisoformat(bulan + "-01")
    except ValueError:
        bulan = hari_ini.strftime("%Y-%m")
    db = get_db()

    baris = db.execute(
        """
        SELECT a.id, a.kategori, a.batas,
               COALESCE((SELECT SUM(t.jumlah) FROM transaksi t
                         WHERE t.tipe = 'keluar' AND lower(t.kategori) = lower(a.kategori)
                           AND substr(t.tanggal, 1, 7) = ?), 0) AS terpakai
        FROM anggaran a ORDER BY a.kategori
        """,
        (bulan,),
    ).fetchall()

    sekarang = bulan == hari_ini.strftime("%Y-%m")
    hari_sisa = calendar.monthrange(hari_ini.year, hari_ini.month)[1] - hari_ini.day + 1

    daftar = []
    for a in baris:
        sisa = a["batas"] - a["terpakai"]
        persen = a["terpakai"] * 100 // a["batas"]
        status = "lewat" if a["terpakai"] > a["batas"] else "waspada" if persen >= 80 else "aman"
        daftar.append({**dict(a), "sisa": sisa, "persen": persen, "status": status,
                       "saran": sisa // hari_sisa if sekarang and sisa > 0 else None})

    total_batas = sum(d["batas"] for d in daftar)
    total_terpakai = sum(d["terpakai"] for d in daftar)
    y, m = bulan.split("-")

    return render_template(
        "anggaran.html",
        daftar=daftar,
        bulan_lalu=geser_bulan(bulan, -1),
        bulan_depan=geser_bulan(bulan, 1),
        nama_bulan=f"{NAMA_BULAN[int(m) - 1]} {y}",
        total_batas=total_batas,
        total_terpakai=total_terpakai,
        total_sisa=total_batas - total_terpakai,
        total_persen=total_terpakai * 100 // total_batas if total_batas else 0,
        daftar_kategori=[r[0] for r in db.execute(
            "SELECT DISTINCT kategori FROM transaksi WHERE tipe = 'keluar' ORDER BY kategori")],
    )


@app.post("/anggaran/simpan")
def anggaran_simpan():
    f = request.form
    try:
        kategori = f["kategori"].strip()
        batas = ke_angka(f["batas"])
        assert kategori and batas > 0
    except (ValueError, KeyError, AssertionError):
        flash("Data anggaran tidak valid. Periksa kategori dan batas.")
        return redirect(request.referrer or url_for("anggaran"))
    db = get_db()
    db.execute(
        "INSERT INTO anggaran (kategori, batas) VALUES (?, ?) "
        "ON CONFLICT(kategori) DO UPDATE SET batas = excluded.batas",
        (kategori, batas),
    )
    db.commit()
    return redirect(request.referrer or url_for("anggaran"))


@app.post("/anggaran/<int:id>/hapus")
def anggaran_hapus(id):
    db = get_db()
    db.execute("DELETE FROM anggaran WHERE id = ?", (id,))
    db.commit()
    return redirect(request.referrer or url_for("anggaran"))

@app.route("/setting")
def setting():
    return render_template("setting.html")

if __name__ == "__main__":
    with sqlite3.connect(DB) as c:
        c.executescript(SCHEMA)
        kolom = [r[1] for r in c.execute("PRAGMA table_info(setoran_tabungan)")]
        if "transaksi_id" not in kolom:
            c.execute("ALTER TABLE setoran_tabungan ADD COLUMN transaksi_id INTEGER")
    app.run(debug=True)


