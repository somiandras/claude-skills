# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

Personal Claude Code plugin marketplace. Distributes plugins via the Claude Code marketplace mechanism so the same versions run locally and in CI (GitHub Actions, Bitbucket Pipelines). No build, no tests, no runtime — just markdown + JSON manifests consumed by the Claude Code harness.

## Architecture

Two-level manifest layout:

- `.claude-plugin/marketplace.json` — top-level marketplace manifest. Lists each plugin with `name`, `version`, and `source` (relative path under `plugins/`). Marketplace name is `somiandras-skills`.
- `plugins/<name>/.claude-plugin/plugin.json` — per-plugin manifest.
- `plugins/<name>/skills/<skill>/SKILL.md` — skill entry point. Frontmatter `description` controls auto-trigger; `user-invocable: true` exposes it as `/<plugin>:<skill>`.
- `plugins/<name>/skills/<skill>/workflow.md` — full procedure, loaded on demand from SKILL.md via `${CLAUDE_SKILL_DIR}/workflow.md`. Keeps SKILL.md cheap to scan.
- `plugins/<name>/agents/*.md` — plugin-scoped subagents, invoked from a skill as `subagent_type: "<plugin>:<agent-name>"` (e.g. `code-review:logic-reviewer`).

The `code-review` plugin orchestrates 6 parallel reviewer subagents (logic, style, test, security, logging, frontend) from a single skill. Frontend agent is conditional on file extensions in the diff. Agents return findings; the skill consolidates, deduplicates, prints a terminal summary, and posts PR comments when reviewing a PR.

## Versioning

Bump `version` in both `.claude-plugin/marketplace.json` and the affected `plugins/*/.claude-plugin/plugin.json` together. Tag releases as `vX.Y.Z` so CI can pin via `...@vX.Y.Z`.

## Conventions when editing plugins

- Skill `description` is the trigger surface — phrases users would say must appear there. Keep it dense but accurate; auto-trigger relies on it.
- Workflow procedure goes in `workflow.md`, not SKILL.md. SKILL.md just points at it.
- Reviewer agents have a strict scope (see each agent's "What NOT to Flag" section) — don't blur boundaries between them.
- The orchestrator runs reviewers strictly in parallel via a single message with multiple Agent tool calls. Never make this sequential.
- When a workflow needs to write multi-line content (PR comments, etc.), write to a temp file and pass via `--content-file`. Never use heredocs (`$(cat <<'EOF' ...)`) — they trigger security approval prompts in the harness.

## Local install / update

```bash
claude plugin marketplace add https://github.com/somiandras/claude-skills.git
claude plugin install code-review@somiandras-skills
claude plugin marketplace update somiandras-skills
```

After installing, remove any shadowing copies under `~/.claude/skills/code-review/` and `~/.claude/agents/*-reviewer.md` — the plugin owns those.
