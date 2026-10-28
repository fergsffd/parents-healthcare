# Parents' Healthcare (PHC)

Tracks healthcare communications for Karen, William, and Marlene: every piece of mail, portal message, EOB, and bill. Goals: log everything, move senders to paperless, and catch billing errors by matching EOBs to bills.

Fully separate from Chief of Staff (CoS): no shared repo, keys, folders, or services.

## Layout

```
parents-healthcare/
  datafiles/      karen.md william.md marlene.md providers.md paperless-status.md open-items.md
  utilities/      phc_config_loader.py (redactor and sync scripts to come)
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

Not decided yet (single git path vs. CoS-style split). A manifest of datafiles changed since the last Project Knowledge upload will be kept either way.

## Services

None installed yet. Planned: `phc-redactor` (watch `inbox/*/`, OCR + redact into `processed/`).

## Git hygiene

Stage explicit paths only; never `git add -A` / `git add .`. Check `git status` before every commit. `.gitignore` blocks NAS folders, PDFs, images, and secrets.
