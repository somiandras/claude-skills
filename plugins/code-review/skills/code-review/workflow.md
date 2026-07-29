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
   **Pass a fully-resolved absolute path to `--content-file` — never a shell variable** (e.g. write `/home/job/tmp/pr_comment.md`, not `$CLAUDE_JOB_DIR/tmp/pr_comment.md`). The harness flags variable expansion as a security concern and forces an approval prompt, defeating any `bitbucket-api` allowlist rule. If your scratchpad path is given as a variable, resolve it to its literal value before building the command.

If posting fails, inform the user and show the full detailed review in the terminal instead.

## Rules

- All agents run in parallel — never sequential
- Never fabricate issues — empty results from an agent are fine
- Source-agnostic — adapt to whatever VCS/platform the project uses
- Don't second-guess agent findings — consolidate and present as-is
- Large diffs (> 2000 lines): warn the user and suggest smaller PRs
- Every agent prompt carries resolved, absolute code pointers and the search-scoping rule — no vague references, no home-rooted searches
