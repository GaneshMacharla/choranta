import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.services import campaigns as svc
from app.services.recipient_files import file_to_csv, google_sheet_to_csv


def _parsed(filename: str, data: bytes):
    return svc.parse_recipients_csv(file_to_csv(filename, data)["csv_text"])


def _xlsx(rows, title_rows=()) -> bytes:
    book = Workbook()
    sheet = book.active
    for row in list(title_rows) + list(rows):
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_xlsx_with_numeric_phones_and_a_title_row():
    data = _xlsx([["Student Name", "Mobile", "Course"], ["Priya", 9876543210, "NEET"], ["Rahul", 919876543211.0, "JEE"]],
                 title_rows=[["Enquiries October"], []])
    parsed = _parsed("leads.xlsx", data)
    assert [r["phone"] for r in parsed.rows] == ["+919876543210", "+919876543211"]
    assert parsed.rows[0]["variables"] == {"course": "NEET", "user_name": "Priya"}


def test_xlsx_picks_the_sheet_with_phone_numbers():
    book = Workbook()
    book.active.title = "Notes"
    book.active.append(["Read me first"])
    leads = book.create_sheet("Leads")
    leads.append(["name", "phone"])
    leads.append(["Asha", "9812345678"])
    out = io.BytesIO()
    book.save(out)
    result = file_to_csv("book.xlsx", out.getvalue())
    assert result["sheet"] == "Leads"
    assert svc.parse_recipients_csv(result["csv_text"]).rows[0]["phone"] == "+919812345678"


def test_semicolon_and_tab_separated_text():
    assert _parsed("list.csv", "name;phone\nAsha;9812345678\n".encode()).rows[0]["phone"] == "+919812345678"
    assert _parsed("list.tsv", "name\tphone\nAsha\t9812345678\n".encode()).rows[0]["name"] == "Asha"


def test_windows_encoded_csv():
    parsed = _parsed("list.csv", "name,phone\nJosé,9812345678\n".encode("cp1252"))
    assert parsed.rows[0]["name"] == "José"


def test_headerless_list_of_numbers():
    parsed = _parsed("numbers.txt", b"9812345678\n9812345679\n09812345670\n")
    assert len(parsed.rows) == 3


def test_headerless_rows_with_names():
    parsed = _parsed("people.csv", b"Asha,9812345678\nRavi,9812345679\n")
    assert [(r["name"], r["phone"]) for r in parsed.rows] == [("Asha", "+919812345678"), ("Ravi", "+919812345679")]


def test_header_without_a_phone_column_name():
    parsed = _parsed("people.csv", b"Student,Contact no,Course\nAsha,9812345678,NEET\nRavi,9812345679,JEE\n")
    assert len(parsed.rows) == 2 and parsed.rows[0]["variables"]["course"] == "NEET"


@pytest.mark.parametrize("name,data,message", [
    ("photo.png", b"\x89PNG....", "Upload a"),
    ("leads.xlsx", b"not a zip", "damaged"),
    ("empty.csv", b"", "empty"),
    ("words.txt", b"hello\nthere\n", "No phone column"),
])
def test_bad_files(name, data, message):
    with pytest.raises(svc.CampaignError, match=message):
        file_to_csv(name, data)


def test_google_sheet_link_must_be_a_sheet():
    with pytest.raises(svc.CampaignError, match="Google Sheets"):
        google_sheet_to_csv("https://example.com/not-a-sheet")


def test_upload_endpoint(client: TestClient, operator_headers: dict):
    data = _xlsx([["name", "phone"], ["Asha", 9812345678]])
    response = client.post("/api/campaigns/recipient-file", headers=operator_headers,
                           files={"file": ("leads.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text
    preview = client.post("/api/campaigns/preview-csv", headers=operator_headers, json={"csv_text": response.json()["csv_text"]})
    assert preview.status_code == 200 and preview.json()["valid"] == 1

    bad = client.post("/api/campaigns/recipient-file", headers=operator_headers, files={"file": ("x.png", b"123", "image/png")})
    assert bad.status_code in (400, 422)
