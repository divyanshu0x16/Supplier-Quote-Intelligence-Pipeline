from email.message import EmailMessage

import pytest

from quote_pipeline.parsers import parse_email


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
