# Parents' Healthcare (PHC)

Tracks healthcare communications for Karen, William, and Marlene: every piece of mail, portal message, EOB, and bill. Goals: log everything, move senders to paperless, and catch billing errors by matching EOBs to bills.

Fully separate from Chief of Staff (CoS): no shared repo, keys, folders, or services.

## Layout

```
parents-healthcare/
  datafiles/      karen.md william.md marlene.md providers.md paperless-status.md open-items.md
  utilities/      phc_redactor.py, phc_autocommit.py, phc_knowledge_status.py,
                  phc_config_loader.py, phc_keys.py, venv/ (gitignored)
  services/       reference copies of systemd units (installed units: ~/.config/systemd/user)
  phc-config.yaml per-host config, no secrets
  project-instructions.md   rules for processing an incoming document
```

| Item | Location |
|---|---|
| GitHub repo | `fergsffd/parents-healthcare` (private) |
| Local clone | `~/myClaude/parents-healthcare` |
| Deploy key | `~/.ssh/id_ed25519_phc`, wired via repo-local `core.sshCommand` |
| Secrets | `~/.config/phc/` (dir 700, files 600) |
| NAS root | `/mnt/Claude/parents-healthcare/` |

## NAS layout (never in git)

```
/mnt/Claude/parents-healthcare/
  inbox/{karen,william,marlene,unsorted}/   drop scans here; folder sets the patient
  inbox/reference/   public plan docs downloaded from a website (ANOC, EOC, SOB, drug lists):
                     text + regex safety net only, no Claude API calls
  originals/    untouched sources, moved here after processing
  processed/    redacted text output for Claude
  failed/       anything OCR/redaction couldn't handle
```

## Redaction profile

- **Strip:** SSNs, full dates of birth (birth year may stay), bank and card numbers, street addresses.
- **Truncate to last 4:** Medicare MBI, plan member IDs, patient account numbers, group numbers.
- **Keep:** patient first name, provider and facility names, provider phone numbers, claim numbers, dates of service, CPT/HCPCS and diagnosis codes, all dollar amounts, plan names, notice types, deadlines.

Each processed document gets a header: patient, source filename, detected sender, document type, document date.

## Transport to Claude

No Gists. Claude Code on Squall reads `processed/` from the NAS, updates `datafiles/` per `project-instructions.md`, and commits. The claude.ai Project gets manual knowledge uploads (delete old file, upload new).

## Sync

Single git path: the deploy-key clone carries both datafiles and scripts. No Contents API, no sparse checkout.

Project Knowledge uploads are manual. `utilities/phc_knowledge_status.py` lists datafiles changed since the last upload; after uploading, run it with `mark` and commit `knowledge-status.txt`.

## Services

Unit files live in `services/`; install by copying to `~/.config/systemd/user/`.

**`phc-redactor.service`** runs `phc_redactor.py watch`. It polls `inbox/{karen,william,marlene,unsorted,reference}/` every 5 s for PDFs and photos (JPG/PNG/HEIC/TIFF), extracts text (pdfplumber, OCR fallback via tesseract, EXIF rotation, HEIC via pillow-heif in the venv), and finds identifiers with the Claude API (`claude-opus-5-5`, structured JSON output, server-side refusal fallback) plus a regex safety net. Policy is enforced in code: guards keep dates of service, claim/NPI/reference numbers, and dollar amounts even if the model mislabels them. Output goes to `processed/<patient>/<name>.redacted.txt` with a header (patient, source, sender, doc type, doc date, redaction list). `inbox/reference/` skips the API (no model scan, no metadata call) and writes to `processed/reference/`; mailed copies with an address on them go in the patient folder instead, because regex doesn't catch addresses. Sources move to `originals/<patient>/`; failures to `failed/<patient>/` with a `.error.txt`. `phc_redactor.py pending` lists outputs not yet logged; `mark-reviewed <patient>/<file>` clears one. Logs: `~/.local/state/phc/logs/`.

Needs `~/.config/phc/anthropic_key` (chmod 600), separate from the CoS key file.

**`phc-autocommit.timer`** runs `phc_autocommit.py` every 5 minutes. It commits and pushes only `datafiles/*.md` and `knowledge-status.txt`, by explicit path. It waits until files have been quiet for 90 s, and refuses (unit fails) if a changed file contains an SSN, full MBI, or labeled full DOB. `--dry-run` shows what it would do.

## Git hygiene

Stage explicit paths only; never `git add -A` / `git add .`. Check `git status` before every commit. `.gitignore` blocks NAS folders, PDFs, images, and secrets.
