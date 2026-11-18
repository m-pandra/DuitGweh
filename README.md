# Buku Kas — Cek Cashflow (Flask + SQLite)

## Menjalankan
```bash
pip install -r requirements.txt
python app.py
```
Buka http://127.0.0.1:5000. Database `cashflow.db` dibuat otomatis.

## Struktur
- `app.py` — route Flask, skema SQL, query ringkasan & saldo berjalan
- `templates/index.html` — tampilan (formulir, ringkasan, riwayat)

## Catatan
- Saldo berjalan memakai window function SQL (`SUM() OVER`), butuh SQLite 3.25+ (sudah standar di Python 3.8+).
- Ganti `app.secret_key` sebelum dipakai di server.
- Untuk MySQL/PostgreSQL, ganti koneksi `sqlite3` dengan driver terkait; query-nya hampir sama.
