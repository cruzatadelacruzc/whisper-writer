# GitHub Workflow, CI, and Branch Protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the repo to a protected two-branch flow (`main` + `develop`) with a GitHub Actions CI (jobs `tests` and `lint`) required on every PR.

**Architecture:** One workflow file runs two independent jobs on PRs to and pushes on `develop`/`main`. Branch protection is implemented as GitHub **rulesets** whose JSON definitions live in the repo and are applied via `gh api`. Bootstrap is ordered so required checks exist before rules demand them.

**Tech Stack:** GitHub Actions (ubuntu-latest, Python 3.10), pytest 9.1.1, ruff 0.16.0, GitHub rulesets API via `gh`.

**Spec:** `docs/superpowers/specs/2026-07-30-github-workflow-ci-design.md`

## Global Constraints

- Repo: `cruzatadelacruzc/whisper-writer` (public). Default branch: `main`. Open PR #1 must be merged by the user before Task 1 proceeds.
- `requirements.txt` is UTF-16 LE with CRLF — **never convert or edit it**. Dev deps go in a separate UTF-8 `requirements-dev.txt`.
- `setuptools<81` must be enforced wherever deps are installed (webrtcvad needs `pkg_resources`).
- Local commands always use `venv/bin/python` / `venv/bin/pip` / `venv/bin/ruff` from the project root.
- Never commit `src/config.yaml` (gitignored user config) or `index.html` (unrelated file at repo root).
- CI check names are exactly `tests` and `lint` — job ids AND ruleset `context` values must match verbatim.
- Every commit message ends with the trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- The GUI app needs `DISPLAY=:0`; the test suite must stay headless (`env -u DISPLAY -u WAYLAND_DISPLAY`).

---

### Task 1: Bootstrap branches (merge gate, create `develop`, cleanup)

**Files:**
- No file changes; git/GitHub state only.

**Interfaces:**
- Consumes: merged PR #1 (`feature/clipboard-injection-history` → `main`).
- Produces: remote branch `develop` (from updated `main`) that Tasks 2–7 build on; old feature branch and SDD workspace removed.

- [ ] **Step 1: Verify PR #1 is merged (hard gate)**

Run: `gh pr view 1 --json state,mergedAt --jq '{state, mergedAt}'`
Expected: `"state": "MERGED"`.
If it is still OPEN: **stop and ask the user** to merge it (or for explicit permission to run `gh pr merge 1 --merge`). Do not proceed unmerged.

- [ ] **Step 2: Sync local main**

```bash
git checkout main
git pull
git log --oneline -3
```
Expected: log shows the merge of PR #1 (Phase 3 commits present).

- [ ] **Step 3: Delete the merged feature branch (local + remote)**

```bash
git branch -d feature/clipboard-injection-history
git push origin --delete feature/clipboard-injection-history || echo "remote branch already deleted (GitHub auto-delete)"
```
Expected: local delete succeeds (`-d` proves it is merged); remote delete succeeds or was already done via the GitHub UI.

- [ ] **Step 4: Delete the finished SDD workspace**

```bash
rm -rf .superpowers/sdd/2026-07-29-clipboard-injection-and-history
```
(Untracked directory; the work has landed on `main`, so per the SDD skill the ledger is deleted.)

- [ ] **Step 5: Create and push develop**

```bash
git checkout -b develop
git push -u origin develop
```

- [ ] **Step 6: Verify develop exists on GitHub**

Run: `gh api repos/cruzatadelacruzc/whisper-writer/branches/develop --jq .name`
Expected: `develop`

---

### Task 2: Feature branch with spec, plan, and dev tooling

**Files:**
- Create: `requirements-dev.txt`
- Create: `ruff.toml`
- Commit (already on disk, untracked): `docs/superpowers/specs/2026-07-30-github-workflow-ci-design.md`, `docs/superpowers/plans/2026-07-30-github-workflow-ci.md`

**Interfaces:**
- Consumes: branch `develop` (Task 1).
- Produces: branch `feature/github-workflow-ci`; `requirements-dev.txt` (used by CI in Task 4 and locally in Task 3); `ruff.toml` (governs `ruff check .` everywhere).

- [ ] **Step 1: Create the feature branch from develop**

```bash
git checkout develop
git checkout -b feature/github-workflow-ci
```

- [ ] **Step 2: Commit the design docs**

