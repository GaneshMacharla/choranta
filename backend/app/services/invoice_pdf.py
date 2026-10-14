import io
import json

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import settings
from app.models.billing import Invoice
from app.services.billing import amount_in_words

# GST state codes for the place-of-supply line
STATE_NAMES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}


def _inr(value: float) -> str:
    return f"Rs {value:,.2f}"


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """A4 GST tax invoice for a wallet recharge, or a plain payment receipt when no GST was charged
    (the supplier is not GST-registered)."""
    bill_to = json.loads(invoice.bill_to or "{}")
    taxed = bool((invoice.cgst_inr or 0) + (invoice.sgst_inr or 0) + (invoice.igst_inr or 0))
    styles = getSampleStyleSheet()
    small = styles["Normal"].clone("small", fontSize=9, leading=12)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"{'Invoice' if taxed else 'Receipt'} {invoice.number}")

    seller = "<br/>".join(filter(None, [
        f"<b>{settings.COMPANY_LEGAL_NAME}</b>",
        settings.COMPANY_ADDRESS.replace("\n", "<br/>") if settings.COMPANY_ADDRESS else None,
        f"GSTIN: {settings.COMPANY_GSTIN}" if taxed and settings.COMPANY_GSTIN else None,
        f"State: {STATE_NAMES.get(settings.COMPANY_STATE_CODE, settings.COMPANY_STATE_CODE)} ({settings.COMPANY_STATE_CODE})",
    ]))
    buyer = "<br/>".join(filter(None, [
        "<b>Bill to</b>",
        f"<b>{bill_to.get('legal_name') or ''}</b>",
        (bill_to.get("address") or "").replace("\n", "<br/>") or None,
        (f"GSTIN: {bill_to['gstin']}" if bill_to.get("gstin") else "GSTIN: Unregistered") if taxed else None,
        f"State: {STATE_NAMES.get(bill_to.get('state_code') or '', bill_to.get('state_code') or '-')}"
        + (f" ({bill_to['state_code']})" if bill_to.get("state_code") else ""),
    ]))
    meta = "<br/>".join([
        f"<b>{'Invoice' if taxed else 'Receipt'} No:</b> {invoice.number}",
        f"<b>Date:</b> {invoice.issue_date.strftime('%d %b %Y')}",
        f"<b>Place of supply:</b> {STATE_NAMES.get(invoice.place_of_supply or '', invoice.place_of_supply or '-')}"
        + (f" ({invoice.place_of_supply})" if invoice.place_of_supply else ""),
        f"<b>Payment ref:</b> {invoice.payment_reference or '-'}",
    ])

    header = Table(
        [[Paragraph(f"<font size=16><b>{'TAX INVOICE' if taxed else 'PAYMENT RECEIPT'}</b></font>", styles["Normal"]), Paragraph(meta, small)],
         [Paragraph(seller, small), Paragraph(buyer, small)]],
        colWidths=[90 * mm, 84 * mm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))

    description = invoice.description or "AI voice agent services - prepaid usage credit"
    if taxed:
        rows = [["#", "Description", "SAC", "Amount"],
                ["1", description, settings.INVOICE_SAC_CODE, _inr(invoice.taxable_inr)]]
        rate = settings.GST_RATE_PERCENT
        if invoice.igst_inr:
            rows.append(["", f"IGST @ {rate:g}%", "", _inr(invoice.igst_inr)])
        else:
            rows.append(["", f"CGST @ {rate / 2:g}%", "", _inr(invoice.cgst_inr)])
            rows.append(["", f"SGST @ {rate / 2:g}%", "", _inr(invoice.sgst_inr)])
    else:
        rows = [["#", "Description", "", "Amount"], ["1", description, "", _inr(invoice.taxable_inr)]]
    rows.append(["", "Total", "", _inr(invoice.total_inr)])
    items = Table(rows, colWidths=[10 * mm, 104 * mm, 22 * mm, 38 * mm])
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    story = [
        header,
        Spacer(1, 6 * mm),
        items,
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Amount in words:</b> {amount_in_words(invoice.total_inr)}", small),
        Spacer(1, 3 * mm),
        Paragraph(
            "The taxable value is credited to the customer's prepaid Choranta wallet and consumed by call usage. "
            "This is a computer-generated invoice." if taxed else
            "The amount is credited to the customer's prepaid Choranta wallet (1 credit per Rs 1) and consumed by "
            "call usage. Supplier not registered under GST; no GST charged. This is a computer-generated receipt.", small),
    ]
    doc.build(story)
    return buffer.getvalue()
