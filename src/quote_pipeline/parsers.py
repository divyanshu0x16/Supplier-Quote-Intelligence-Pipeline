"""Turn supplier documents (email, PDF, CSV) into plain text, one chunk per quote (M2)."""

import email
from email import policy
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RawQuote:
    source_file: str  # path relative to the data folder, e.g. "email/acme_006.eml"
    row: int | None  # 1-based data row for CSVs; None for PDFs and emails
    text: str  # plain text for the extractor (M3) to read


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
