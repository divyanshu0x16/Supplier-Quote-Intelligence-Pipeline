"""Turn supplier documents (email, PDF, CSV) into plain text, one RawQuote per quote."""

import csv
import email
from email import policy
from pathlib import Path

import pdfplumber

from quote_pipeline.domain.models import RawQuote


def parse_email(path: Path, source_file: str) -> list[RawQuote]:
    """Read a .eml file and return its sender, subject and decoded body as one RawQuote."""
    data = path.read_bytes()
    msg = email.message_from_bytes(data, policy=policy.default)

    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:  # e.g. an attachment-only email: fail loudly, don't return empty text
        raise ValueError(f"{source_file}: email has no plain-text or HTML body")
    part_content = part.get_content()
    sender = msg.get("From")
    subject = msg.get("Subject")
    sent = msg.get("Date")  # quote date: resolves "valid for 30 days"; valid_until before it = suspicious
    lines = [f"From: {sender}", f"Date: {sent}", f"Subject: {subject}", "", part_content]
    raw_quote = RawQuote(
        source_file=source_file,
        row=None,
        text="\n".join(lines))
    return [raw_quote]


def parse_csv(path: Path, source_file: str) -> list[RawQuote]:
    """Read a supplier price list and return one RawQuote per data row, as "Header: value" lines."""
    text = path.read_text(encoding="utf-8-sig")  # -sig strips Excel's invisible byte-order mark
    dialect = csv.Sniffer().sniff(text, delimiters=",;")  # detect , vs ; (German Excel uses ;)
    reader = csv.DictReader(text.splitlines(), dialect=dialect)  # header row becomes the dict keys

    quotes = []
    for i, row in enumerate(reader, start=1):
        lines = [f"File: {source_file}"] + [f"{header}: {value}" for header, value in row.items()]
        quotes.append(RawQuote(source_file=source_file, row=i, text="\n".join(lines)))
    return quotes


def parse_pdf(path: Path, source_file: str) -> list[RawQuote]:
    """Extract the text of every page of a PDF quotation as one RawQuote."""
    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n\n".join(pages).strip()
    if not text:  # a scanned PDF is just images: no text layer, so it needs OCR
        raise ValueError(f"{source_file}: PDF has no extractable text (scanned image?)")
    return [RawQuote(source_file=source_file, row=None, text=text)]


PARSERS = {".eml": parse_email, ".csv": parse_csv, ".pdf": parse_pdf}


def parse_file(path: Path, source_file: str) -> list[RawQuote]:
    """Pick the right parser from the file extension."""
    parser = PARSERS.get(path.suffix.lower())
    if parser is None:
        raise ValueError(f"{source_file}: unsupported file type {path.suffix!r}")
    return parser(path, source_file)
