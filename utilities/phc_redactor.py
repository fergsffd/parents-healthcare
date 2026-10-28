#!/usr/bin/env python3
"""
PHC Redactor
------------
Watches NAS inbox/<patient>/ folders for healthcare documents (PDF or photo),
extracts text locally (OCR for photos and scanned PDFs), uses the Claude API
to find identifiers, and writes redacted text to processed/<patient>/.
Modeled on the CoS redactor, with a healthcare redaction profile:

  Strip:          SSNs, full dates of birth (birth year kept), bank and card
                  numbers, routing numbers, street addresses
  Truncate to 4:  Medicare MBI, member IDs, patient account numbers, group numbers
  Keep:           everything else (names, providers, claim numbers, dates of
                  service, codes, dollar amounts, plan names, deadlines)

Sources move to originals/<patient>/ on success, failed/<patient>/ on failure.
Files in inbox/unsorted/ are processed with patient UNKNOWN for CJ to assign.

Usage:
    phc_redactor.py watch                 # poll all inbox folders continuously
    phc_redactor.py once                  # process everything pending and exit
    phc_redactor.py file <path> [--patient karen]
    phc_redactor.py pending               # list outputs awaiting review
    phc_redactor.py mark-reviewed <name>  # clear one from pending
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from phc_config_loader import get_config

cfg = get_config()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NAS_ROOT = Path(cfg["nas_root"])
PATIENTS = cfg["patients"]

CONFIG = {
    "inbox_dir":     NAS_ROOT / "inbox",
    "processed_dir": NAS_ROOT / "processed",
    "originals_dir": NAS_ROOT / "originals",
    "failed_dir":    NAS_ROOT / "failed",
    "pending_log":   NAS_ROOT / "pending_review.log",
    # Logs hold filenames only, but keep them out of the repo anyway
    "log_dir":       Path.home() / ".local/state/phc/logs",

    "model":             "claude-opus-5-5",
    "max_tokens":        16000,
    "chunk_chars":       6000,
    "chunk_overlap":     300,
    "max_chunks":        80,

    "poll_interval":     5,
    "min_file_age":      2,
    "pdf_extensions":    [".pdf"],
    "image_extensions":  [".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff"],
}

DOC_TYPES = ["EOB", "MSN", "bill", "statement", "notice", "results",
             "plan materials", "other"]

# NAS folders are 2770; keep new files group-only too
os.umask(0o007)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

CONFIG["log_dir"].mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, cfg.get("log_level", "INFO")),
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(CONFIG["log_dir"] / f"phc_redactor_{datetime.now():%Y%m%d}.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("phc_redactor")

# ---------------------------------------------------------------------------
# Text extraction (same stack as CoS: pdfplumber, pdf2image + tesseract,
# Pillow with pillow-heif and EXIF orientation fix)
# ---------------------------------------------------------------------------

# pdfplumber emits "(cid:NN)" for glyphs whose font has no Unicode map. That
# text is invisible to the model and the regexes but trivially decodable, so
# any page containing it is re-read with OCR.
_CID_RE = re.compile(r"\(cid:\d+\)")


def _ocr_pdf_page(path: Path, page_no: int) -> str:
    from pdf2image import convert_from_path
    import pytesseract
    images = convert_from_path(path, dpi=300, first_page=page_no, last_page=page_no)
    return pytesseract.image_to_string(images[0]) if images else ""


def extract_pdf_text(path: Path) -> str:
    import pdfplumber
    parts = []
    with pdfplumber.open(path) as pdf:
        log.info("  PDF has %d page(s)", len(pdf.pages))
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if _CID_RE.search(text):
                log.info("  Page %d has unmapped glyphs; using OCR", i + 1)
                text = _ocr_pdf_page(path, i + 1)
            parts.append(f"--- Page {i+1} ---\n{text}")
    return "\n\n".join(parts)


def _text_is_sparse(text: str, min_chars_per_page: int = 200) -> bool:
    pages = max(1, text.count("--- Page "))
    body = re.sub(r"--- Page \d+ ---", "", text)
    return len(body.strip()) < min_chars_per_page * pages


def extract_pdf_text_ocr(path: Path) -> str:
    from pdf2image import convert_from_path
    import pytesseract
    log.info("  Running OCR on scanned PDF...")
    images = convert_from_path(path, dpi=300)
    return "\n\n".join(f"--- Page {i+1} ---\n{pytesseract.image_to_string(img)}"
                       for i, img in enumerate(images))


def extract_image_text(path: Path) -> str:
    from PIL import Image, ImageOps
    import pytesseract
    if path.suffix.lower() in (".heic", ".heif"):
        import pillow_heif
        pillow_heif.register_heif_opener()
    log.info("  Running OCR on image")
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)  # phone photos are often stored sideways
        return pytesseract.image_to_string(img)


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in CONFIG["pdf_extensions"]:
        text = extract_pdf_text(path)
        if _text_is_sparse(text):
            log.warning("  Little text extracted; trying OCR")
            ocr = extract_pdf_text_ocr(path)
            if len(ocr.strip()) > len(text.strip()):
                text = ocr
        return text
    if suffix in CONFIG["image_extensions"]:
        return extract_image_text(path)
    raise ValueError(f"unsupported file type {suffix}")

# ---------------------------------------------------------------------------
# Redaction policy (enforced in code, not left to the model)
# ---------------------------------------------------------------------------

STRIP_TYPES = {"SSN", "Bank account number", "Routing number", "Card number",
               "Street address", "Date of birth", "Postal barcode"}
LAST4_TYPES = {"Medicare MBI", "Member ID", "Patient account number", "Group number"}
ALL_TYPES = sorted(STRIP_TYPES | LAST4_TYPES)

# Dollar amounts the model might mislabel as account numbers
_MONEY_RE = re.compile(r"^\(?-?\$?(\d{1,3}(,\d{3})+(\.\d{1,2})?|\d+\.\d{2})\.?\)?$")
_DOB_CONTEXT_RE = re.compile(r"(?i)birth|\bd\.?o\.?b\b|\bborn\b")
# Identifiers that must survive even if the model flags them: only when the
# label sits immediately before the value ("Claim #: 123..."), so a member ID
# printed shortly after a claim number is still redacted.
_KEEP_CONTEXT_RE = re.compile(r"(?i)\b(claim|icn|dcn|npi|tax\s*id|tin|ein|reference|ref|"
                              r"authorization|auth|cpt|hcpcs|icd)\b\.?\s*"
                              r"(?:number|no\.?|#|id|code)?\s*[:#]?\s*$")


def _enforce_policy(items: list, text: str) -> list:
    out = []
    for item in items:
        t = item.get("type")
        v = str(item.get("value", "")).strip()
        if t not in STRIP_TYPES | LAST4_TYPES or len(v) < 3 or v not in text:
            continue
        if t != "Date of birth" and t != "Street address" and _MONEY_RE.match(v):
            continue
        if t == "Date of birth" and not _labeled(v, text, _DOB_CONTEXT_RE, 40, 15):
            # Ordinary dates (service dates, statement dates) get mislabeled as DOBs
            continue
        out.append({"value": v, "type": t, "source": item.get("source", "model")})
    return out


def _labeled(value: str, text: str, pattern, before: int, after: int) -> bool:
    for m in re.finditer(re.escape(value), text):
        if pattern.search(text[max(0, m.start() - before): m.end() + after]):
            return True
    return False


def _last4(value: str) -> str:
    alnum = re.sub(r"[^A-Za-z0-9]", "", value)
    return alnum[-4:]


def _birth_year(value: str) -> str | None:
    m = re.search(r"\b(19|20)\d{2}\b", value)
    return m.group() if m else None


def replacement(item: dict) -> str:
    t, v = item["type"], item["value"]
    if t == "Date of birth":
        year = _birth_year(v)
        return f"[DOB year {year}]" if year else "[REDACTED:Date of birth]"
    if t in LAST4_TYPES:
        return f"[{t} ***{_last4(v)}]"
    return f"[REDACTED:{t}]"


def masked(item: dict) -> str:
    """How a value appears in the output header: never the full value."""
    return replacement(item)

# ---------------------------------------------------------------------------
# Regex safety net (runs on the full text regardless of the model)
# ---------------------------------------------------------------------------

_MBI_CHARS = "AC-HJKMNP-RT-Y"
_SAFETY_PATTERNS = [
    ("SSN", re.compile(r"\b(\d{3}-\d{2}-\d{4})\b")),
    ("SSN", re.compile(r"(?i)\b(?:ssn|social\s+security(?:\s+(?:number|no\.?))?)\s*[:#]?\s*(\d{9})\b")),
    ("Medicare MBI", re.compile(
        rf"\b([1-9][{_MBI_CHARS}][{_MBI_CHARS}0-9]\d-?[{_MBI_CHARS}][{_MBI_CHARS}0-9]\d-?"
        rf"[{_MBI_CHARS}]{{2}}\d{{2}})\b")),
    ("Date of birth", re.compile(
        r"(?i)\b(?:dob|d\.o\.b\.?|date\s+of\s+birth|birth\s*date)\s*[:#]?\s*"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4})")),
    ("Member ID", re.compile(
        r"(?i)\b(?:member|subscriber|insured|identification|id\s+card)\s*"
        r"(?:id|number|no\.?|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{4,}[A-Z0-9])\b")),
    ("Group number", re.compile(
        r"(?i)\bgroup\s*(?:number|no\.?|#|id)?\s*[:#]\s*([A-Z0-9][A-Z0-9-]{3,}[A-Z0-9])\b")),
    ("Patient account number", re.compile(
        r"(?i)\b(?:patient\s+)?(?:account|acct\.?)\s*(?:number|no\.?|#)\s*[:#]?\s*"
        r"([A-Z0-9][A-Z0-9-]{3,}[A-Z0-9])\b")),
    ("Routing number", re.compile(
        r"(?i)\brouting(?:\s+transit)?\s*(?:number|no\.?|#)?\s*[:#]?\s*(\d{9})\b")),
    # USPS Intelligent Mail barcode rendered as text: encodes ZIP+4 and delivery point
    ("Postal barcode", re.compile(r"\b([ADFT]{65})\b")),
]
_CARD_RE = re.compile(r"\b(\d(?:[ -]?\d){12,18})\b")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def find_by_regex(text: str) -> list:
    found = {}
    for kind, pattern in _SAFETY_PATTERNS:
        for m in pattern.finditer(text):
            v = m.group(1).strip()
            if kind not in ("Date of birth", "Postal barcode") and sum(c.isdigit() for c in v) < 4:
                continue
            found.setdefault(v, {"value": v, "type": kind, "source": "regex"})
    for m in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            found.setdefault(m.group(1), {"value": m.group(1), "type": "Card number",
                                          "source": "regex"})
    return list(found.values())

# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------

_client = None


def _api():
    global _client
    if _client is None:
        import anthropic
        from phc_keys import get_anthropic_key
        _client = anthropic.Anthropic(api_key=get_anthropic_key())
    return _client


def _ask_json(prompt: str, schema: dict) -> dict | None:
    """One structured-output call with retries. Returns None after 3 failures."""
    for attempt in range(1, 4):
        try:
            resp = _api().beta.messages.create(
                model=CONFIG["model"],
                max_tokens=CONFIG["max_tokens"],
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "medium",
                               "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": prompt}],
            )
            if resp.stop_reason == "refusal":
                raise ValueError(f"refused: {getattr(resp, 'stop_details', None)}")
            if resp.stop_reason == "max_tokens":
                raise ValueError("response hit max_tokens")
            text = next(b.text for b in resp.content if b.type == "text")
            return json.loads(text)
        except Exception as e:
            log.warning("  API call failed (attempt %d/3): %s", attempt, e)
            time.sleep(2 * attempt)
    return None


_DETECT_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"value": {"type": "string"},
                       "type": {"type": "string", "enum": ALL_TYPES}},
        "required": ["value", "type"],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}

_META_SCHEMA = {
    "type": "object",
    "properties": {
        "sender": {"type": "string"},
        "document_type": {"type": "string", "enum": DOC_TYPES},
        "document_date": {"type": "string"},
    },
    "required": ["sender", "document_type", "document_date"],
    "additionalProperties": False,
}


def detect_identifiers(text: str) -> tuple[list, bool]:
    """Scan the whole text in overlapping chunks. Returns (items, complete);
    complete is False if any chunk failed or chunks were capped."""
    size, step = CONFIG["chunk_chars"], CONFIG["chunk_chars"] - CONFIG["chunk_overlap"]
    starts = list(range(0, max(len(text), 1), step))
    complete = True
    if len(starts) > CONFIG["max_chunks"]:
        log.warning("  Text too long; scanning first %d chunks only", CONFIG["max_chunks"])
        starts, complete = starts[: CONFIG["max_chunks"]], False
    log.info("  Scanning %d chunk(s)", len(starts))
    items = {}
    for i in starts:
        result = _ask_json(_detect_prompt(text[i:i + size]), _DETECT_SCHEMA)
        if result is None:
            complete = False
            continue
        for it in result["items"]:
            items.setdefault((it["value"], it["type"]), it)
    return list(items.values()), complete


def _detect_prompt(chunk: str) -> str:
    return f"""This is OCR text from a US healthcare document (EOB, Medicare Summary Notice,
medical bill, plan notice, or test results) that a family caregiver is logging.
List every occurrence of these identifiers, with the value copied exactly as it appears:

