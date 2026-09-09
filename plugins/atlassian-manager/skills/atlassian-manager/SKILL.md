---
name: atlassian-manager
description: Manage Jira issues and Bitbucket pull requests using REST API CLIs. Use for fetching tickets, transitioning issues, creating/merging PRs, or any Atlassian operations.
model: sonnet
---

# Atlassian Manager Skill

Uses the `jira-api` and `bitbucket-api` CLIs from the **`atlassian-api-cli`** tool.

## Dependency: `atlassian-api-cli`

The CLIs are **not** bundled with this plugin — install them once as a global `uv` tool
(source lives at `tools/atlassian-api-cli` in the `somiandras/claude-skills` repo):

```bash
# From the repo (canonical):
uv tool install "git+https://github.com/somiandras/claude-skills.git#subdirectory=tools/atlassian-api-cli"
# …or from a local checkout:
uv tool install /path/to/claude-skills/tools/atlassian-api-cli
```

This puts `jira-api`, `bitbucket-api`, and `atlassian-api` on PATH. If they're missing,
that's the fix. Then bootstrap the config below with `atlassian-api config init`.

## Configuration

All non-secret IDs (cloud IDs, project keys, board/issue-type/transition IDs,
Bitbucket workspace, repo slugs, dest branches) live in a single config file at
`$XDG_CONFIG_HOME/atlassian-cli/config.yaml` (default
`~/.config/atlassian-cli/config.yaml`). Credentials are **not** in the file —
set them in the environment (or `.env`): `ATLASSIAN_EMAIL`, `JIRA_API_TOKEN`,
`BITBUCKET_API_TOKEN`.

| Command | Purpose |
|---------|---------|
| `atlassian-api config show` | Print the resolved config (all IDs/values) |
| `atlassian-api config path` | Print the config file location |
| `atlassian-api config init` | Write a blank template (`--force` to overwrite) |

Run `config show` for current values rather than duplicating them here.

The config supports multiple **orgs** (Atlassian sites + Bitbucket workspaces).
Commands **auto-route** to an org by JIRA ticket prefix (`DA-123`) or Bitbucket
repo slug; `--org <name>` overrides, and `default_org` covers commands with no
prefix/slug (e.g. `search`, `link-types`, `release-version`).

**Collective routing (current config):** `DA-*` ↔ `data-importer` (dest `master`),
`COL-*` ↔ `analytics-agent` (dest `develop`), `AP-*` ↔ `advisor-portal` (dest `develop`).
Repo slugs ≠ local folder names: `pipeline` → `data-importer`, `analytics_agent` →
`analytics-agent`, `advisor_portal` → `advisor-portal`.

## Jira CLI Reference

```bash
# Get / Search
jira-api get DA-1234                       # Shows parent, linked issues (with link IDs), attachments
jira-api search "project=DA AND status='In Progress'"
jira-api search "project=DA AND sprint in openSprints()" --limit 10

# Transitions
jira-api transition DA-1234 in_progress    # or: done, 21 (by ID)
jira-api transitions DA-1234               # List available transitions

# Sprint
jira-api active-sprint
jira-api set-sprint DA-1234                # Add to active sprint
jira-api set-sprint DA-1234 1575           # Specific sprint by ID

# Create (--project is required — routes to the org by prefix)
jira-api create-issue "Title" --project DA --type Task
jira-api create-issue "Title" --project DA --type Bug --labels "bug,urgent"
jira-api create-issue "Title" --project DA --type Epic --description "..."
jira-api create-issue "Title" --project DA --type Task --parent DA-1234
jira-api create-issue "Title" --project COL --type Feature

# Update
jira-api update DA-1234 --summary "..." --description "..." --labels "..." --assignee "..." --priority "High"

# Assignees — no external lookup needed (token needs the read:jira-user scope)
jira-api whoami                            # Your account ID (for "assign to me")
jira-api find-user "Andras Somi"           # Resolve a name/email to account ID(s)
jira-api update DA-1234 --assignee me       # Assign to the token owner (you)
jira-api update DA-1234 --assignee "jane@example.com"  # Name/email → resolved to account ID

# Comments
jira-api comment DA-1234 "Comment text"
jira-api comments DA-1234

# Issue Links — reads as: <outward> <link_type> <inward>
jira-api link-types                                # List available link types
jira-api link DA-1234 Blocks DA-5678               # DA-1234 blocks DA-5678
jira-api link DA-1234 Relates DA-5678 -c "Note"    # With optional comment
jira-api unlink 12345                              # Remove by link ID (from `jira-api get`)

# Versions
jira-api versions DA
jira-api create-version 2026-02-10 --project DA --date 2026-02-10 --description "..."
jira-api release-version 12345
jira-api set-fix-version DA-1234 2026-02-09        # Replaces existing
jira-api set-fix-version DA-1234 2026-02-09 --add  # Adds to existing
```