```bash
git add docs/superpowers/specs/2026-07-30-github-workflow-ci-design.md docs/superpowers/plans/2026-07-30-github-workflow-ci.md
git commit -m "docs: add GitHub workflow/CI design spec and implementation plan

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 3: Create requirements-dev.txt (UTF-8, plain LF)**

```
pytest==9.1.1
ruff==0.16.0
```

- [ ] **Step 4: Create ruff.toml**

```toml
# Lint for real errors only (pyflakes + basic pycodestyle); no style
# reformatting of the inherited WhisperWriter code.
target-version = "py310"
exclude = ["venv"]
```
(Default rule set = `E4`, `E7`, `E9`, `F` — unused imports, dead variables, syntax/comparison errors.)

- [ ] **Step 5: Install dev deps into the venv and verify**

```bash
venv/bin/pip install -r requirements-dev.txt
venv/bin/ruff --version
```
Expected: `ruff 0.16.0` (pytest 9.1.1 already present — no-op).

- [ ] **Step 6: Verify the files' encoding is sane**

Run: `file requirements-dev.txt ruff.toml`
Expected: both reported as ASCII/UTF-8 text (NOT UTF-16 — only the legacy `requirements.txt` is UTF-16).

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt ruff.toml
git commit -m "chore: add dev requirements (pytest, ruff) and ruff config

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Fix existing ruff violations (RED → GREEN)

**Files:**
- Modify: whatever `ruff check .` reports — expected at least `src/main.py` (unused `import time` at line 3, unused `Controller` import at line 5, unused local `model_path` around line 53); likely unused Qt imports in `src/ui/*.py` (e.g. `QApplication` in `src/ui/base_window.py:3`).

**Interfaces:**
- Consumes: `ruff.toml` + `venv/bin/ruff` (Task 2).
- Produces: a codebase where `ruff check .` exits 0 — required for the CI `lint` job (Task 4/5) to pass.

- [ ] **Step 1: RED — capture current violations**

Run: `venv/bin/ruff check .`
Expected: FAILS listing violations (F401 unused imports, F841 unused variables). Save the list; it is the exact work order for Step 2.

- [ ] **Step 2: Fix every reported violation minimally**

Rules for each fix:
- F401 (unused import): delete only that import name (keep the line if other names on it are used).
- F841 (unused variable): delete the assignment line, e.g. in `src/main.py` remove `model_path = model_options.get('local', {}).get('model_path')` — keep the `model_options` line, which IS used.
- Do NOT reformat, rename, or "improve" anything else. If ruff reports something non-mechanical (e.g. E7 comparison bug), fix exactly that expression and nothing more.

- [ ] **Step 3: GREEN — ruff passes**

Run: `venv/bin/ruff check .`
Expected: `All checks passed!`

- [ ] **Step 4: Full test suite still green**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/`
Expected: `18 passed`.

- [ ] **Step 5: App smoke test (imports were touched)**

```bash
DISPLAY=:0 venv/bin/python run.py > /tmp/claude-1000/-mnt-D4B873F1B873D10A-Dev-Python-whisper-writer/aba5318a-aa21-484f-aec9-983211dd7627/scratchpad/smoke.log 2>&1 &
SMOKE_PID=$!
sleep 75   # model load takes ~48s on this machine
kill -0 "$SMOKE_PID" && echo ALIVE || echo DEAD
kill -9 "$SMOKE_PID"
grep -i "traceback" /tmp/claude-1000/-mnt-D4B873F1B873D10A-Dev-Python-whisper-writer/aba5318a-aa21-484f-aec9-983211dd7627/scratchpad/smoke.log || echo NO_TRACEBACK
```
Expected: `ALIVE` and `NO_TRACEBACK`. (SIGKILL because the evdev backend can swallow SIGTERM. Note: stdout is block-buffered — the log fills at exit, so grep AFTER the kill.)

- [ ] **Step 6: Commit**

```bash
git add -u src/
git commit -m "refactor: remove unused imports and variables flagged by ruff

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
(Use `git add -u src/` — never `-A` — so stray files like `index.html` can't slip in.)

---

### Task 4: CI workflow, ruleset definitions, CLAUDE.md note

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/rulesets/develop.json`
- Create: `.github/rulesets/main.json`
- Modify: `CLAUDE.md` (add branch-flow section)

**Interfaces:**
- Consumes: `requirements-dev.txt` (Task 2), lint-clean codebase (Task 3).
- Produces: jobs named exactly `tests` and `lint` (contexts required by the rulesets); ruleset JSONs applied in Task 6 via `gh api --input`.

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
    branches: [develop, main]
  push:
    branches: [develop, main]

jobs:
  tests:
    name: tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'
      - name: Install PortAudio (sounddevice loads it at import time)
        run: sudo apt-get update && sudo apt-get install -y libportaudio2
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt "setuptools<81"
      - name: Run tests
        run: python -m pytest tests/

  lint:
    name: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - name: Install ruff
        run: pip install ruff==0.16.0
      - name: Run ruff
        run: ruff check .
```

**Contingency (apply ONLY if the `tests` job later fails on the UTF-16 `requirements.txt`):** insert this step before "Install dependencies" and change that step to use the converted copy:

```yaml
      - name: Convert requirements.txt to UTF-8 copy (repo file is UTF-16 LE)
        run: iconv -f UTF-16LE -t UTF-8 requirements.txt | tr -d '\r' > /tmp/requirements-utf8.txt
```
with `pip install -r /tmp/requirements-utf8.txt -r requirements-dev.txt "setuptools<81"`.

- [ ] **Step 2: Create `.github/rulesets/develop.json`**

```json
{
  "name": "protect-develop",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/develop"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "tests" },
          { "context": "lint" }
        ]
      }
    }
  ],
  "bypass_actors": []
}
```

- [ ] **Step 3: Create `.github/rulesets/main.json`**

Identical to develop.json except two values:

```json
{
  "name": "protect-main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/main"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "tests" },
          { "context": "lint" }
        ]
      }
    }
  ],
  "bypass_actors": []
}
```

- [ ] **Step 4: Validate syntax locally**

```bash
venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('YAML OK')"
venv/bin/python -m json.tool .github/rulesets/develop.json > /dev/null && echo "develop.json OK"
venv/bin/python -m json.tool .github/rulesets/main.json > /dev/null && echo "main.json OK"
```
Expected: `YAML OK`, `develop.json OK`, `main.json OK`.

- [ ] **Step 5: Add branch-flow section to CLAUDE.md**

Append under the "## Commands" section (keep CLAUDE.md in English):

```markdown
## Branch flow & CI

- `main` = stable; `develop` = integration. Both are protected by rulesets
  (`.github/rulesets/*.json`): no direct pushes, no force-push/deletion;
  changes land only via PR with the `tests` and `lint` checks green
  (0 approvals required — single-account repo, GitHub cannot self-approve).
- Work branches (`feature/...`, `fix/...`) fork from `develop` and PR back
  into `develop`; releases are a PR `develop` → `main`.
- CI: `.github/workflows/ci.yml` (Python 3.10, installs
  `requirements.txt` + `requirements-dev.txt` + `setuptools<81`).
  Run locally: `venv/bin/ruff check .` and
  `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/`.
- Re-apply a ruleset after changes:
  `gh api --method POST repos/cruzatadelacruzc/whisper-writer/rulesets --input .github/rulesets/<file>.json`
  (POST creates; to modify an existing one use PUT `.../rulesets/<id>`).
```

- [ ] **Step 6: Commit**

```bash
git add .github/ CLAUDE.md
git commit -m "ci: add GitHub Actions workflow and branch ruleset definitions

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Open the setup PR to develop, get CI green, merge

**Files:**
- No new files; GitHub state (PR, workflow runs). Possible iteration commits on `feature/github-workflow-ci` if CI is red.

**Interfaces:**
- Consumes: branch `feature/github-workflow-ci` complete (Tasks 2–4).
- Produces: CI proven green on GitHub; workflow + rulesets JSON merged into `develop` (Task 6 applies them from there).

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feature/github-workflow-ci
```

- [ ] **Step 2: Create the PR against develop**

```bash
gh pr create --base develop --head feature/github-workflow-ci \
  --title "ci: GitHub Actions workflow, ruff, and branch ruleset definitions" \
  --body "$(cat <<'EOF'
## Summary
- CI workflow with two jobs (`tests`, `lint`) on PRs to and pushes on `develop`/`main`
- `requirements-dev.txt` (pytest 9.1.1, ruff 0.16.0) and `ruff.toml`; legacy lint violations fixed
- Ruleset JSON definitions for `develop`/`main` protection (applied via `gh api` after this merges)
- Design spec + implementation plan committed under `docs/superpowers/`

## Test plan
- This PR exercises the new CI on itself: both checks must be green
- Locally: 18/18 pytest headless, `ruff check .` clean, app smoke test alive

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Watch the checks**

Run: `gh pr checks --watch` (in the feature branch checkout)
Expected: `tests` PASS, `lint` PASS.
If a check fails: `gh run view --log-failed` to read the error, fix on the feature branch (for a UTF-16 pip failure use the Task 4 Step 1 contingency), commit, push, watch again. Repeat until green.

- [ ] **Step 4: Merge the PR**

```bash
gh pr merge --merge --delete-branch
git checkout develop && git pull
```
Expected: merged; local `develop` now contains `.github/`. (develop is not yet protected — that is Task 6; this is the designed bootstrap order.)

- [ ] **Step 5: Verify the post-merge push run on develop**

Run: `gh run list --branch develop --limit 2`
Expected: the `push`-triggered CI run on develop completes green.

---

### Task 6: Apply rulesets and prove the protection

**Files:**
- No file changes; GitHub state only (uses `.github/rulesets/*.json` now on `develop`).

**Interfaces:**
- Consumes: merged ruleset JSONs (Task 5); green check contexts `tests`/`lint` existing on the repo.
- Produces: active rulesets `protect-develop` and `protect-main` — Task 7's PR runs under them.

- [ ] **Step 1: Apply both rulesets**

```bash
git checkout develop
gh api --method POST repos/cruzatadelacruzc/whisper-writer/rulesets --input .github/rulesets/develop.json
gh api --method POST repos/cruzatadelacruzc/whisper-writer/rulesets --input .github/rulesets/main.json
```
Expected: each returns HTTP 201 with the created ruleset JSON (note the `id` fields).

- [ ] **Step 2: Verify both are listed and active**

Run: `gh api repos/cruzatadelacruzc/whisper-writer/rulesets --jq '.[] | {id, name, enforcement}'`
Expected: `protect-develop` and `protect-main`, both `"enforcement": "active"`.

- [ ] **Step 3: NEGATIVE test — direct push must be rejected**

```bash
git checkout develop
git commit --allow-empty -m "test: protection probe (must be rejected)"
git push origin develop
```
Expected: **push REJECTED** by GitHub with a rules violation (e.g. "Changes must be made through a pull request").
If the push is ACCEPTED, the protection is broken: STOP, revert with a forced investigation of the ruleset (do not continue to Task 7).

- [ ] **Step 4: Clean the probe commit from the local branch**

```bash
git reset --hard origin/develop
git log --oneline -1
```
Expected: local develop back at the remote tip; probe commit gone.

---

### Task 7: First protected release PR — develop → main

**Files:**
- No file changes; GitHub state only.

**Interfaces:**
- Consumes: protected branches + green CI (Tasks 5–6).
- Produces: `main` with CI + docs + lint fixes; the full loop (feature → develop → main) proven under protection.

- [ ] **Step 1: Create the release PR**

```bash
gh pr create --base main --head develop \
  --title "Release: CI workflow, lint cleanup, and branch protection setup" \
  --body "$(cat <<'EOF'
## Summary
First release under the new branch flow: brings the CI workflow, ruff config
and lint fixes, ruleset definitions, and design docs from `develop` to `main`.

## Test plan
- `tests` and `lint` checks must pass on this PR (required by ruleset protect-main)
- Direct-push rejection on develop already verified (Task 6 negative test)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Confirm the merge is blocked until checks pass, then green**

Run: `gh pr checks --watch`
Expected: `tests` PASS, `lint` PASS. (While they run, `gh pr view --json mergeStateStatus --jq .mergeStateStatus` reports `BLOCKED` — that is the ruleset working.)

- [ ] **Step 3: Merge — WITHOUT deleting develop**

```bash
gh pr merge --merge
git checkout main && git pull
git checkout develop
```
**Never pass `--delete-branch` here** — `develop` is permanent.

- [ ] **Step 4: Final verification sweep**

```bash
gh run list --branch main --limit 2
gh api repos/cruzatadelacruzc/whisper-writer/rulesets --jq '.[] | {name, enforcement}'
git fetch --prune && git branch -a
```
Expected: green push-run on `main`; both rulesets active; branches present: `main`, `develop` (local and remote), no stale feature branches.

- [ ] **Step 5: Report to the user**

Summarize in Spanish: both branches protected, CI green on both, negative test proved direct pushes are rejected, and the day-to-day flow going forward (feature branch → PR to develop → release PR to main).
