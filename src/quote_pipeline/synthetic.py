"""Synthetic supplier quotes with ground-truth labels (M1)."""

import csv
import json
import random
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from quote_pipeline.catalog import KNOWN_PARTS, SUPPLIERS, Supplier

QUOTE_DATE = date(2026, 10, 24)  # fixed, so the same seed always gives the same output
FX_FROM_USD = {"USD": 1.0, "EUR": 0.92, "JPY": 150.0}
CURRENCY_SYMBOL = {"USD": "$", "EUR": "€", "JPY": "¥"}
DOCS_PER_FORMAT = 12  # PDFs, and separately emails
ROWS_PER_CSV = 6
FAULTS = ["unknown_part", "zero_price", "absurd_lead_time", "expired"]
EACH_FAULT_TIMES = 2


@dataclass
class Truth:
    """The correct answers for one quote: what a perfect extractor should return."""

    supplier: str
    part_number: str
    unit_price: float
    currency: str
    moq: int | None
    lead_time_days: int
    valid_until: date
    source_file: str = ""  # filled in once we know which file the quote goes into
    row: int | None = None  # 1-based data row for CSVs; None for PDFs and emails
    expected_valid: bool = True  # what M4 validation should decide
    issues: list[str] = field(default_factory=list)  # which faults were injected, if any


def make_quote(rng: random.Random, s: Supplier) -> Truth:
    part_number = rng.choice(list(KNOWN_PARTS))
    usd = KNOWN_PARTS[part_number].base_price_usd * rng.uniform(0.85, 1.25)
    price = usd * FX_FROM_USD[s.currency]
    return Truth(
        supplier=s.name,
        part_number=part_number,
        unit_price=float(round(price)) if s.currency == "JPY" else round(price, 2),
        currency=s.currency,
        moq=rng.choice([None, 100, 500, 1000]),
        lead_time_days=rng.choice([7, 14, 21, 28, 42]),
        valid_until=QUOTE_DATE + timedelta(days=rng.choice([30, 60, 90])),
    )


def inject_fault(t: Truth, fault: str) -> None:
    """Break a quote on purpose, so M4 validation has something to catch."""
    if fault == "unknown_part":
        t.part_number += "X"  # AX-4410 -> AX-4410X, which is not in the catalog
    elif fault == "zero_price":
        t.unit_price = 0.0
    elif fault == "absurd_lead_time":
        t.lead_time_days = 400
    elif fault == "expired":
        t.valid_until = QUOTE_DATE - timedelta(days=30)
    t.expected_valid = False
    t.issues.append(fault)


def fmt_number(value: float, s: Supplier) -> str:
    """Write a number the way this supplier does: 1,234.56 / 1.234,56 / 1,235."""
    decimals = 0 if s.currency == "JPY" else 2
    text = f"{value:,.{decimals}f}"
    if s.decimal_comma:
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return text


def fmt_price(rng: random.Random, s: Supplier, value: float) -> str:
    """One of several real-world ways to write a price: "$4.10", "USD 4.10", "4,10 EUR"."""
    num = fmt_number(value, s)
    return rng.choice([
        f"{CURRENCY_SYMBOL[s.currency]}{num}",
        f"{s.currency} {num}",
        f"{num} {s.currency}",
    ])


def fmt_lead(rng: random.Random, days: int) -> str:
    """Lead time as suppliers write it: "21 days", "3 weeks", "3 wks ARO" (after receipt of order)."""
    if days % 7 == 0:
        weeks = days // 7
        return rng.choice([f"{days} days", f"{weeks} weeks", f"{weeks} wks ARO"])
    return rng.choice([f"{days} days", f"{days} calendar days"])


def fmt_date(s: Supplier, d: date) -> str:
    """A date in this supplier's own format, e.g. 12/08/2026 (US) vs 08.12.2026 (DE)."""
    return d.strftime(s.date_fmt)


def write_csv(rng: random.Random, path: Path, s: Supplier, quotes: list[Truth]) -> None:
    """A supplier price list: one header row, then one row per quote."""
    delimiter = ";" if s.decimal_comma else ","  # "4,10" would break a comma-separated file
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(["Part Number", "Unit Price", "Currency", "MOQ", "Lead Time", "Valid Until"])
        for t in quotes:
            writer.writerow([
                t.part_number,
                fmt_number(t.unit_price, s),
                t.currency,
                t.moq or "",
                fmt_lead(rng, t.lead_time_days),
                fmt_date(s, t.valid_until),
            ])


