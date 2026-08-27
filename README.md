# 🧾 Telegram Expense Tracker Bot (QRIS & Nota OCR)

Bot Telegram pintar untuk mencatat pengeluaran harian secara otomatis dari foto bukti pembayaran (screenshot QRIS digital atau struk/nota fisik). Bot mengekstrak data menggunakan **Google Gemini 3.7 Flash**, menyimpannya ke **Google Sheets**, dan menyajikan grafik laporan keuangan berkala via chat.

---

## 🌟 Fitur Utama

- **OCR & Ekstraksi Cerdas**: Menggunakan Gemini 3.7 Flash untuk mendeteksi jenis bukti (`QRIS` / `Nota`), total nominal, merchant, tanggal, jam, dan kategorisasi otomatis secara bebas.
- **Konfirmasi & Edit Fleksibel**: Menampilkan ringkasan sebelum disimpan dengan tombol inline keyboard (`✅ Simpan`, `✏️ Edit`, `❌ Batal`).
- **Penyimpanan Terpusat**: Terintegrasi langsung dengan Google Sheets menggunakan Service Account.
- **Laporan Visual**:
  - `/laporan` — Bar chart pengeluaran harian + statistik total, rata-rata harian, & kategori terbesar.
  - `/kategori` — Donut/pie chart proporsi pengeluaran per kategori bulan berjalan.
  - `/edit [id]` — Koreksi data baris tertentu kapan saja.
  - `/hapus_terakhir` — Hapus transaksi terakhir dengan konfirmasi aman.
- **100% Gratis & Ringan**: Tidak ada biaya API berbayar, berjalan di VPS 1 vCPU / 1 GB RAM tanpa database server eksternal, dan menggunakan **long polling** (tanpa butuh domain/SSL publik).
- **Aman (Single-User)**: Hanya merespons `chat_id` pemilik yang terdaftar di whitelist `.env`.

---

## 📁 Struktur File

```
qris-bot/
├── .env.example              # Template variabel environment
├── requirements.txt          # Daftar pustaka Python yang dibutuhkan
├── main.py                   # Entry point aplikasi & inisialisasi handler
├── config.py                 # Pemuatan & validasi konfigurasi + whitelist security
├── gemini_extract.py         # Modul OCR & ekstraksi JSON via Gemini 3.7 Flash (google-genai)
├── sheets.py                 # Modul integrasi Google Sheets API via gspread
├── charts.py                 # Modul pembuat grafik bar & pie via matplotlib
├── handlers/
│   ├── __init__.py
│   ├── photo_handler.py      # Flow penerimaan foto, ekstraksi, konfirmasi, & simpan
│   ├── report_handler.py     # Command /start, /laporan, /kategori
│   └── edit_handler.py       # Command /edit, /hapus_terakhir
├── qris-bot.service          # Unit file systemd untuk daemon di VPS Linux
└── README.md                 # Panduan instalasi dan deployment
```

---

## 🚀 Panduan Setup Lengkap dari Nol

### Langkah 1: Buat Bot Telegram & Dapatkan Chat ID

