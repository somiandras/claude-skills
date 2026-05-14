# Code Review Workflow

## Step 1: Get the Diff

Parse the user's input to determine what to review:

- **PR reference** (e.g., "PR #42 in pipeline", a URL): Use the project's skill/CLI to fetch the PR diff. Check CLAUDE.md for whether to use `bitbucket-api`, `gh`, etc.
- **Branch comparison** (e.g., "this branch vs develop"): Use `git diff <base>...<head>`.
- **JIRA ticket** (e.g., "DA-1234"): Look up the associated branch/PR.
- **Current changes** (no specific ref): Use `git diff HEAD`.

If the diff is empty, stop and tell the user.

Record `DIFF_SOURCE` (pr/branch/local) and `PR_REF` (if applicable).

## Step 2: Gather Context (parallel)

1. Get the diff content
2. Find CLAUDE.md files: root + any in directories touched by the diff
3. Get PR description or commit messages for intent

## Step 3: Detect Frontend Code

Frontend = diff contains `.js`, `.jsx`, `.ts`, `.tsx`, `.vue`, `.svelte`, `.css`, `.scss`, `.sass`, `.less`, `.html` files.

Exclude: `*.config.{js,ts}`, files under `migrations/`, `scripts/`, `cli/`, `server/`, `backend/`, `api/` (unless JSX/TSX), Node.js backend files.

## Step 4: Launch Review Agents (parallel)

Launch all agents simultaneously using the Agent tool. Each receives: full diff, change description, CLAUDE.md paths to read.

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

1. Parse each agent's JSON output
2. Deduplicate: same file+line range → keep highest confidence, merge descriptions
3. Filter: drop confidence < 60 (< 70 for security)
4. Sort: CRITICAL → IMPORTANT → MINOR → NITPICK

## Step 6: Terminal Summary (ALWAYS show this)

Always display a concise summary in the terminal, even if details are posted to a PR.

**If issues found:**

```
## Code Review: [title]

Reviewers: logic, style, tests, security, logging[, frontend]
Found: X blocking, Y suggestions

### Blocking (CRITICAL / IMPORTANT)

| # | Sev | Reviewer | File | Issue |
|---|-----|----------|------|-------|
| 1 | CRITICAL | logic | path:L42 | brief description |

### Suggestions (MINOR / NITPICK)

| # | Sev | Reviewer | File | Issue |
|---|-----|----------|------|-------|
| 1 | MINOR | style | path:L10 | brief description |

Verdict: REQUEST CHANGES / APPROVE WITH SUGGESTIONS / APPROVE
```

**If no issues:**

```
## Code Review: [title]

Reviewers: logic, style, tests, security, logging[, frontend]
No issues found. Verdict: APPROVE
```

Keep the terminal summary compact — one-line issue descriptions, no suggestions column. The detailed suggestions go into PR comments.

## Step 7: Post to PR (AUTOMATIC when reviewing a PR)

**When `DIFF_SOURCE` is `pr`, ALWAYS post comments immediately — do NOT ask for confirmation.** This is the whole point of reviewing a PR.

1. **Summary comment** on the PR with the full review (including suggestions)
2. **Inline comments** for each CRITICAL and IMPORTANT issue on the specific file+line
3. Use the appropriate tool per project CLAUDE.md (`gh`, `bitbucket-api`, `atlassian-manager` skill, etc.)
4. **For multi-line comments**: Write content to a temp file, then pass via `--content-file`. Example:
   ```bash
   # Write comment to temp file first
   Write tool → /tmp/pr_comment.md
   # Then post without shell operators
   bitbucket-api comment <repo> <pr_id> --content-file /tmp/pr_comment.md
   ```
   **NEVER use `$(cat <<'EOF' ...)` heredocs** — they trigger security approval prompts.

If posting fails, inform the user and show the full detailed review in the terminal instead.

## Rules

- All agents run in parallel — never sequential
- Never fabricate issues — empty results from an agent are fine
- Source-agnostic — adapt to whatever VCS/platform the project uses
- Don't second-guess agent findings — consolidate and present as-is
- Large diffs (> 2000 lines): warn the user and suggest smaller PRs
