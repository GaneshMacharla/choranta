"""
Campaign recipient lists in whatever file the client has: CSV / TSV / TXT, Excel (.xlsx, .xls) or a shared
Google Sheet. Each is turned into the CSV text the campaign import
already reads (services/campaigns.parse_recipients_csv), so preview, validation and import stay the same.

Sheets often have a title above the header, or no header at all (just a column of numbers): the header row is
found by its phone column, and a headerless list gets one from the column that holds phone numbers.
"""
import csv
import io
import re
import zipfile
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.services.campaigns import NAME_COLUMNS, PHONE_COLUMNS, CampaignError, _column_key, normalize_phone

MAX_FILE_BYTES = 5_000_000
MAX_ROWS = 20_000           # more than a campaign takes; the import reports the limit
MAX_COLUMNS = 100
MAX_UNZIPPED_BYTES = 60_000_000
HEADER_SEARCH_ROWS = 15
SUPPORTED = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls")
SUPPORTED_TEXT = "CSV, TSV, TXT or Excel (.xlsx, .xls)"

Rows = List[List[str]]


def _cell(value: Any) -> str:
    """A spreadsheet cell as text; whole numbers lose the '.0' Excel gives phone numbers."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    return re.sub(r"\s+", " ", str(value)).strip()


def _trim(rows: Rows) -> Rows:
    out = []
    for row in rows:
        row = [c for c in row[:MAX_COLUMNS]]
        while row and not row[-1]:
            row.pop()
        out.append(row)
    while out and not any(out[-1]):
        out.pop()
    return out


# ---------------------------------------------------------------- readers


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):  # Excel's "Unicode text"
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")  # Excel's "CSV" on Windows


def _read_text(data: bytes) -> Rows:
    text = _decode(data).replace("\r\n", "\n")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for i, row in enumerate(csv.reader(io.StringIO(text), dialect)):
        if i >= MAX_ROWS:
            break
        rows.append([_cell(c) for c in row])
    return rows


def _best_sheet(sheets: List[Tuple[str, Rows]]) -> Tuple[str, Rows]:
    """The sheet with a phone column, else the first one with data."""
    with_data = [(name, rows) for name, rows in sheets if any(any(r) for r in rows)]
    if not with_data:
        raise CampaignError("The file has no data.")
    for name, rows in with_data:
        if _header_index(rows) is not None:
            return name, rows
    return with_data[0]


def _read_xlsx(data: bytes) -> Tuple[str, Rows]:
    from openpyxl import load_workbook
    _check_zip(data)
    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise CampaignError("Couldn't open this Excel file. Save it again as .xlsx and retry.") from exc
    sheets = []
    try:
        for sheet in book.worksheets:
            rows = []
            for i, row in enumerate(sheet.iter_rows(values_only=True)):
                if i >= MAX_ROWS:
                    break
                rows.append([_cell(v) for v in row[:MAX_COLUMNS]])
            sheets.append((sheet.title, _trim(rows)))
    finally:
        book.close()
    return _best_sheet(sheets)


def _read_xls(data: bytes) -> Tuple[str, Rows]:
    import xlrd
    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception as exc:
        raise CampaignError("Couldn't open this .xls file. Save it as .xlsx or CSV and retry.") from exc
    sheets = []
    for sheet in book.sheets():
        rows = []
        for r in range(min(sheet.nrows, MAX_ROWS)):
            cells = []
            for c in range(min(sheet.ncols, MAX_COLUMNS)):
                cell = sheet.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    cells.append(_cell(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)))
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    cells.append(_cell(bool(cell.value)))
                else:
                    cells.append(_cell(cell.value))
            rows.append(cells)
        sheets.append((sheet.name, _trim(rows)))
    return _best_sheet(sheets)


def _check_zip(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise CampaignError("This file is damaged or isn't the type its name says.") from exc
    if sum(i.file_size for i in archive.infolist()) > MAX_UNZIPPED_BYTES:
        raise CampaignError("This file is too large. Split it into smaller files.")
    return archive


# ---------------------------------------------------------------- header


def _header_index(rows: Rows) -> Optional[int]:
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        if any(_column_key(c) in PHONE_COLUMNS for c in row):
            return i
    return None


def _with_header(rows: Rows) -> Rows:
    """Rows starting at their header row; a headerless list gets 'phone' (and 'name') column names."""
    index = _header_index(rows)
    if index is not None:
        return rows[index:]
    sample = [r for r in rows if any(r)][:30]
    if not sample:
        raise CampaignError("The file has no data.")
    width = max(len(r) for r in sample)

    def phone_share(col: int) -> float:
        values = [r[col] for r in sample if col < len(r) and r[col]]
        return sum(1 for v in values if normalize_phone(v)) / len(values) if values else 0.0

    phone_col = max(range(width), key=phone_share)
    if phone_share(phone_col) < 0.6:
        raise CampaignError("No phone column found. Name one column 'phone' (or mobile / number / contact_number).")
    # A header row naming other columns but not the phone one: keep it, just name the phone column
    first = sample[0]
    if not normalize_phone(first[phone_col] if phone_col < len(first) else "") and rows and rows[0] is first:
        header = list(first) + [""] * (width - len(first))
        header[phone_col] = "phone"
        return [header] + rows[1:]
    header = [f"column_{i + 1}" for i in range(width)]
    header[phone_col] = "phone"
    text_cols = [i for i in range(width) if i != phone_col
                 and any(i < len(r) and r[i] and not normalize_phone(r[i]) for r in sample)]
    if text_cols and not any(_column_key(h) in NAME_COLUMNS for h in header):
        header[text_cols[0]] = "name"
    return [header] + rows


def _to_csv(rows: Rows) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in _with_header(_trim(rows)):
        writer.writerow(row)
    return out.getvalue()


# ---------------------------------------------------------------- entry points


def file_to_csv(filename: str, data: bytes) -> Dict[str, Any]:
    """{"csv_text", "file_type", "sheet"} for an uploaded recipient file."""
    name = (filename or "").strip().lower()
    ext = name[name.rfind("."):] if "." in name else ""
    if len(data) > MAX_FILE_BYTES:
        raise CampaignError(f"The file is larger than {MAX_FILE_BYTES // 1_000_000} MB. Split it into smaller files.")
    if not data:
        raise CampaignError("The file is empty.")
    sheet = None
    if ext in (".xlsx", ".xlsm"):
        sheet, rows = _read_xlsx(data)
    elif ext == ".xls":
        # Some "xls" files are really HTML or CSV saved by other software
        if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            sheet, rows = _read_xls(data)
        elif data[:2] == b"PK":
            sheet, rows = _read_xlsx(data)
        else:
            rows = _read_text(data)
    elif ext in (".csv", ".tsv", ".txt") or not ext:
        rows = _read_text(data)
    else:
        raise CampaignError(f"Upload a {SUPPORTED_TEXT} file.")
    return {"csv_text": _to_csv(rows), "file_type": ext.lstrip(".") or "txt", "sheet": sheet}


def google_sheet_to_csv(url: str) -> Dict[str, Any]:
    """The rows of a Google Sheet shared as 'Anyone with the link can view'."""
    from app.services.inventory_sync import InventorySyncError, google_sheet_csv_url
    try:
        export_url = google_sheet_csv_url(url)
    except InventorySyncError as exc:
        raise CampaignError(str(exc)) from exc
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(export_url)
    except httpx.RequestError as exc:
        raise CampaignError("Couldn't reach Google Sheets. Try again in a moment.") from exc
    if response.status_code >= 400 or "text/html" in response.headers.get("content-type", ""):
        raise CampaignError("Couldn't read the sheet. Share it as 'Anyone with the link can view' and paste its link.")
    if len(response.content) > MAX_FILE_BYTES:
        raise CampaignError("The sheet is too large. Split it into smaller sheets.")
    return {"csv_text": _to_csv(_read_text(response.content)), "file_type": "google_sheet", "sheet": None}
