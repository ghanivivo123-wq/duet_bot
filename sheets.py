import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger(__name__)

HEADERS = [
    "ID",
    "Jenis Bukti",
    "Tanggal",
    "Waktu",
    "Nominal",
    "Merchant",
    "Keterangan",
    "Kategori",
    "Sumber Foto",
    "Timestamp Input",
]

SHEET_NAME = "Pengeluaran"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: Optional[gspread.Client] = None


def get_gspread_client() -> gspread.Client:
    """Initialize and return gspread client using Service Account."""
    global _client
    if _client is None:
        # Check if credentials JSON is provided as raw JSON string in env var (convenient for Render)
        raw_json_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if raw_json_env and raw_json_env.startswith("{"):
            try:
                import json
                info = json.loads(raw_json_env)
                credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
                _client = gspread.authorize(credentials)
                return _client
            except Exception as exc:
                logger.error("Gagal parsing GOOGLE_SERVICE_ACCOUNT_JSON dari env var: %s", exc)

        json_path = Path(config.GOOGLE_SERVICE_ACCOUNT_JSON_PATH)
        if not json_path.is_absolute():
            json_path = Path(__file__).resolve().parent / json_path

        if not json_path.exists():
            raise FileNotFoundError(
                f"File Service Account '{json_path}' tidak ditemukan. "
                "Periksa konfigurasi GOOGLE_SERVICE_ACCOUNT_JSON_PATH atau GOOGLE_SERVICE_ACCOUNT_JSON di .env."
            )

        credentials = Credentials.from_service_account_file(
            str(json_path),
            scopes=SCOPES,
        )
        _client = gspread.authorize(credentials)
    return _client


def get_worksheet() -> gspread.Worksheet:
    """Get the 'Pengeluaran' worksheet, creating it if it doesn't exist."""
    client = get_gspread_client()
    spreadsheet = client.open_by_key(config.GOOGLE_SHEET_ID)

    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        logger.info("Worksheet '%s' tidak ditemukan. Membuat worksheet baru...", SHEET_NAME)
        worksheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=100, cols=len(HEADERS))
        worksheet.append_row(HEADERS)
        return worksheet

    # Check if header exists
    first_row = worksheet.row_values(1)
    if not first_row or first_row != HEADERS:
        if not first_row:
            worksheet.append_row(HEADERS)
        else:
            logger.warning(
                "Header pada sheet '%s' berbeda dengan yang diharapkan. Mengupdate header...",
                SHEET_NAME,
            )
            worksheet.update("A1:J1", [HEADERS])

    return worksheet


def init_sheet() -> bool:
    """Initialize sheet and verify connection."""
    try:
        ws = get_worksheet()
        logger.info("Berhasil terhubung ke Google Sheet: %s (Sheet: %s)", config.GOOGLE_SHEET_ID, ws.title)
        return True
    except Exception as exc:
        logger.error("Gagal menginisialisasi Google Sheet: %s", exc, exc_info=True)
        return False


def _get_next_id(worksheet: gspread.Worksheet) -> int:
    """Calculate auto-increment ID."""
    id_values = worksheet.col_values(1)  # Column 1 = ID
    if len(id_values) <= 1:
        return 1
    
    ids = []
    for val in id_values[1:]:  # Skip header
        try:
            ids.append(int(val))
        except (ValueError, TypeError):
            continue
    
    if not ids:
        return 1
    return max(ids) + 1