def write_email(rng: random.Random, path: Path, s: Supplier, t: Truth) -> None:
    """A supplier's reply to our RFQ, with the quote buried in a friendly paragraph."""
    msg = EmailMessage()
    msg["From"] = f"sales@{s.slug}.example"
    msg["To"] = "procurement@buyer.example"
    msg["Subject"] = f"RE: RFQ {t.part_number}"
    msg["Date"] = format_datetime(datetime.combine(QUOTE_DATE, time(10, 30), tzinfo=timezone.utc))

    moq = f"MOQ is {t.moq:,} pcs." if t.moq else "There is no MOQ."
    msg.set_content(
        "Hi Jordan,\n\n"
        f"Thanks for your RFQ. For P/N {t.part_number} we can offer "
        f"{fmt_price(rng, s, t.unit_price)} per unit. {moq}\n"
        f"Lead time is {fmt_lead(rng, t.lead_time_days)}, "
        f"and this offer is valid until {fmt_date(s, t.valid_until)}.\n\n"
        f"Best regards,\n{s.name}\nTel: +1 555 0100\n"
    )
    path.write_bytes(bytes(msg))


def write_pdf(rng: random.Random, path: Path, s: Supplier, t: Truth) -> None:
    """A formal quotation: letterhead, a one-row price table, and the small print."""
    styles = getSampleStyleSheet()
    table = Table([
        ["Part No.", "Unit Price", "MOQ", "Lead Time"],
        [t.part_number, fmt_price(rng, s, t.unit_price), t.moq or "-", fmt_lead(rng, t.lead_time_days)],
    ])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))

    story = [
        Paragraph(s.name, styles["Title"]),
        Paragraph(f"Quotation date: {fmt_date(s, QUOTE_DATE)}", styles["Normal"]),
        Spacer(1, 12),
        table,
        Spacer(1, 12),
    ]
    if t.moq:  # distractor: a total that is NOT the unit price
        total = fmt_price(rng, s, t.unit_price * t.moq)
        story.append(Paragraph(f"Total at MOQ: {total}", styles["Normal"]))
    story.append(Paragraph(f"This quotation is valid until {fmt_date(s, t.valid_until)}.",
                           styles["Normal"]))

    SimpleDocTemplate(str(path), pagesize=A4).build(story)


def generate(out: Path, seed: int = 42) -> list[Truth]:
    """Write every document under `out`, plus ground_truth.jsonl with the correct answers."""
    rng = random.Random(seed)
    for sub in ("pdf", "email", "csv"):
        shutil.rmtree(out / sub, ignore_errors=True)  # no stale files from an earlier run
        (out / sub).mkdir(parents=True)

    # Decide up front which quotes get which fault, so every fault type is always covered.
    total = 2 * DOCS_PER_FORMAT + len(SUPPLIERS) * ROWS_PER_CSV
    plan = FAULTS * EACH_FAULT_TIMES + [None] * (total - len(FAULTS) * EACH_FAULT_TIMES)
    rng.shuffle(plan)
    faults = iter(plan)

    def next_quote(s: Supplier) -> Truth:
        t = make_quote(rng, s)
        if fault := next(faults):
            inject_fault(t, fault)
        return t

    truths: list[Truth] = []

    # One quote per document for PDFs and emails.
    for folder, ext, write in [("pdf", "pdf", write_pdf), ("email", "eml", write_email)]:
        for i in range(1, DOCS_PER_FORMAT + 1):
            s = rng.choice(SUPPLIERS)
            t = next_quote(s)
            t.source_file = f"{folder}/{s.slug}_{i:03d}.{ext}"
            write(rng, out / t.source_file, s, t)
            truths.append(t)

    # One price list per supplier, several quotes per file.
    for s in SUPPLIERS:
        quotes = [next_quote(s) for _ in range(ROWS_PER_CSV)]
        for row, t in enumerate(quotes, start=1):
            t.source_file = f"csv/{s.slug}_pricelist.csv"
            t.row = row
        write_csv(rng, out / quotes[0].source_file, s, quotes)
        truths += quotes

    with (out / "ground_truth.jsonl").open("w", encoding="utf-8") as f:
        for t in truths:
            f.write(json.dumps(asdict(t), default=str, ensure_ascii=False) + "\n")
    return truths


if __name__ == "__main__":
    truths = generate(Path("data/generated"))
    broken = [t for t in truths if not t.expected_valid]
    print(f"Wrote {len(truths)} quotes to data/generated/ ({len(broken)} with deliberate faults)")
