import json
from email.message import EmailMessage

import pytest
from reportlab.pdfgen import canvas

from quote_pipeline.parsing import parse_csv, parse_email, parse_file, parse_pdf


def test_parse_email_decodes_body(tmp_path):
    msg = EmailMessage()
    msg["From"] = "sales@mueller.example"
    msg["Subject"] = "RE: RFQ AX-4410"
    msg.set_content("We can offer €0,09 per unit from Müller Präzisionsteile GmbH.")
    path = tmp_path / "quote.eml"
    path.write_bytes(bytes(msg))

    [quote] = parse_email(path, "email/quote.eml")

    assert quote.source_file == "email/quote.eml"
    assert quote.row is None
    assert "€0,09" in quote.text  # quoted-printable decoded, not "=E2=82=AC0,09"
    assert "Müller" in quote.text
    assert "sales@mueller.example" in quote.text  # sender helps the LLM identify the supplier
    assert "AX-4410" in quote.text  # so does the subject


def test_parse_email_without_body_raises(tmp_path):
    msg = EmailMessage()
    msg["From"] = "sales@acme.example"
    msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="quote.pdf")
    path = tmp_path / "attachment_only.eml"
    path.write_bytes(bytes(msg))

    with pytest.raises(ValueError, match="no plain-text or HTML body"):
        parse_email(path, "email/attachment_only.eml")


@pytest.mark.parametrize("delimiter, price", [(",", "0.40"), (";", "0,40")])
def test_parse_csv_one_quote_per_row(tmp_path, delimiter, price):
    rows = [
        ["Part Number", "Unit Price", "Currency", "MOQ"],
        ["CN-2201", price, "EUR", "1000"],
        ["DS-6100", "19.46", "EUR", ""],
    ]
    path = tmp_path / "mueller_pricelist.csv"
    path.write_text("\n".join(delimiter.join(r) for r in rows) + "\n", encoding="utf-8")

    quotes = parse_csv(path, "csv/mueller_pricelist.csv")

    assert [q.row for q in quotes] == [1, 2]  # header is not a quote; rows are 1-based
    assert all(q.source_file == "csv/mueller_pricelist.csv" for q in quotes)
    assert "Part Number: CN-2201" in quotes[0].text
    assert f"Unit Price: {price}" in quotes[0].text  # kept exactly as written, not converted
    assert "Part Number: DS-6100" in quotes[1].text
    assert "mueller_pricelist.csv" in quotes[0].text  # the file name is the only supplier clue


def test_parse_csv_single_column_falls_back_to_comma(tmp_path):
    # csv.Sniffer can't guess a delimiter when there is none; that must not crash the pipeline
    path = tmp_path / "parts.csv"
    path.write_text("Part Number\nCN-2201\n", encoding="utf-8")
    [quote] = parse_csv(path, "csv/parts.csv")
    assert "Part Number: CN-2201" in quote.text


def test_parse_pdf_joins_all_pages(tmp_path):
    path = tmp_path / "quote.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(72, 750, "Müller Präzisionsteile GmbH")
    c.drawString(72, 720, "AX-4410   €0,09   500")
    c.showPage()  # start page 2
    c.drawString(72, 750, "This quotation is valid until 23.11.2026.")
    c.save()

    [quote] = parse_pdf(path, "pdf/quote.pdf")

    assert quote.source_file == "pdf/quote.pdf"
    assert quote.row is None
    assert "Müller" in quote.text
    assert "€0,09" in quote.text
    assert "23.11.2026" in quote.text  # page 2 is included, not just page 1


def test_parse_pdf_without_text_raises(tmp_path):
    path = tmp_path / "scanned.pdf"
    c = canvas.Canvas(str(path))
    c.rect(72, 600, 200, 100)  # a drawing but no text, like a scanned image
    c.save()

    with pytest.raises(ValueError, match="no extractable text"):
        parse_pdf(path, "pdf/scanned.pdf")


def test_parse_file_rejects_unknown_type(tmp_path):
    path = tmp_path / "quote.docx"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="unsupported file type '.docx'"):
        parse_file(path, "other/quote.docx")


def test_every_generated_quote_is_parsed(generated_data):
    """Parsers and ground truth must agree on exactly which quotes exist."""
    files = [p for p in sorted(generated_data.rglob("*")) if p.suffix in {".eml", ".csv", ".pdf"}]
    parsed = [q for p in files for q in parse_file(p, p.relative_to(generated_data).as_posix())]

    truth_lines = (generated_data / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()
    truth = [json.loads(line) for line in truth_lines]

    assert len(parsed) == len(truth) == 42
    assert {(q.source_file, q.row) for q in parsed} == {(t["source_file"], t["row"]) for t in truth}
    assert all(q.text.strip() for q in parsed)  # no empty text slipped through
