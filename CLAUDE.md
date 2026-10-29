# Parents' Healthcare (PHC)

This repo tracks healthcare communications for three people CJ coordinates care for. Its main goals are to log every piece of mail, portal message, EOB, and bill; cut paper mail by moving senders to paperless; and catch billing errors by matching EOBs to bills.
- **William** and **Marlene**: Debbie's parents. They live in the lower-level unit of CJ's home in Alameda, CA.
- **Karen**: CJ's mother, in Toledo, OH. CJ coordinates her care remotely.

The full rules for handling an incoming document live in `project-instructions.md`. Follow them whenever you update `datafiles/`.

## Layout
- `datafiles/`: `karen.md`, `william.md`, `marlene.md`, `providers.md`, `paperless-status.md`, `open-items.md`
- `utilities/`: scripts (`phc_redactor.py`, sync, config loader)
- `services/`: reference copies of systemd unit files. The installed units are in `~/.config/systemd/user`.
- `phc-config.yaml`: per-host config. It contains no secrets.
- NAS root: `/mnt/Claude/parents-healthcare/` with subfolders `inbox/{karen,william,marlene,unsorted,reference}`, `originals/`, `processed/`, `failed/`
- Secrets: `~/.config/phc/` (chmod 600). Deploy key: `~/.ssh/id_ed25519_phc`

## Hard rules
- **Chief of Staff is off-limits.** Never modify the CoS repo (`~/myClaude/chief-of-staff`), its config, secrets, services, or NAS folders. You may read CoS scripts for reference. If a change to shared code looks worthwhile, propose it to CJ and stop.
- **Sensitive documents never enter git.** That covers anything in the NAS `inbox/`, `originals/`, `processed/`, or `failed/` folders, plus any PDF or image. Never run `git add -A` or `git add .`; stage explicit paths only. Check `git status` before every commit.
- **No Gists** for PHC content unless CJ explicitly approves them. Secret Gists can be read by anyone who has the URL.
- Ask before using `sudo`, creating or enabling systemd units, changing anything on GitHub, or deleting files.
- Verify script behavior by reading the code. Don't trust documentation, including this file, to describe the current state of the code.

## Redaction profile
- **Strip:** SSNs, full dates of birth (birth year may stay), bank and card numbers, street addresses.
- **Truncate to last 4:** Medicare MBI, plan member IDs, patient account numbers, group numbers.
- **Keep:** patient first name, provider and facility names, claim numbers, dates of service, CPT/HCPCS and diagnosis codes, all dollar amounts, plan names, notice types, and deadlines.

## Data conventions
- Record identifiers as the last 4 only. Never record an SSN.
- Write dates as YYYY-MM-DD.
- Mark facts as **confirmed** when they come from a document and **reported** when CJ stated them.
- Keep each person's medical details in their own file.
- When CJ or Debbie pay an out-of-pocket cost, flag it in `open-items.md` with "→ CoS" so it gets carried into Chief of Staff.

## Sync
Single git path (CJ chose this 2026-10-27): the deploy-key clone carries datafiles and scripts. `utilities/phc_knowledge_status.py` lists datafiles changed since the last Project Knowledge upload; `mark` records a new upload point in `knowledge-status.txt`. Uploads are manual: delete the old file, then upload the new one.

`phc-autocommit.timer` commits and pushes `datafiles/*.md` and `knowledge-status.txt` on its own every 5 minutes. Commit other paths (scripts, docs) by hand as usual. Redacted input to process lives in NAS `processed/<patient>/`; `utilities/phc_redactor.py pending` lists what hasn't been logged yet.

## Working style
CJ is technically fluent and terse. Do the work, surface conclusions, and ask only when something is genuinely ambiguous. If it's unclear which patient a document belongs to, ask rather than guess. At the end of every session, list every file created or modified and every unit installed or changed.
