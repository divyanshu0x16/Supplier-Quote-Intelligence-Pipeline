"""Extract one generated document (or one CSV row) with Claude and print the result. Handy for prompt work.

Usage: uv run python scripts/extract_one.py pdf/mueller_009.pdf [csv-row-number]      (one call, ~$0.0002)
"""

import sys

from common import DATA, setup_logging

from quote_pipeline.config import get_settings
from quote_pipeline.extraction.extractor import ClaudeExtractor
from quote_pipeline.parsing import parse_file


def main() -> None:
    setup_logging()
    source_file = sys.argv[1] if len(sys.argv) > 1 else "email/acme_002.eml"
    row = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    raw = parse_file(DATA / source_file, source_file)[row - 1]  # PDFs/emails have one quote; CSVs: pick the row
    print(raw.text, "\n---")
    print(ClaudeExtractor.from_settings(get_settings()).extract(raw).quote)


if __name__ == "__main__":
    main()
