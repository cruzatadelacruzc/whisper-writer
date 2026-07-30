# GitHub Workflow, CI, and Branch Protection — Design

**Date:** 2026-07-30
**Status:** Approved by user (brainstorming session)
**Repo:** https://github.com/cruzatadelacruzc/whisper-writer (public, single owner account)

## Goal

Move the repository from a single unprotected `main` branch to a two-branch
flow (`main` + `develop`) with CI on GitHub Actions and branch protection, so
that nothing lands on either branch without a pull request whose checks are
green.

## Decisions made during brainstorming

| Question | Decision |
|----------|----------|
| Fate of open PR #1 (Phase 3, already verified live) | User merges it into `main` first; `develop` is created from the updated `main`. |
| Separate GitHub identity for Claude | **No second account.** Everything runs under the owner's account. GitHub forbids approving your own PRs, so the merge gate is "PR required + CI green" with **0 required approvals**. |
| Strictness of `develop` | Fully protected: no direct pushes; every change arrives via feature branch → PR → green CI → merge. |
| CI scope | Tests **and** linter (ruff). |
| Mechanism / layout | **Rulesets** (not classic branch protection) + a **single** `ci.yml` workflow with two jobs. |

## Branch model

- `main` — stable/deliverable. Only receives PRs **from `develop`** with green CI.
- `develop` — daily integration. Only receives PRs from work branches
  (`feature/...`, `fix/...`) with green CI.
- No direct pushes to either branch. All work starts on a work branch.
- Merge method: GitHub default (merge commit). Revisit later if desired.

## CI workflow — `.github/workflows/ci.yml`

**Triggers:** `pull_request` targeting `develop` or `main`; `push` to
`develop` or `main` (post-merge confirmation).

**Job `tests`** (ubuntu-latest):
1. `actions/setup-python` with Python **3.10** (matches the local venv) and pip cache.
2. `sudo apt-get install -y libportaudio2` — `sounddevice` loads PortAudio at
   import time. `webrtcvad` compiles with the runner's preinstalled gcc.
3. `pip install -r requirements.txt -r requirements-dev.txt "setuptools<81"`
   — the setuptools pin is required because `webrtcvad` imports `pkg_resources`
   (removed in setuptools 81).
4. `python -m pytest tests/` with no display (the suite is headless by design).

The tests import `faster_whisper` but never instantiate a model, so CI makes
**no** HuggingFace downloads.

**Job `lint`** (ubuntu-latest): setup-python → `pip install ruff` (pinned via
`requirements-dev.txt`) → `ruff check .`.

**Known risk & fallback:** `requirements.txt` is UTF-16 LE (must not be
converted in the repo — see CLAUDE.md). Local pip tolerates it; if the
runner's pip chokes on it, add a workflow step converting it with `iconv` to a
temporary UTF-8 copy and install from that. The original file is never touched.

## New support files

- **`requirements-dev.txt`** — plain UTF-8 (the UTF-16 `requirements.txt` is
  untouched). Contents: `pytest` and `ruff`, both version-pinned.
- **`ruff.toml`** — `target-version = "py310"`, default rule set (pyflakes +
  basic pycodestyle errors: unused imports, dead variables, broken
  comparisons), `exclude = ["venv"]`. No aggressive style rules — the goal is
  catching real errors, not reformatting inherited WhisperWriter code.
- Existing ruff violations in the legacy code are fixed inside the setup PR
  (default rules → few and mechanical, e.g. unused imports in `main.py`).

## Branch protection — rulesets

Two identical rulesets, one targeting `main`, one targeting `develop`.
Created via `gh api`; their JSON definitions are versioned in the repo at
`.github/rulesets/main.json` and `.github/rulesets/develop.json` so they are
documented and restorable with one command.

Rules in each:
- **Require a pull request** before merging (required approvals: 0 — see
  decisions table).
- **Required status checks:** `tests` and `lint`, with "require branch to be
  up to date" enabled.
- **Block force pushes** and **restrict deletions**.
- **No bypass actors.** Emergency escape hatch = the owner disables the
  ruleset in the GitHub UI, explicitly.

Check names in the ruleset must match the workflow job names exactly
(`tests`, `lint`).

## Bootstrap order

1. User merges **PR #1** into `main` (pre-protection; work already verified).
2. Create `develop` from updated `main`; push it.
3. On branch `feature/github-workflow-ci`: this spec, `ci.yml`,
   `requirements-dev.txt`, `ruff.toml`, ruleset JSONs, lint fixes. Open
   **PR → develop**; this PR exercises the new CI and must come out green.
4. After merging, apply the rulesets via `gh api` (only now do the required
   checks exist — enabling them earlier would deadlock every PR).
5. First **PR develop → main** brings CI to `main` and closes the loop under
   the new flow.

## Verification

1. **Negative:** direct `git push` of a trivial commit to `develop` must be
   **rejected** by GitHub.
2. **Positive:** the setup PR shows both checks green, with the merge button
   blocked until they are.
3. `gh api /repos/cruzatadelacruzc/whisper-writer/rulesets` lists both active
   rulesets.

## Error handling

Red CI on the setup PR → iterate on the feature branch until green; nothing
broken can merge, so the system proves itself. If a required check never
reports (name mismatch), fix the ruleset JSON and re-apply.

## Out of scope (YAGNI)

Merge-method policy, CODEOWNERS, PR templates, issue templates, deployments,
release automation, coverage reporting. Any of these can be added later in
its own PR.
