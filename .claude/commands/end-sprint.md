# /end-sprint

Commit all unstaged work on the current feature branch, push, and open a PR to `preview`.
A second mode (`--postmerge`) handles the cleanup once that PR has been merged on GitHub.

## Invocation
```
/end-sprint "<pr message>"
# example: /end-sprint "facilities prefetch with in-memory cache and ETag"

/end-sprint --postmerge [<branch>]
# example: /end-sprint --postmerge
# example: /end-sprint --postmerge feat/facilities-prefetch
```

The PR message argument is required for the default mode. If not provided, stop and report:
`⛔ PR message required. Usage: /end-sprint "<message>"`

If the first argument is `--postmerge`, skip Steps 1-7 below and go straight to
**Post-merge mode** at the end of this file.

---

## Step 1 — Branch check

```bash
git branch --show-current
```

Store the result as `CURRENT_BRANCH`.

**If `CURRENT_BRANCH` is `main` or `preview`:**
Stop immediately. Do not stage, commit, or push anything.
Report:
```
⛔ On protected branch '<CURRENT_BRANCH>'.
/end-sprint must be run from a feature branch (feat/, fix/, refactor/, chore/, docs/).
```

**If `CURRENT_BRANCH` is any other value:** proceed.

---

## Step 2 — Inspect working tree

```bash
git status --short
```

Three possible states:

**A — Nothing to commit (clean tree):**
```
# git status --short returns empty output
```
Skip Steps 3 and 4. Proceed directly to Step 5 (push).

**B — Unstaged or untracked changes present:**
Proceed to Step 3.

**C — Already staged but not committed:**
Proceed to Step 4 directly (skip `git add`).

---

## Step 3 — Stage all changes on this branch

```bash
# Stage all modified and untracked files
# /end-sprint is an explicit sprint termination — git add . is permitted here
# because the intent is to commit everything remaining
git add .

# Confirm what was staged
git diff --staged --stat
```

Report what was staged before committing.

---

## Step 4 — Commit staged changes

Infer the commit type from the branch name prefix:

| Branch prefix | Commit type |
|---|---|
| `feat/` | `feat` |
| `fix/` | `fix` |
| `refactor/` | `refactor` |
| `chore/` | `chore` |
| `docs/` | `docs` |
| anything else | `chore` |

Extract the scope from the branch name — the part after the `/`:
`feat/backend-api` → scope `backend-api`
`refactor/home-ui` → scope `home-ui`

```bash
git commit -m "<type>(<scope>): end-sprint snapshot — <CURRENT_BRANCH>"
```

Example for branch `feat/facilities-prefetch`:
```bash
git commit -m "feat(facilities-prefetch): end-sprint snapshot — feat/facilities-prefetch"
```

**Never add Claude or any AI assistant as co-author.**

---

## Step 5 — Push branch

```bash
git push -u origin <CURRENT_BRANCH>
```

If the branch already has upstream tracking, `git push` without arguments is fine.
If push fails, report the error and stop — do not attempt to force push.

---

## Step 6 — Open PR to `preview`

```bash
gh pr create \
  --base preview \
  --label run-eval \
  --head <CURRENT_BRANCH> \
  --title "<type>(<scope>): <pr message>" \
  --body "Sprint close: <pr message>

Branch: \`<CURRENT_BRANCH>\`
Target: \`preview\`

## Changes
> Summarise the main changes committed in this sprint in 2-4 bullet points
> based on what was staged and committed in Steps 3-4 and any prior commits
> on this branch. Read the git log to generate this accurately.

\`\`\`bash
git log preview..<CURRENT_BRANCH> --oneline
\`\`\`

## Checklist
- [ ] TypeScript compiles clean
- [ ] No hardcoded secrets
- [ ] Ready for preview deployment"
```

`--label run-eval` is always attached: it starts the CI eval gate (`.github/workflows/eval-gate.yml`, Groq free tier). The label must already exist on the repo; if `gh pr create` fails because it does not, stop and report instead of dropping the flag. Never add it with `gh pr edit` (broken on this repo); for an existing PR use `gh api repos/{owner}/{repo}/issues/<n>/labels -f 'labels[]=run-eval'`.

The `--title` uses the same conventional commit format as the commit message.
The `--body` bullet points are generated from `git log preview..<CURRENT_BRANCH> --oneline`
— read the actual log, do not invent or guess what changed.

---

## Step 7 — Report outcome

```
✓ Sprint closed

Branch:  <CURRENT_BRANCH>
Commit:  <commit hash if new commit was made, or "none — tree was clean">
Pushed:  yes
PR:      <URL returned by gh pr create>
Target:  preview

Next steps:
  1. Review the PR in GitHub
  2. Once approved/mergeable: /end-sprint --postmerge
```

---

## Post-merge mode (`--postmerge`)

Run this after the PR opened above has been reviewed and is mergeable. It merges the PR,
syncs local `preview`, and deletes the feature branch both locally and on origin.

`<TARGET_BRANCH>` is the optional `<branch>` argument, or `CURRENT_BRANCH` from
`git branch --show-current` if omitted.

### P1 — Find and validate the PR

```bash
gh pr view <TARGET_BRANCH> --json number,state,mergeable,mergeStateStatus,baseRefName
```

**If no open PR is found for `<TARGET_BRANCH>`:** stop and report:
`⛔ No open PR found for '<TARGET_BRANCH>'. Run /end-sprint "<message>" first.`

**If `baseRefName` is not `preview`:** stop and report:
`⛔ PR for '<TARGET_BRANCH>' does not target preview. Resolve manually.`

**If `mergeable` is not `MERGEABLE` or `mergeStateStatus` is not `CLEAN`:** stop and report:
`⛔ PR #<number> is not cleanly mergeable (<mergeStateStatus>). Resolve conflicts/checks first.`

### P2 — Merge

```bash
gh pr merge <number> --merge
```

If the merge fails (e.g. branch protection, failing required check), stop and report the error.
Do not retry with `--admin` or force flags.

### P3 — Sync local `preview`

```bash
git switch preview
git pull origin preview
```

### P4 — Delete the feature branch

```bash
git branch -d <TARGET_BRANCH>
git push origin --delete <TARGET_BRANCH>
```

If `git branch -d` fails because the branch isn't fully merged locally (stale local state),
report the error and stop rather than forcing with `-D`.

### P5 — Report outcome

```
✓ Post-merge complete

PR:      #<number> merged into preview
Local:   preview updated to <new HEAD short hash>
Deleted: <TARGET_BRANCH> (local + origin)

Next: git checkout -b <next-branch> && git push -u origin <next-branch>
```

---

## Hard Stops

| Condition | Action |
|---|---|
| No PR message argument (default mode) | Stop before doing anything |
| Branch is `main` or `preview` (default mode) | Stop before doing anything |
| Push fails | Stop after push attempt — do not open PR |
| `gh` CLI not authenticated | Report: `⛔ GitHub CLI not authenticated. Run: gh auth login` |
| `gh pr create` fails because PR already exists | Report the existing PR URL and stop |
| `--postmerge`: no open PR found for branch | Stop before doing anything |
| `--postmerge`: PR not targeting `preview` | Stop before doing anything |
| `--postmerge`: PR not cleanly mergeable | Stop before merging |
| `--postmerge`: `gh pr merge` fails | Stop — do not retry with force/admin flags |
| `--postmerge`: local branch delete fails (not fully merged) | Stop before deleting remote branch |