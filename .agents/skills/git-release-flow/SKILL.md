---
name: git-release-flow
description: Ship a feature branch via PR to main (this project's chosen release flow). Use when asked to commit, push, and open a PR for a finished change.
---

# Git release flow: Branch + PR to main

1. Run the gate: `npm run check` (typecheck + full unit suite). Do not proceed
   if it fails.
2. If the change touches `apps/operator/public/`, `apps/super-admin/public/`
   or `apps/web/public/`, run the Help Center gate. CI runs it, but
   `npm run check` does not:
   `HELP_IMPACT_BASE=origin/main npm run check:help-impact`.
   If it fails, update `docs/help/articles/`, or review the Help Center and
   add `[help-not-needed]` to a commit message with the reason.
3. Commit on the current feature branch. **Never commit on `main`.**
4. Never commit `.tmp/`. Confirm `git status` shows it untouched/excluded
   before committing.
5. Push: `git push -u origin HEAD`.
6. Open a PR to `main`: `gh pr create --base main`.
7. No tags.
8. Merging to `main` triggers the staging deploy. Do not merge the PR
   yourself — leave it for review.