1. Buka aplikasi Telegram, cari akun **[@BotFather](https://t.me/BotFather)**.
2. Kirim perintah `/newbot`, ikuti petunjuk untuk memberi nama dan username bot.
3. Simpan **HTTP API Token** yang diberikan (contoh: `7123456789:AAF...`). Ini adalah `TELEGRAM_BOT_TOKEN`.
4. Untuk mendapatkan `chat_id` Telegram pribadi kamu:
   - Cari bot **[@userinfobot](https://t.me/userinfobot)** di Telegram dan kirim `/start`.
   - Catat angka `Id` yang muncul (contoh: `123456789`). Ini adalah `ALLOWED_CHAT_ID`.

---

### Langkah 2: Dapatkan Gemini API Key Gratis

1. Kunjungi **[Google AI Studio](https://aistudio.google.com/)**.
2. Login menggunakan akun Google kamu.
3. Klik tombol **"Get API key"** lalu pilih **"Create API key in new project"**.
4. Salin API key yang dihasilkan. Ini adalah `GEMINI_API_KEY`.
*(Paket gratis Gemini AI Studio memiliki kuota yang sangat cukup untuk penggunaan pribadi).*

---

### Langkah 3: Setup Google Cloud Service Account & Spreadsheet

1. Buka **[Google Cloud Console](https://console.cloud.google.com/)**.
2. Buat project baru (misal: `expense-tracker-bot`).
3. Aktifkan API berikut di menu **APIs & Services > Library**:
   - **Google Sheets API** (Klik *Enable*)
   - **Google Drive API** (Klik *Enable*)
4. Masuk ke **APIs & Services > Credentials**:
   - Klik **Create Credentials** > pilih **Service Account**.
   - Beri nama service account (misal: `sheets-bot`), klik **Create and Continue**, lalu klik **Done**.
5. Klik pada Service Account yang baru dibuat di daftar credentials:
   - Masuk ke tab **Keys** > klik **Add Key** > pilih **Create new key**.
   - Pilih format **JSON** dan klik **Create**. File JSON kredensial akan terunduh ke komputermu.
   - Pindahkan file ini ke direktori project dan beri nama `service_account.json`.
6. Buka file JSON tersebut, salin alamat email service account (contoh: `sheets-bot@expense-tracker-bot.iam.gserviceaccount.com`).
7. Buka **[Google Sheets](https://sheets.google.com/)** dan buat Spreadsheet baru:
   - Beri nama sheet (misal: `Catatan Pengeluaran Pribadi`).
   - Ganti nama tab pertama menjadi `Pengeluaran` (atau biarkan bot membuatnya otomatis).
   - Klik tombol **Share (Bagikan)** di kanan atas.
   - Masukkan alamat email service account tadi, beri akses sebagai **Editor**, dan hapus centang "Notify people", lalu klik **Share**.
8. Salin **Spreadsheet ID** dari URL browser:
   - Format URL: `https://docs.google.com/spreadsheets/d/`**`1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms`**`/edit`
   - Bagian yang dicetak tebal adalah `GOOGLE_SHEET_ID`.

---

### Langkah 4: Konfigurasi File `.env`

Di direktori project `qris-bot/`, salin file `.env.example` menjadi `.env`:

```bash
cp .env.example .env
```

Buka dan isi file `.env` dengan data yang sudah kamu dapatkan:

```env
TELEGRAM_BOT_TOKEN=7123456789:AAFxxxxxxxxxxxxxxxxxxxxxx
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GEMINI_MODEL=gemini-3.7-flash
ALLOWED_CHAT_ID=123456789
GOOGLE_SERVICE_ACCOUNT_JSON_PATH=service_account.json
GOOGLE_SHEET_ID=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms
```

---

## 💻 Menjalankan Bot Secara Lokal

1. **Buat Virtual Environment Python:**
   ```bash
   python3 -m venv venv
   ```

2. **Aktifkan Virtual Environment:**
   - Linux/macOS:
     ```bash
     source venv/bin/activate
     ```
   - Windows (PowerShell):
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```

3. **Install Dependensi:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Jalankan Bot:**
   ```bash
   python main.py
   ```

5. Coba kirim pesan `/start` ke bot di Telegram dari akunmu.

---

## 🌐 Panduan Deploy di VPS Linux (systemd)

Agar bot berjalan 24/7 di VPS dan otomatis hidup kembali saat server reboot/crash:

1. **Upload Folder Project ke VPS:**
   Letakkan project di direktori `/opt/qris-bot` (atau direktori pilihanmu):
   ```bash
   sudo mkdir -p /opt/qris-bot
   sudo cp -r ./* /opt/qris-bot/
   cd /opt/qris-bot
   ```

2. **Buat Virtual Environment & Install Dependencies di VPS:**
   ```bash
   sudo apt update && sudo apt install -y python3 python3-venv python3-pip
   sudo python3 -m venv /opt/qris-bot/venv
   sudo /opt/qris-bot/venv/bin/pip install --upgrade pip
   sudo /opt/qris-bot/venv/bin/pip install -r /opt/qris-bot/requirements.txt
   ```

3. **Salin Unit File systemd:**
   ```bash
   sudo cp /opt/qris-bot/qris-bot.service /etc/systemd/system/
   ```

4. **Aktifkan & Jalankan Service:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable qris-bot
   sudo systemctl start qris-bot
   ```

5. **Cek Status & Log Service:**
   - Cek status:
     ```bash
     sudo systemctl status qris-bot
     ```
   - Pantau live log:
     ```bash
     sudo journalctl -u qris-bot -f
     ```

6. **Perintah Manajemen Tambahan:**
   - Restart bot: `sudo systemctl restart qris-bot`
   - Stop bot: `sudo systemctl stop qris-bot`

---

## 📖 Panduan Penggunaan Bot

| Perintah / Aksi | Penjelasan |
|---|---|
| **Kirim Foto Struk** | Kirim screenshot QRIS / nota belanja fisik. Bisa diberi caption langsung (contoh: `Makan siang`). Jika tanpa caption, bot akan menanyakan keterangan belanja. |
| `✅ Simpan` | Menyimpan data hasil ekstraksi ke baris baru Spreadsheet. |
| `✏️ Edit` | Memperbaiki nominal, keterangan, kategori, dll sebelum disimpan. |
| `❌ Batal` | Membatalkan pencatatan. |
| `/laporan` | Menampilkan bar chart & statistik pengeluaran harian bulan ini. |
| `/laporan 7hari` | Menampilkan bar chart pengeluaran 7 hari terakhir. |
| `/laporan YYYY-MM` | Menampilkan laporan untuk bulan spesifik (contoh: `/laporan 2026-08`). |
| `/kategori` | Menampilkan donut/pie chart proporsi pengeluaran per kategori bulan berjalan. |
| `/edit [id]` | Mengedit data transaksi yang sudah tersimpan di sheet (contoh: `/edit 5`). |
| `/hapus_terakhir` | Menghapus baris transaksi terakhir yang baru saja diinput. |

---

## 📊 Struktur Data Google Sheets

Data tersimpan pada sheet `Pengeluaran` dengan kolom berikut:

| Kolom | Tipe | Keterangan |
|---|---|---|
| `ID` | Integer | Nomor urut auto-increment |
| `Jenis Bukti` | Text | `QRIS` atau `Nota` |
| `Tanggal` | Date | Format `YYYY-MM-DD` |
| `Waktu` | Time | Format `HH:MM` |
| `Nominal` | Number | Angka total pembayaran murni |
| `Merchant` | Text | Nama toko / pedagang |
| `Keterangan` | Text | Deskripsi pengeluaran |
| `Kategori` | Text | Kategori (bebas sesuai analisis LLM) |
| `Sumber Foto` | Text | Telegram `file_id` |
| `Timestamp Input` | Datetime | Waktu pencatatan server (ISO 8601) |

---

## 🛡️ Lisensi & Catatan

Proyek ini dibuat untuk kebutuhan personal expense tracking yang efisien, hemat daya, dan bebas biaya berlangganan.
