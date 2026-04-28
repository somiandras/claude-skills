---
name: code-review
description: Review a PR or branch diff using 6 parallel specialized reviewers (logic, style, tests, security, logging, frontend). Use when the user asks to review a PR, review code changes, or review a branch diff. Triggers on phrases like "review PR", "code review", "review this branch", "review changes".
user-invocable: true
argument-hint: "[PR reference, branch, or diff target]"
---

# Code Review Orchestrator

Read `${CLAUDE_SKILL_DIR}/workflow.md` for the full review procedure, then execute it.

Input from user: `$ARGUMENTS`