def add_expense(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Append new expense record to Google Sheet.
    
    data keys expected:
      - jenis_bukti, tanggal, waktu, nominal, merchant, keterangan, kategori, sumber_foto
    """
    worksheet = get_worksheet()
    next_id = _get_next_id(worksheet)
    timestamp_input = datetime.now().isoformat(timespec="seconds")

    row = [
        next_id,
        str(data.get("jenis_bukti", "Nota")),
        str(data.get("tanggal", datetime.now().strftime("%Y-%m-%d"))),
        str(data.get("waktu", "")),
        data.get("nominal", 0),
        str(data.get("merchant", "")),
        str(data.get("keterangan", "")),
        str(data.get("kategori", "Lain-lain")),
        str(data.get("sumber_foto", "")),
        timestamp_input,
    ]

    worksheet.append_row(row, value_input_option="USER_ENTERED")

    result = dict(data)
    result["id"] = next_id
    result["timestamp_input"] = timestamp_input
    return result


def get_all_expenses() -> List[Dict[str, Any]]:
    """Fetch all expense rows and return as structured list of dictionaries."""
    worksheet = get_worksheet()
    all_values = worksheet.get_all_values()

    if len(all_values) <= 1:
        return []

    headers = all_values[0]
    records = []

    for row_idx, row in enumerate(all_values[1:], start=2):
        # Pad row if shorter than headers
        if len(row) < len(headers):
            row = row + [""] * (len(headers) - len(row))

        try:
            exp_id = int(row[0]) if row[0] else None
        except ValueError:
            exp_id = None

        if exp_id is None:
            continue

        try:
            raw_nom = str(row[4]).replace(".", "").replace(",", ".").replace("Rp", "").strip()
            nominal = float(raw_nom) if raw_nom else 0.0
            if nominal.is_integer():
                nominal = int(nominal)
        except (ValueError, TypeError):
            nominal = 0

        item = {
            "row_index": row_idx,
            "id": exp_id,
            "jenis_bukti": row[1],
            "tanggal": row[2],
            "waktu": row[3],
            "nominal": nominal,
            "merchant": row[5],
            "keterangan": row[6],
            "kategori": row[7],
            "sumber_foto": row[8],
            "timestamp_input": row[9] if len(row) > 9 else "",
        }
        records.append(item)

    return records


def get_expenses_by_period(period: str = "bulan-ini") -> List[Dict[str, Any]]:
    """
    Filter expenses by period:
      - 'bulan-ini': Current month (YYYY-MM)
      - '7hari': Last 7 days including today
      - 'YYYY-MM': Specific year and month (e.g. '2026-08')
      - 'all': All records
    """
    all_records = get_all_expenses()
    today = datetime.now().date()

    if period == "bulan-ini":
        current_month = today.strftime("%Y-%m")
        return [r for r in all_records if r.get("tanggal", "").startswith(current_month)]

    elif period == "7hari":
        seven_days_ago = today - timedelta(days=6)
        filtered = []
        for r in all_records:
            try:
                tgl = datetime.strptime(r.get("tanggal", ""), "%Y-%m-%d").date()
                if seven_days_ago <= tgl <= today:
                    filtered.append(r)
            except ValueError:
                continue
        return filtered

    elif period != "all":
        # Specific YYYY-MM
        return [r for r in all_records if r.get("tanggal", "").startswith(period)]

    return all_records


def get_expense_by_id(expense_id: int) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
    """
    Find an expense by its ID.
    Returns (expense_dict, row_index) or (None, None).
    """
    all_records = get_all_expenses()
    for rec in all_records:
        if rec.get("id") == expense_id:
            return rec, rec.get("row_index")
    return None, None


def update_expense(expense_id: int, updates: Dict[str, Any]) -> bool:
    """
    Update specific columns for the given expense ID.
    Accepted update keys: nominal, merchant, keterangan, kategori, tanggal, waktu, jenis_bukti.
    """
    rec, row_idx = get_expense_by_id(expense_id)
    if not rec or not row_idx:
        return False

    worksheet = get_worksheet()

    # Column mapping (1-based index)
    col_map = {
        "jenis_bukti": 2,
        "tanggal": 3,
        "waktu": 4,
        "nominal": 5,
        "merchant": 6,
        "keterangan": 7,
        "kategori": 8,
        "sumber_foto": 9,
    }

    for key, val in updates.items():
        key_clean = key.lower().strip()
        if key_clean in col_map:
            col_num = col_map[key_clean]
            if key_clean == "nominal":
                try:
                    val = float(str(val).replace(".", "").replace(",", ".").replace("Rp", "").strip())
                    if val.is_integer():
                        val = int(val)
                except (ValueError, TypeError):
                    pass
            worksheet.update_cell(row_idx, col_num, val)

    return True


def delete_last_expense() -> Optional[Dict[str, Any]]:
    """
    Delete the most recent expense row (the last data row in the sheet).
    Returns the deleted record or None if no records exist.
    """
    all_records = get_all_expenses()
    if not all_records:
        return None

    last_record = all_records[-1]
    row_idx = last_record["row_index"]

    worksheet = get_worksheet()
    worksheet.delete_rows(row_idx)

    return last_record


def delete_expense_by_id(expense_id: int) -> bool:
    """Delete an expense record by its ID."""
    rec, row_idx = get_expense_by_id(expense_id)
    if not rec or not row_idx:
        return False

    worksheet = get_worksheet()
    worksheet.delete_rows(row_idx)
    return True