- SSN: Social Security numbers
- Date of birth: the patient's or member's date of birth (not dates of service,
  statement dates, or deadlines)
- Bank account number, Routing number, Card number: payment details
- Street address: any street address line (number + street, PO Box). Not city/state alone.
- Medicare MBI: Medicare Beneficiary Identifier (11 characters, e.g. 1EG4-TE5-MK73)
- Member ID: health plan member, subscriber, or insured ID numbers
- Patient account number: a provider's account number for the patient
- Group number: plan group numbers

Do NOT list: names, provider or facility names, phone numbers, claim numbers,
NPI or tax IDs, authorization or reference numbers, CPT/HCPCS/ICD codes,
dollar amounts, dates of service, or plan names. Return an empty list if none.

Text:
{chunk}"""


def detect_metadata(text: str) -> dict:
    prompt = f"""This is OCR text from a US healthcare document. Identify:
- sender: the organization that sent it (plan, provider, Medicare, pharmacy), or "unknown"
- document_type: EOB (plan Explanation of Benefits), MSN (Medicare Summary Notice),
  bill (asks for payment), statement (account summary, no payment due), notice
  (coverage, appeal, enrollment, policy), results (labs, imaging), plan materials
  (ANOC, EOC, formulary, ID card), or other
- document_date: the document's own date (statement/notice date) as YYYY-MM-DD, or "unknown"

