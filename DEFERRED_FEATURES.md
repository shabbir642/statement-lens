# Planned features (not yet implemented)

Deferred until the product direction is settled. Each entry is turnkey: the
feasibility work is done, decisions are recorded, implement when ready.

---

## Data purge / "delete on uninstall"

**Goal:** let the user wipe all sensitive data the tool generated — ideally on
uninstall, or via an explicit command.

### Feasibility (already investigated)

- **A true "run on uninstall" hook is NOT feasible.** This is not a pip package
  (no `setup.py`/`pyproject.toml`), just a script run from a folder — there is
  no uninstall event. Even as a pip package, `pip uninstall` runs no code by
  design, and there is no packaging uninstall hook. Deleting a folder fires no
  callback either.
- **All generated data lives inside the project folder**, so "uninstall" =
  delete the folder already removes it. The `.gitignore` is the exact
  inventory: `statements/`, `*.pdf`, `transactions.csv`, `report.html`,
  `digest.md`, `merchant_overrides.json`. The real gaps are (1) wiping data
  without deleting the whole checkout, and (2) unrecoverable deletion.
- **"Secure"/unrecoverable delete is best-effort only** on SSD/APFS: overwriting
  a file does not guarantee the old blocks are gone (copy-on-write,
  wear-levelling, snapshots). `srm`/`rm -P` were removed from macOS for this
  reason. FileVault full-disk encryption is the real protection — the feature
  must say so honestly and not oversell overwriting.
- **Related leak to flag:** passing `--password` on the CLI puts it in shell
  history (`~/.zsh_history`) and the process list. The purge cannot safely
  rewrite shell history, but should warn and hand over the fix; better still,
  stop the password reaching argv in the first place (see hardening below).

### Decisions (already made with the user)

1. **Scope: full set** — `purge` command + `uninstall.sh` + a write-manifest +
   password hardening.
2. **Secure delete: opt-in.** Plain unlink by default; overwrite-then-unlink
   only under `--secure`, printed with the honest SSD/FileVault caveat.
3. **Config file:** `categories.json` is kept by default (it's the user's
   editable keyword config, not financial data); removed only with
   `--include-config` (and by `uninstall.sh`).

### Design to implement

- **`purge.py` module**
  - `DEFAULT_TARGETS`: `transactions.csv`, `digest.md`, `report.html`,
    `merchant_overrides.json`, `statements/` (source PDFs — most sensitive),
    `__pycache__/`.
  - `CONFIG_TARGETS`: `categories.json` (only with `--include-config`).
  - `record(path)` — append generated file paths to `.lens/manifest`
    (best-effort) so purge finds custom `--out`/`--csv` locations, not just
    defaults.
  - `gather(base, include_config, extra)` — existing paths, de-duped by real
    path.
  - `_overwrite_file()` / `_remove(path, secure)` — best-effort overwrite for
    files (and files within dirs) before unlink when `--secure`.
  - `purge(base, include_config, secure, dry_run, extra, confirm)` — lists
    targets, honours `--dry-run`, asks `confirm` unless bypassed, deletes, then
    removes the `.lens/` manifest dir last. Prints SSD caveat + shell-history
    reminder.

- **`lens.py` wiring**
  - New `purge` subcommand: `--dry-run`, `--secure`, `--include-config`,
    `--yes`, `--custom PATH...`. Interactive confirm unless `--yes`/`--dry-run`.
  - `purge.record(...)` after writing the CSV (extract), the report, and the
    digest.
  - **Password hardening:** `_resolve_password()` order = `--password` (warned
    as insecure) -> `LENS_PDF_PASSWORD` env -> `None`; `_extract_with_password()`
    prompts once via `getpass` if a PDF turns out encrypted and no password was
    supplied. Update `--password` help to say it stays in shell history. Note:
    the getpass-on-encrypted-PDF retry path was not exercised against a live
    encrypted file in CI — test manually with the real statement.

- **`.gitignore`:** add `.lens/`.

- **`uninstall.sh`:** runs `python lens.py purge --include-config --yes [--secure]`,
  optionally `rm -rf .venv/` with `--venv`, then prints the folder-delete and
  shell-history-cleanup reminders. Documented as *the* uninstall (no automatic
  trigger exists).

- **Docs:** a "Removing your data" section in `README.md`; the SSD/FileVault
  caveat in `GAPS.md`.

- **Tests (`run_tests.py`):** a `test_purge()` in the existing temp-dir
  isolation — default run removes data + `statements/` but keeps
  `categories.json`; `--include-config` removes it; a declined confirmation
  deletes nothing. (This was written and passing — 25/25 — before being
  reverted; reinstate it alongside the feature.)

### Status

Implemented and verified once (25/25 tests), then **reverted** on
2026-07-28 pending product direction. Reintroduce from this spec.
