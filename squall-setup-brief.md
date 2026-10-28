# Squall Setup Brief — Parents' Healthcare (PHC)

Hand this to Claude Code on Squall. It sets up a new, fully separate pipeline for the Parents' Healthcare Project, modeled on Chief of Staff (CoS) but sharing none of its repo, keys, folders, or services.

## Ground rules
- **Do not modify anything belonging to CoS.** That includes the repo, `~/myClaude/chief-of-staff`, `cos-config.yaml`, `cos_secrets.py`, systemd units, and NAS folders. Read CoS scripts as reference only. If a shared change looks worthwhile, propose it to CJ and stop.
- **Read the live CoS scripts before copying them.** Don't rely on documentation. `redactor.py`, `cos_md_sync.py`, `cos_md_watch.py`, `cos_secrets.py`, and `cos_config_loader.py` are the reference set.
- **No `git add -A`.** Stage explicit paths only.
- Sensitive documents (inbox, originals, processed output) never enter git. Enforce this with `.gitignore` from the first commit, before any document exists.
- Ask CJ before any step that needs GitHub web UI action, `sudo`, or creating or enabling a systemd unit.

## Names and locations (defaults — confirm with CJ before creating)
| Item | Value |
|---|---|
| GitHub repo | `fergsffd/parents-healthcare` (private) |
| Local clone | `~/myClaude/parents-healthcare` |
| Deploy key | `~/.ssh/id_ed25519_phc` (new key; write access; do not reuse the CoS key) |
| Secrets dir | `~/.config/phc/` (chmod 700, files chmod 600) |
| NAS root | `/mnt/Claude/parents-healthcare/` |
| Service prefix | `phc-` |

## NAS layout
```
/mnt/Claude/parents-healthcare/
  inbox/
    karen/        # drop scans/PDFs here — folder sets the patient
    william/
    marlene/
    unsorted/     # patient unknown; flag for CJ
  originals/      # untouched source files, moved here after processing (NAS only, never git)
  processed/      # redacted text/JSON output ready for Claude
  failed/         # anything OCR/redaction couldn't handle
```
The per-patient inbox folders remove the "whose document is this?" ambiguity at intake. The processor should carry the patient tag through to its output.

## Repo layout
```
parents-healthcare/
  datafiles/
    karen.md  william.md  marlene.md
    providers.md  paperless-status.md  open-items.md
  utilities/      # phc_redactor.py, sync scripts, config loader
  services/       # systemd unit files (copies; installed units live in ~/.config/systemd/user)
  phc-config.yaml
  .gitignore
  README.md
```
Seed `datafiles/` with the six starter files CJ has (from the claude.ai Project). Put `project-instructions.md` at the repo root for reference.

`.gitignore` must deny, at minimum: `inbox/`, `originals/`, `processed/`, `failed/`, `*.pdf`, `*.jpg`, `*.jpeg`, `*.png`, `*.heic`, `*.tif*`, `.env`, `*secret*`, `*.key`.

## Redaction profile (different from CoS — this is the key change)
CoS strips PII broadly. For healthcare, the identifiers are the useful data, so:

**Strip entirely:** SSNs, full dates of birth (keep birth year if present), bank or card numbers, home street addresses.

**Truncate to last 4:** Medicare MBI, plan member IDs, patient account numbers, group numbers.

**Keep:** patient first name, provider and facility names, provider phone numbers, claim numbers, dates of service, CPT/HCPCS and diagnosis codes, billed / allowed / plan-paid / patient-responsibility amounts, plan names, letter or notice type, and deadlines (appeal windows, enrollment dates).

Output per document: the redacted text plus a small header with patient (from the inbox folder), source filename, detected sender, document type (EOB / MSN / bill / notice / results / plan materials / other), and document date.

## Transport to Claude — decision for CJ
CoS moves redacted content to claude.ai through secret Gists. Secret Gists are unlisted but **readable by anyone holding the URL**. That was acceptable for heavily redacted CoS content. PHC output keeps much more, so the recommended default is:

**No Gists for PHC.** Claude Code on Squall reads `processed/` directly from the NAS, updates `datafiles/*.md` following the processing rules in `project-instructions.md`, and commits and pushes. The claude.ai Project gets periodic knowledge snapshots, delete-then-upload as with CoS.

Confirm with CJ before building any Gist bridge for PHC.

## Sync
This is a greenfield repo, so consider a single git-based path (the deploy-key clone) for both datafiles and scripts, rather than replicating the CoS split between the Contents API and sparse checkout. Present the trade-off to CJ and let him choose. If you mirror CoS instead, document the two paths explicitly in `README.md` and never mix them.

Either way, include a knowledge-status equivalent (a manifest of which datafiles changed since the last Project Knowledge upload).

## Services
- `phc-redactor`: watches `inbox/*/`, OCRs and redacts into `processed/`, moves the source to `originals/`, and moves failures to `failed/`. Reuse the CoS redactor's OCR stack (pytesseract, pillow-heif, EXIF orientation fix).
- A watch or autopush service is optional. Propose it, don't assume it.
- Use separate API key entries in `~/.config/phc/`, even if the value matches CoS, so the two can be rotated independently.

## Done when
1. The repo exists, the clone is on Squall, the deploy key works, and the first commit contains `.gitignore`, `README.md`, the config, and the seeded datafiles. Verify that `git status` shows nothing sensitive.
2. The NAS folders exist with correct permissions.
3. A test document dropped in `inbox/karen/` produces correctly redacted output in `processed/`, and its original lands in `originals/`. Check the redaction against the profile above.
4. `README.md` documents the layout, services, sync path, and redaction profile.
5. CJ gets a close-out list of every file created and every unit installed.
