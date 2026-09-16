import hashlib
import hmac
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from pypdf import PdfReader

from app.services.import_service import parse_camt, parse_csv, parse_ofx, parse_qif


def detect_mime(data: bytes, filename: str, declared: str) -> str:
    """Detect MIME from magic bytes. Extension is never trusted."""
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        name = filename.lower()
        if name.endswith(".xlsx"):
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    head = data[:200].lstrip().upper()
    if head.startswith(b"OFXHEADER") or b"<OFX" in head or b"OFXHEADER:" in head:
        return "application/x-ofx"
    if head.startswith(b"!TYPE:") or b"!TYPE:" in data[:400].upper():
        return "application/x-qif"
    if b"<CAMT." in data[:2000].upper() or b"CAMT.053" in data[:2000].upper():
        return "application/xml"
    if declared.startswith("text/") or filename.lower().endswith(".csv"):
        return "text/csv"
    if _looks_like_text(data):
        return "text/csv"
    return "application/octet-stream"


def _looks_like_text(data: bytes) -> bool:
    sample = data[:2048]
    if not sample:
        return False
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(*parts: str) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hmac_sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def parse_xlsx(data: bytes) -> tuple[list[dict], list[str]]:
    """Minimal XLSX reader using the zip+XML format. First sheet only."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for si in root.findall("m:si", ns):
                texts = [t.text or "" for t in si.findall(".//m:t", ns)]
                shared.append("".join(texts))
        sheet_name = next(
            (n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")),
            None,
        )
        if not sheet_name:
            return [], []
        sheet = ET.fromstring(zf.read(sheet_name))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows: list[list[str]] = []
        for row in sheet.findall("m:sheetData/m:row", ns):
            values: list[str] = []
            for cell in row.findall("m:c", ns):
                cell_type = cell.attrib.get("t")
                raw = cell.find("m:v", ns)
                text = raw.text if raw is not None and raw.text is not None else ""
                if cell_type == "s" and text.isdigit():
                    idx = int(text)
                    text = shared[idx] if idx < len(shared) else text
                values.append(text)
            if any(v.strip() for v in values):
                rows.append(values)
        if not rows:
            return [], []
        headers = [h.strip() or f"col_{i}" for i, h in enumerate(rows[0])]
        records = []
        for i, row in enumerate(rows[1:], start=2):
            record = {headers[j]: (row[j] if j < len(row) else "") for j in range(len(headers))}
            record["_row"] = str(i)
            records.append(record)
        return records, headers


def classify_document(filename: str, mime: str, text_sample: str) -> str:
    name = filename.lower()
    blob = f"{name} {text_sample[:2000].lower()}"
    if any(k in blob for k in ("fatura", "invoice", "statement credit", "cartao", "card statement")):
        return "credit_card_statement"
    if any(k in blob for k in ("extrato", "bank statement", "ofx", "saldo")):
        return "bank_statement"
    if any(k in blob for k in ("emprestimo", "loan", "contrato")):
        return "loan_contract"
    if any(k in blob for k in ("boleto", "linha digitavel")):
        return "boleto"
    if any(k in blob for k in ("nota fiscal", "nf-e", "nfe")):
        return "tax_invoice"
    if mime in (
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/x-ofx",
        "application/x-qif",
    ):
        return "transaction_export"
    return "unknown"


def parse_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid amount: {value}") from exc


def _as_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {value}")


def extract_structured_rows(
    data: bytes,
    mime: str,
    filename: str,
) -> tuple[list[dict], str, str]:
    """Return (rows, method, raw_text). Rows are dicts with amount/date/description."""
    if mime == "application/x-ofx":
        items = parse_ofx(data)
        rows = [_txn_to_row(item, i, "ofx") for i, item in enumerate(items)]
        return rows, "ofx", filename
    if mime == "application/x-qif":
        items = parse_qif(data)
        rows = [_txn_to_row(item, i, "qif") for i, item in enumerate(items)]
        return rows, "qif", filename
    if mime in ("application/xml",) and (b"camt" in data[:2000].lower() or b"CAMT" in data[:2000]):
        items = parse_camt(data)
        rows = [_txn_to_row(item, i, "camt") for i, item in enumerate(items)]
        return rows, "camt", filename
    if mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        records, headers = parse_xlsx(data)
        csv_like = _records_to_csv_bytes(records, headers)
        items, _failed = parse_csv(csv_like)
        rows = [_txn_to_row(item, i, f"xlsx:row:{i + 2}") for i, item in enumerate(items)]
        return rows, "xlsx", ",".join(headers)
    if mime in ("text/csv", "text/plain"):
        items, _failed = parse_csv(data)
        rows = [_txn_to_row(item, i, f"csv:row:{i + 2}") for i, item in enumerate(items)]
        return rows, "csv", data[:4000].decode("utf-8", errors="replace")
    if mime == "application/pdf":
        text = parse_pdf_text(data)
        return _rows_from_pdf_text(text), "pdf_text", text[:20000]
    return [], "unsupported", ""


def _records_to_csv_bytes(records: list[dict], headers: list[str]) -> bytes:
    import csv
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[h for h in headers if h != "_row"])
    writer.writeheader()
    for record in records:
        writer.writerow({k: v for k, v in record.items() if k != "_row"})
    return buf.getvalue().encode("utf-8")


def _txn_to_row(item, index: int, locator: str) -> dict:
    amount = _as_decimal(item.amount)
    txn_type = getattr(item, "type", None) or ("credit" if amount > 0 else "debit")
    return {
        "description": item.description,
        "amount": abs(amount),
        "currency": getattr(item, "currency", None) or "USD",
        "competence_date": _as_date(item.date),
        "payment_date": _as_date(item.date),
        "txn_type": txn_type,
        "payee": getattr(item, "payee_raw", None),
        "external_id": getattr(item, "external_id", None),
        "locator": f"{locator}:{index + 1}",
        "confidence": Decimal("1.0000"),
    }


def _rows_from_pdf_text(text: str) -> list[dict]:
    """Best-effort line parser. Missing facts stay out rather than being invented."""
    import re

    rows: list[dict] = []
    date_re = re.compile(r"(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}-\d{2}-\d{2})")
    amount_re = re.compile(r"(-?\d{1,3}(?:[.\s]\d{3})*,\d{2}|-?\d+\.\d{2})")
    for i, line in enumerate(text.splitlines(), start=1):
        date_match = date_re.search(line)
        amounts = amount_re.findall(line)
        if not date_match or not amounts:
            continue
        try:
            competence = _as_date(date_match.group(1))
            amount = _as_decimal(amounts[-1])
        except ValueError:
            continue
        desc = date_re.sub("", line)
        desc = amount_re.sub("", desc).strip(" -|\t")
        if not desc:
            continue
        rows.append(
            {
                "description": desc[:500],
                "amount": abs(amount),
                "currency": "USD",
                "competence_date": competence,
                "payment_date": competence,
                "txn_type": "credit" if amount > 0 else "debit",
                "payee": None,
                "external_id": None,
                "locator": f"pdf:line:{i}",
                "confidence": Decimal("0.5500"),
            }
        )
    return rows
