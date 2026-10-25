# Supplier Quote Intelligence

**Stop digging through your inbox to compare supplier quotes.** Drop in the quotes you receive, whether a PDF,
an email or a spreadsheet, and ask one question:

> *"Who can supply part CN-2201 cheapest, delivered within 30 days?"*

The tool reads each quote, pulls out the price, minimum order, lead time and expiry date, checks them, and gives
you a ranked answer in seconds. Anything it isn't sure about goes to a **review queue** for a person to check.
It never guesses.

---

## What you can do

| You want to… | Use |
|---|---|
| Add a quote you received | **Upload** (`/ingest`) |
| Find the best current offer for a part | **Compare** (`/compare`) |
| See every quote on file for a part or supplier | **Quotes** (`/quotes`) |
| Check the quotes that need a person's attention | **Review queue** (`/review-queue`) |

All four are on one web page: **http://localhost:8000/docs**. Click an item, press **Try it out**, fill in
the boxes, then press **Execute**.

---

## 1. Add a quote

Open **POST /ingest**, choose the file and press **Execute**. Accepted formats:

- **PDF** quotations (with real text, not scanned images)
- **Emails** saved as `.eml` (in most mail apps: *File → Save As*)
- **CSV** price lists (comma- or semicolon-separated, any column names)

Two optional boxes:
- **supplier**: who sent it. Fill this in for **price lists**, which often don't name the supplier inside the file.
- **received_on**: the date you received it, if not today.

You get an answer straight away, one line per quote in the file:

| status | meaning |
|---|---|
| `valid` | checked and stored; it will appear in comparisons |
| `needs_review` | stored in the review queue with the reasons (see section 3) |

**Uploading the same file twice is safe.** The tool recognises the exact file and skips it (`"skipped": true`),
so nothing is duplicated and nothing is charged twice. An *updated* price list (new content, same name) is
treated as a new quote.

---

## 2. Find the best offer

Open **GET /compare** and enter the **part** number. Optionally, enter **max_lead_days** to keep only offers
that can be delivered in time. For example, `part = CN-2201`, `max_lead_days = 30`:

| Supplier | Price | ≈ USD | Lead time | Valid until |
|---|---|---|---|---|
| Acme Components Inc. | 0.38 USD | $0.38 | 21 days | 23 Dec 2026 |
| Acme Components Inc. | 0.39 USD | $0.39 | 28 days | 23 Nov 2026 |
| Kanto Precision Co., Ltd. | 60 JPY | $0.40 | 21 days | 23 Nov 2026 |
| Kanto Precision Co., Ltd. | 66 JPY | $0.44 | 14 days | 23 Nov 2026 |

- **Cheapest first**, even across currencies: prices are converted to an approximate USD value **for ranking
  only**. The supplier's original price and currency are always shown and are what you'd order at.
- **Expired quotes are left out automatically**, checked against today's date every time you ask.
- Every row shows which file it came from (`source_file`), so you can always open the original.

---

## 3. Check the review queue

Open **GET /review-queue**. Each entry shows the file, **the reasons** it was flagged, what the tool read from
it, and the original text, so you can decide without hunting for the document.

| Reason you'll see | What it usually means | What to do |
|---|---|---|
| `unknown part number 'DS-6100X'` | a typo, or a part not in our catalog | check with the supplier, or add the part to the catalog |
| `unit price must be > 0` | a missing or zero price | ask the supplier for the price |
| `lead time 400 days is outside 1-180 days` | a typo, or a genuinely long lead time | confirm with the supplier; very long lead times do exist |
| `valid until … is before the quote was received` | the date was misread (12/08 vs 08/12) or an old quote was re-sent | check the date on the original |
| `currency not stated` | e.g. `¥` without saying yen or yuan | check the original, then confirm the currency |
| `… not stated` (supplier, price, …) | the document doesn't say | ask the supplier, or re-upload with the **supplier** box filled in |
| `PDF has no extractable text (scanned image?)` | a scanned page, which the tool can't read yet | type the quote in, or ask the supplier for a digital PDF |

**Why a queue instead of a guess?** A flagged quote costs you a few seconds. A wrong price that slips through
silently (say, yen read as yuan, which is 20× off) could cost real money, and nobody would notice.

---

## What it checks

Every quote must have a supplier, part number, price, currency, lead time and expiry date. On top of that:

- the part number is one we actually buy
- the price is above zero
- the lead time is between 1 and **180 days** (a business setting: ask your administrator to change it)
- the quote hadn't already expired when it arrived

A minimum order quantity is optional ("No MOQ" is normal).

---

## Good to know

- **Your documents are read by an AI service.** Quote text is sent to Anthropic's Claude API to be read. Check
  that this is acceptable for your suppliers' documents before using it with confidential quotes.
- **One price per quote.** Tiered prices ("$0.12 for 100+, $0.09 for 5,000+") and conditions ("+15% surcharge")
  aren't captured as separate fields yet. Check the original for those.
- **Exchange rates are approximate** and fixed. They're good for ranking, not for budgeting.
- **Cost:** reading a quote costs about $0.0002 (roughly 5,000 quotes per dollar). Re-uploads are free.

---

## Setting it up (for whoever installs it)

Needs Docker and an Anthropic API key.

```bash
cp .env.example .env          # then put the API key in .env
docker compose up -d --build  # starts the database and the tool
```

Then open **http://localhost:8000/docs**. To stop it: `docker compose down` (your data is kept).

Engineers: see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how it works inside, and
[LEARNING_LOG.md](LEARNING_LOG.md) for the design decisions.
