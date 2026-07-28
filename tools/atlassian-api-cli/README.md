# atlassian-api-cli

A small, config-driven CLI for Jira and Bitbucket Cloud REST APIs — a reliable
alternative to the Atlassian MCP server. Exposes three commands: `jira-api`,
`bitbucket-api`, and `atlassian-api` (the combined entry point).

It is the runtime dependency of the **`atlassian-manager`** Claude Code skill
(`plugins/atlassian-manager` in this repo), but it is a standalone tool — nothing
Atlassian-org-specific is baked in.

## Install

```bash
# From this repo (canonical):
uv tool install "git+https://github.com/somiandras/claude-skills.git#subdirectory=tools/atlassian-api-cli"
# …or from a local checkout:
uv tool install /path/to/claude-skills/tools/atlassian-api-cli
```

## Configure

Non-secret IDs live in `$XDG_CONFIG_HOME/atlassian-cli/config.yaml`
(default `~/.config/atlassian-cli/config.yaml`). Credentials come from the
environment: `ATLASSIAN_EMAIL`, `JIRA_API_TOKEN`, `BITBUCKET_API_TOKEN`.

```bash
atlassian-api config init     # write a blank template
atlassian-api config show     # print the resolved config
atlassian-api config path     # print the config file location
```

The config holds one or more **orgs** (Atlassian site + Bitbucket workspace),
each with its projects and repos. Commands auto-route to an org by JIRA ticket
prefix (`DA-123`) or Bitbucket repo slug; `--org` overrides, and `default_org`
covers commands with no prefix/slug.

## Usage

Run `jira-api --help` / `bitbucket-api --help`, or see the `atlassian-manager`
skill (`plugins/atlassian-manager/skills/atlassian-manager/SKILL.md`) for the
full command reference.
