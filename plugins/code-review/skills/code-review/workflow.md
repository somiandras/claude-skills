# Code Review Workflow

## Step 1: Get the Diff

Parse the user's input to determine what to review:

- **PR reference** (e.g., "PR #42 in pipeline", a URL): Use the project's skill/CLI to fetch the PR diff. Check CLAUDE.md for whether to use `bitbucket-api`, `gh`, etc.
- **Branch comparison** (e.g., "this branch vs develop"): Use `git diff <base>...<head>`.
- **JIRA ticket** (e.g., "DA-1234"): Look up the associated branch/PR.
- **Current changes** (no specific ref): Use `git diff HEAD`.

If the diff is empty, stop and tell the user.

Record `DIFF_SOURCE` (pr/branch/local), `PR_REF` (if applicable), and `REPO_ROOT` — the absolute path to the repository being reviewed. Every path you later hand to an agent must live under `REPO_ROOT`.

## Step 2: Gather Context (parallel)

1. Get the diff content
2. Find CLAUDE.md files: root + any in directories touched by the diff
3. Get PR description or commit messages for intent
4. **Re-review check (PR only):** fetch the PR's existing comments. If an earlier summary comment from this skill exists (it starts with `## Code Review:` and contains a `Reviewed commit:` line), this is a re-review. Record `PRIOR_REVIEW` = that summary comment plus the inline comments posted with it, and the replies to them. Record `CHANGED_SINCE` = `git diff <reviewed commit>..<PR head>`. If the reviewed commit is no longer reachable (force-push), use the PR's commits newer than the comment's timestamp instead.

## Step 3: Detect Frontend Code

Frontend = diff contains `.js`, `.jsx`, `.ts`, `.tsx`, `.vue`, `.svelte`, `.css`, `.scss`, `.sass`, `.less`, `.html` files.

Exclude: `*.config.{js,ts}`, files under `migrations/`, `scripts/`, `cli/`, `server/`, `backend/`, `api/` (unless JSX/TSX), Node.js backend files.

## Step 4: Launch Review Agents (parallel)

Launch all agents simultaneously using the Agent tool. Each agent's prompt MUST spell out the following explicitly — never make a reviewer hunt for a file:

- **`REPO_ROOT`** — the absolute path to the repository under review.
- **The full diff** (path to the saved diff file, or inline) and the change description / intent.
- **Specific code pointers — resolved to absolute paths, never vague names.** This is mandatory:
  - List every substantive changed source file by absolute path, and distinguish reviewable code from bulk data / generated / deleted files so agents spend effort where it matters.
  - For any *cross-reference* you ask a reviewer to consult, give the exact path. E.g. if you want the security agent to compare against how the API validates a token, hand it `REPO_ROOT/apps/api/.../auth.ts` — NOT "the api app". If you don't know the exact path, locate it yourself (search scoped to `REPO_ROOT`) BEFORE launching, and pass the resolved path.
  - Relevant CLAUDE.md paths (root + any in touched directories).
- **Search-scoping rule — paste this verbatim into every agent prompt:**
  > Root ALL file searches (grep, glob, find) at `REPO_ROOT`. NEVER search from `$HOME`, `~`, `/`, or any home-rooted path — this is forbidden. Use absolute paths under `REPO_ROOT`. If a referenced file isn't where expected, report that in your findings rather than widening the search outside the repo.

A bare feature name ("the auth module", "the api app") is never acceptable — resolve it to a path first. Vague references are what cause agents to fall back to broad, home-rooted searches.

**Always launch:**

| Agent | `subagent_type` | Focus |
|-------|----------------|-------|
| Logic | `code-review:logic-reviewer` | Correctness, robustness, corner cases |
| Style | `code-review:style-reviewer` | Design principles, CLAUDE.md compliance |
| Tests | `code-review:test-reviewer` | Test strategy and coverage |
| Security | `code-review:security-reviewer` | Vulnerabilities, secrets, auth |
| Logging | `code-review:logging-reviewer` | Log levels, context, observability |

**Conditional (only if frontend files detected):**

| Agent | `subagent_type` | Focus |
|-------|----------------|-------|
| Frontend | `code-review:frontend-reviewer` | FE modularity, a11y, state management |

## Step 5: Consolidate