Text:
{text[:8000]}"""
    return _ask_json(prompt, _META_SCHEMA) or {
        "sender": "unknown", "document_type": "other", "document_date": "unknown"}

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def redact_text(text: str, items: list) -> tuple[str, int]:
    """Replace longest values first. LAST4/strip numbers preceded by a claim,
    NPI, reference, or code label are left alone (claim numbers are kept)."""
    total = 0
    for item in sorted(items, key=lambda i: len(i["value"]), reverse=True):
        rep = replacement(item)
        guard = item["type"] not in ("SSN", "Date of birth", "Street address")

        def sub(m):
            nonlocal total
            if guard and _KEEP_CONTEXT_RE.search(text_now[max(0, m.start() - 30): m.start()]):
                return m.group()
            total += 1
            return rep

        text_now = text
        text = re.sub(re.escape(item["value"]), sub, text_now)
    return text, total


def safe_name(name: str) -> str:
    """Mask long digit runs (account numbers in scanner/portal filenames)."""
    return re.sub(r"\d{6,}", lambda m: "***" + m.group()[-4:], name)


def unique_path(directory: Path, name: str) -> Path:
    dest = directory / name
    if dest.exists():
        p = Path(name)
        dest = directory / f"{p.stem}_{datetime.now():%Y%m%d_%H%M%S}{p.suffix}"
    return dest

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def process_file(path: Path, patient: str) -> bool:
    label = patient if patient in PATIENTS else "UNKNOWN"
    folder = patient if patient in PATIENTS else "unsorted"
    log.info("Processing [%s] %s", label, safe_name(path.name))
    try:
        text = extract_text(path)
        if not text.strip():
            raise ValueError("no text extracted")
        model_items, complete = detect_identifiers(text)
        items = _enforce_policy(model_items + find_by_regex(text), text)
        dedup = {}
        for it in items:
            dedup.setdefault(it["value"], it)
        items = list(dedup.values())
        redacted, n = redact_text(text, items)
        meta = detect_metadata(redacted)
        log.info("  %d identifier(s), %d replacement(s); %s %s from %s",
                 len(items), n, meta["document_type"], meta["document_date"], meta["sender"])

        out_dir = CONFIG["processed_dir"] / folder
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = unique_path(out_dir, f"{safe_name(path.stem)}.redacted.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# Patient: {label}\n")
            f.write(f"# Source file: {safe_name(path.name)}\n")
            f.write(f"# Sender: {meta['sender']}\n")
            f.write(f"# Document type: {meta['document_type']}\n")
            f.write(f"# Document date: {meta['document_date']}\n")
            f.write(f"# Processed: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            if not complete:
                f.write("# WARNING: model scan incomplete; only regex safety net covered "
                        "part of this text. Review before use.\n")
            f.write(f"# Redactions ({n}):\n")
            for it in items:
                f.write(f"#   {it['type']}: {masked(it)} ({it['source']})\n")
            f.write("\n" + "=" * 60 + "\n\n")
            f.write(redacted)
    except Exception as e:
        log.exception("  Failed: %s", e)
        fail_dir = CONFIG["failed_dir"] / folder
        fail_dir.mkdir(parents=True, exist_ok=True)
        dest = unique_path(fail_dir, path.name)
        shutil.move(str(path), str(dest))
        with open(dest.with_name(dest.name + ".error.txt"), "w") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {type(e).__name__}: {e}\n")
        log.info("  Moved to failed/%s/%s", folder, safe_name(dest.name))
        return False

    orig_dir = CONFIG["originals_dir"] / folder
    orig_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_path(orig_dir, path.name)
    shutil.move(str(path), str(dest))
    log.info("  Output: processed/%s/%s; original archived", folder, out_path.name)
    with open(CONFIG["pending_log"], "a") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  PENDING   {folder}/{out_path.name}\n")
    return True

# ---------------------------------------------------------------------------
# Discovery and modes
# ---------------------------------------------------------------------------

def _candidates() -> list[tuple[Path, str]]:
    exts = set(CONFIG["pdf_extensions"] + CONFIG["image_extensions"])
    found = []
    for folder in PATIENTS + ["unsorted"]:
        d = CONFIG["inbox_dir"] / folder
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.is_file() and p.suffix.lower() in exts and not p.name.startswith("."):
                    found.append((p, folder))
    return found


def _file_stable(path: Path) -> bool:
    try:
        s1 = path.stat().st_size
        time.sleep(CONFIG["min_file_age"])
        return s1 == path.stat().st_size and s1 > 0
    except FileNotFoundError:
        return False


def watch_mode():
    log.info("Watching %s/{%s}", CONFIG["inbox_dir"], ",".join(PATIENTS + ["unsorted"]))
    seen = set()
    while True:
        for path, folder in _candidates():
            try:
                if not _file_stable(path):
                    continue
                h = hashlib.sha256(path.read_bytes()).hexdigest()
                if h in seen:
                    continue
                seen.add(h)
                process_file(path, folder)
            except Exception as e:
                log.exception("Unexpected error on %s: %s", safe_name(path.name), e)
        time.sleep(CONFIG["poll_interval"])


def once_mode():
    items = _candidates()
    if not items:
        log.info("Nothing in inbox.")
    for path, folder in items:
        process_file(path, folder)


def list_pending():
    log_path = CONFIG["pending_log"]
    if not log_path.exists():
        print("Nothing processed yet.")
        return
    status = {}
    for line in log_path.read_text().splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            status[parts[3]] = parts[2]
    pending = sorted(f for f, s in status.items() if s == "PENDING")
    print(f"{len(pending)} file(s) awaiting review in {CONFIG['processed_dir']}:"
          if pending else "Nothing pending review.")
    for name in pending:
        print(f"  {name}")


def mark_reviewed(name: str):
    with open(CONFIG["pending_log"], "a") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  REVIEWED  {name}\n")
    print(f"Marked reviewed: {name}")


def main():
    parser = argparse.ArgumentParser(description="PHC healthcare document redactor",
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("watch")
    sub.add_parser("once")
    p_file = sub.add_parser("file")
    p_file.add_argument("path")
    p_file.add_argument("--patient", default="unsorted",
                        choices=PATIENTS + ["unsorted"])
    sub.add_parser("pending")
    p_rev = sub.add_parser("mark-reviewed")
    p_rev.add_argument("name", help="name as shown by `pending`, e.g. karen/x.redacted.txt")
    args = parser.parse_args()

    if args.cmd == "watch":
        watch_mode()
    elif args.cmd == "once":
        once_mode()
    elif args.cmd == "file":
        target = Path(args.path).expanduser().resolve()
        if not target.exists():
            sys.exit(f"File not found: {target}")
        sys.exit(0 if process_file(target, args.patient) else 1)
    elif args.cmd == "pending":
        list_pending()
    elif args.cmd == "mark-reviewed":
        mark_reviewed(args.name)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
