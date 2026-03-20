# Release Checklist

Practical checklist for preparing `sortdocs` for a local release or an initial project handoff.

## Before Tagging

- make sure `.env` is not tracked
- make sure `~/.config/sortdocs/.env` is documented and not committed anywhere
- verify the version in `pyproject.toml` and `src/sortdocs/__init__.py`
- update `README.md` if the CLI flow changed
- review `sortdocs.example.yaml`

## Technical Verification

Run:

```bash
make test
make lint
```

Also verify the real command:

```bash
hash -r
sortdocs . --dry-run
```

Also verify onboarding:

```bash
env -u OPENAI_API_KEY sortdocs .
```

Expected behavior:

- welcome panel appears
- API key setup panel appears
- the tool points users to the official OpenAI API key page

## Packaging

Confirm the console script is available:

```bash
.venv/bin/sortdocs --help
```

Confirm the launcher works from `PATH`:

```bash
bash scripts/install-path.sh
hash -r
sortdocs --help
```

If global onboarding storage is used, also confirm:

- `~/.config/sortdocs/.env` is loaded by the launcher
- project-local `.env` still overrides or complements it as intended

If you plan to ship the desktop GUI, also confirm the local standalone build:

```bash
bash scripts/build-macos-app.sh
open dist/sortdocs.app
```

Expected behavior:

- the bundle build completes without import errors
- `dist/sortdocs.app` launches from Finder
- onboarding still works when no API key is configured
- the app reads `~/.config/sortdocs/.env` correctly

## Recommended Manual Checks

- run on a small folder with `--dry-run`
- run a confirmed apply on a test folder
- verify first-run onboarding in a clean shell
- verify `.sortdocsignore` rules on a test tree
- verify project-folder protection on a repo-like folder
- verify filename collision handling
- verify PDFs with real extractable text
- verify scanned or image-based PDFs
- verify files that are already in the correct place
- verify unchanged files are skipped on a second run

## After Release

- note real-world cases that ended up in review unexpectedly
- adjust heuristics or the AI prompt only after collecting concrete examples
- consider cleaning or migrating local memory if the path strategy changes
