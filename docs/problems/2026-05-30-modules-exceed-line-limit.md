# Modules exceed 300-line guideline

1. **Time & Date:** 2026-05-30T00:00:00Z
2. **Name:** `build.py` and CLI `flash.py` exceed 300-line guideline
3. **Issue:** Two core modules are longer than the repo’s ~300-line refactor threshold, making them harder to review and test in isolation
4. **Severity:** S5 (Note)
5. **Location:** `packages/image/src/easymanet_image/build.py` (391 lines), `apps/cli/src/easymanet_cli/flash.py` (323 lines)
6. **Expected:** Modules stay under ~300 lines or are split along clear boundaries (build orchestration vs Dockerfile/cache vs CLI wiring; flash flow vs disk selection vs image resolution)
7. **Actual:** `build.py` holds OpenMANET Docker build orchestration end-to-end; CLI `flash.py` holds the interactive flash command, confirmations, and image/disk resolution in one file
8. **Reproduction:**
   1. `wc -l packages/image/src/easymanet_image/build.py apps/cli/src/easymanet_cli/flash.py`
   2. Skim structure for natural split points (e.g. `build.py` ~lines 160–185 Docker helpers vs CLI entry; CLI `flash.py` Typer command vs helpers)
9. **Notes:** Non-blocking for PR #1 merge. Suggested later splits: `build.py` → dockerfile/cache module + thin CLI adapter; CLI `flash.py` → flash orchestration + disk/image prompt helpers. No behavior change required until someone touches these areas heavily.