1. Parse each agent's JSON output and tag each finding with its `reviewer`
2. Deduplicate: same file+line range → keep highest confidence, merge descriptions
3. Filter: drop confidence < 60 (< 70 for security)

If no findings remain, skip Step 6 — the verdict is APPROVE.

## Step 6: Final Filter (ALWAYS run when findings remain)

Launch one `code-review:findings-filter` agent. It is the only judge of what reaches the author: it verifies each finding against the code, drops pedantic and speculative ones, corrects severities, and sets the verdict. Its prompt MUST include:

- `REPO_ROOT`, the diff, the change description / intent, and the CLAUDE.md paths (same as Step 4)
- The consolidated findings from Step 5 as a JSON array
- For re-reviews: `PRIOR_REVIEW` and `CHANGED_SINCE` from Step 2
- The search-scoping rule from Step 4, verbatim

Use its `kept` list, `dropped` list, and `verdict` as-is for Steps 7 and 8. Do not re-add dropped findings or change its severities.

## Step 7: Terminal Summary (ALWAYS show this)

Always display a concise summary in the terminal, even if details are posted to a PR.

**If issues kept:**

```
## Code Review: [title]

Reviewers: logic, style, tests, security, logging[, frontend]
Kept: X blocking, Y suggestions (Z dropped by the final filter)

### Blocking (CRITICAL / IMPORTANT)

| # | Sev | Reviewer | File | Issue |
|---|-----|----------|------|-------|
| 1 | CRITICAL | logic | path:L42 | brief description |

### Suggestions (MINOR)

| # | Sev | Reviewer | File | Issue |
|---|-----|----------|------|-------|
| 1 | MINOR | style | path:L10 | brief description |

### Dropped by the final filter

| Reviewer | File | Issue | Reason |
|----------|------|-------|--------|
| test | path:L80 | brief description | brief reason |

Verdict: REQUEST CHANGES / APPROVE WITH SUGGESTIONS / APPROVE
```

**If no issues kept:**

```
## Code Review: [title]

Reviewers: logic, style, tests, security, logging[, frontend]
No issues found (Z dropped by the final filter). Verdict: APPROVE
```

Keep the terminal summary compact — one-line issue descriptions, no suggestions column. The detailed suggestions go into PR comments. The dropped table appears only in the terminal, never on the PR.

## Step 8: Post to PR (AUTOMATIC when reviewing a PR)

**When `DIFF_SOURCE` is `pr`, ALWAYS post comments immediately — do NOT ask for confirmation.** This is the whole point of reviewing a PR.

Post only the findings the final filter kept.

1. **Summary comment** on the PR with the full review (including suggestions). It must start with `## Code Review:` and include a line `Reviewed commit: <full SHA of the PR head>` — Step 2 uses both to detect re-reviews.
2. **Inline comments** for each CRITICAL and IMPORTANT issue on the specific file+line, including its failure scenario
3. Use the appropriate tool per project CLAUDE.md (`gh`, `bitbucket-api`, `atlassian-manager` skill, etc.)
4. **For multi-line comments**: Write content to a temp file, then pass via `--content-file`. Example:
   ```bash
   # Write comment to temp file first
   Write tool → /tmp/pr_comment.md
   # Then post without shell operators
   bitbucket-api comment <repo> <pr_id> --content-file /tmp/pr_comment.md
   ```
   **NEVER use `$(cat <<'EOF' ...)` heredocs** — they trigger security approval prompts.
   **Pass a fully-resolved absolute path to `--content-file` — never a shell variable** (e.g. write `/home/job/tmp/pr_comment.md`, not `$CLAUDE_JOB_DIR/tmp/pr_comment.md`). The harness flags variable expansion as a security concern and forces an approval prompt, defeating any `bitbucket-api` allowlist rule. If your scratchpad path is given as a variable, resolve it to its literal value before building the command.

If posting fails, inform the user and show the full detailed review in the terminal instead.

## Rules

- All reviewer agents run in parallel — never sequential. The final filter runs once, after all of them finish
- Never fabricate issues — empty results from an agent are fine
- Source-agnostic — adapt to whatever VCS/platform the project uses
- The final filter decides what reaches the author — don't add your own findings or override its decisions
- Large diffs (> 2000 lines): warn the user and suggest smaller PRs
- Every agent prompt carries resolved, absolute code pointers and the search-scoping rule — no vague references, no home-rooted searches
