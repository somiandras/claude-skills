# claude-skills

Personal Claude Code plugins, distributed via the marketplace mechanism so the
same versions run on my laptop and in CI (GitHub Actions, Bitbucket Pipelines)
without per-project drift.

## Plugins

| Plugin | What it does |
|--------|--------------|
| `code-review` | Review a PR or branch diff using 6 parallel specialized reviewers (logic, style, tests, security, logging, frontend). |

## Local install (laptop)

```bash
claude plugin marketplace add https://github.com/somiandras/claude-skills.git
claude plugin install code-review@somiandras-skills
```

Updating: `claude plugin marketplace update somiandras-skills`.

After installing, remove the user-level copies under `~/.claude/skills/code-review/`
and `~/.claude/agents/*-reviewer.md` so there's no shadowing — the plugin owns
those now.

## CI install (GitHub Actions)

```yaml
- uses: anthropics/claude-code-action@v1
  with:
    claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
    plugin_marketplaces: 'https://github.com/somiandras/claude-skills.git'
    plugins: 'code-review@somiandras-skills'
    prompt: '/code-review:code-review ${{ github.repository }}/pull/${{ github.event.pull_request.number }}'
```

## CI install (Bitbucket Pipelines)

Same pattern — clone this repo as a marketplace via HTTPS, no auth needed since
the repo is public.

## Layout

```
.claude-plugin/marketplace.json     # marketplace manifest
plugins/
  code-review/
    .claude-plugin/plugin.json      # plugin manifest
    skills/
      code-review/
        SKILL.md                    # entry — auto-triggers on review requests
        workflow.md                 # full procedure, read on demand
    agents/                         # 6 plugin-scoped reviewer subagents
      logic-reviewer.md             # invoked as code-review:logic-reviewer
      style-reviewer.md
      test-reviewer.md
      security-reviewer.md
      logging-reviewer.md
      frontend-reviewer.md
```

The skill auto-triggers when the user asks to review a PR / branch / diff
(via the description match in SKILL.md), and is also explicitly invocable as
`/code-review:code-review <args>`.

## Versioning

Bump `version` in `marketplace.json` and the affected plugin's `plugin.json`
together. Tag releases (`v0.1.0`) so CI can pin if needed:

```yaml
plugin_marketplaces: 'https://github.com/somiandras/claude-skills.git@v0.1.0'
```