**Common JQL:**
- DA: `project = DA AND sprint in openSprints() AND status != Done`
- COL: `project = COL AND status != Done`

## Bitbucket CLI Reference

```bash
# Pull Requests
bitbucket-api prs data-importer --state OPEN
bitbucket-api pr data-importer 123

# Diff — prints to stdout, or use -o to save straight to a file (no shell redirect needed)
bitbucket-api diff data-importer 123
bitbucket-api diff data-importer 123 -o /tmp/pr-123.diff

# Create PR (auto-transitions linked JIRA ticket to Review).
# --dest is optional: defaults to the repo's configured dest branch.
# For a multi-line description, write the body to a file and use --description-file —
# inline newlines render as literal \n in the PR otherwise. This sets the full
# description at creation time, so no follow-up update-pr round is needed.
bitbucket-api create-pr data-importer feature/DA-1234-add-feature "DA-1234: Add feature" \
    --description-file /tmp/pr-body.md
bitbucket-api create-pr advisor-portal feature/AP-1234-add "AP-1234: Add feature"   # dest develop from config
bitbucket-api create-pr data-importer feature/DA-1234-fix "Fix" --dest master --no-transition

# Update PR title/description (fix a botched description in place)
bitbucket-api update-pr data-importer 123 --title "DA-1234: New title"
bitbucket-api update-pr data-importer 123 --description "## Summary\nSingle-line only"
# For multi-line descriptions, write to a file and use --description-file — inline
# newlines render as literal \n in the PR otherwise.
bitbucket-api update-pr data-importer 123 --description-file /tmp/pr-body.md

# Merge (deletes the source branch by default; --no-close keeps it)
bitbucket-api merge data-importer 123
bitbucket-api merge data-importer 123 --strategy squash
bitbucket-api merge data-importer 123 --no-close

# Comments
bitbucket-api comment data-importer 123 "Comment text"
bitbucket-api inline-comment data-importer 123 "Needs null check" --file src/utils.py --line 42
bitbucket-api reply-comment data-importer 123 456 "Fixed"
bitbucket-api comments data-importer 123              # All comments
bitbucket-api comments data-importer 123 --active     # Unresolved only
bitbucket-api resolve-comment data-importer 123 456    # Only inline/diff comments can be resolved

# Branches
bitbucket-api branches data-importer
bitbucket-api create-branch data-importer release/2026-02-10 --source master
bitbucket-api delete-branch data-importer feature/old-branch
```

## Release Workflow

```bash
jira-api create-version 2026-02-10 --project DA --date 2026-02-10
bitbucket-api create-branch data-importer release/2026-02-10 --source master
bitbucket-api create-branch analytics-agent release/2026-02-10 --source develop
```

## Python API

Available via `from atlassian_api_cli import JiraAPI, BitbucketAPI` for complex operations. See package docs.

## Error Handling

| Error | Solution |
|-------|----------|
| `KeyError: 'ATLASSIAN_EMAIL'` | Set environment variables |
| 401 Unauthorized | Check API token validity and scopes |
| 404 Not Found | Verify issue key or PR ID |
| 429 Rate Limited | Wait and retry |
