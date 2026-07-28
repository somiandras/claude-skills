"""Config loading for the Atlassian CLI.

All non-secret identifiers (cloud IDs, project/board/issue-type/transition IDs,
Bitbucket workspace, repo slugs, dest branches) live in a single YAML file at
``$XDG_CONFIG_HOME/atlassian-cli/config.yaml`` (default
``~/.config/atlassian-cli/config.yaml``). Credentials are NOT stored here —
they come from the environment (ATLASSIAN_EMAIL, JIRA_API_TOKEN,
BITBUCKET_API_TOKEN).

The config supports multiple orgs (Atlassian sites + Bitbucket workspaces).
Commands auto-route to an org by JIRA ticket prefix or Bitbucket repo slug; an
explicit ``--org`` overrides, and ``default_org`` covers commands with no
prefix/slug to route by.
"""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError


class ConfigError(Exception):
    """Raised when the config file is missing, malformed, or ambiguous."""


class ProjectConfig(BaseModel):
    """A single JIRA project's identifiers."""

    project_id: str
    board_id: int | None = None
    issue_types: dict[str, str] = {}
    transitions: dict[str, str] = {}


class RepoConfig(BaseModel):
    """A single Bitbucket repo's routing info."""

    prefix: str
    dest_branch: str


class OrgConfig(BaseModel):
    """One Atlassian site + Bitbucket workspace, with its projects and repos."""

    cloud_id: str
    bitbucket_workspace: str
    account_id: str
    sprint_field: str
    projects: dict[str, ProjectConfig] = {}
    repos: dict[str, RepoConfig] = {}


class Config(BaseModel):
    """Top-level config: named orgs plus an optional default."""

    default_org: str | None = None
    orgs: dict[str, OrgConfig] = {}

    def resolve_by_prefix(self, prefix: str) -> tuple[str, OrgConfig]:
        """Find the org whose projects contain ``prefix`` (case-insensitive)."""
        prefix = prefix.upper()
        matches = [
            (name, org)
            for name, org in self.orgs.items()
            if prefix in {p.upper() for p in org.projects}
        ]
        if not matches:
            known = sorted(p for org in self.orgs.values() for p in org.projects)
            raise ConfigError(
                f"No configured project matches prefix '{prefix}'. "
                f"Known prefixes: {', '.join(known) or '(none)'}."
            )
        if len(matches) > 1:
            names = ", ".join(name for name, _ in matches)
            raise ConfigError(
                f"Prefix '{prefix}' is defined in multiple orgs ({names}). "
                f"Disambiguate with --org."
            )
        return matches[0]

    def resolve_by_repo(self, repo_slug: str) -> tuple[str, OrgConfig] | None:
        """Find the org whose repos contain ``repo_slug``.

        Returns None if no org lists the repo (callers fall back to
        context-free resolution). Raises on an ambiguous match.
        """
        matches = [
            (name, org) for name, org in self.orgs.items() if repo_slug in org.repos
        ]
        if not matches:
            return None
        if len(matches) > 1:
            names = ", ".join(name for name, _ in matches)
            raise ConfigError(
                f"Repo '{repo_slug}' is defined in multiple orgs ({names}). "
                f"Disambiguate with --org."
            )
        return matches[0]

    def resolve_by_name(self, name: str) -> tuple[str, OrgConfig]:
        """Look up an org by its explicit name (from --org)."""
        org = self.orgs.get(name)
        if org is None:
            known = ", ".join(sorted(self.orgs)) or "(none)"
            raise ConfigError(f"Unknown org '{name}'. Configured orgs: {known}.")
        return name, org

    def resolve_default(self) -> tuple[str, OrgConfig]:
        """Resolve an org with no prefix/slug context.

        Uses ``default_org`` if set, else the sole org if there is exactly one,
        else raises asking for --org.
        """
        if self.default_org is not None:
            return self.resolve_by_name(self.default_org)
        if len(self.orgs) == 1:
            return next(iter(self.orgs.items()))
        raise ConfigError(
            "No org context for this command. Set default_org in the config "
            "or pass --org."
        )


def config_path() -> Path:
    """Resolved path to the config file (honors XDG_CONFIG_HOME)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "atlassian-cli" / "config.yaml"


def load_config() -> Config:
    """Load and validate the config file.

    Raises ConfigError (with a clear message) if the file is missing,
    malformed, or fails validation.
    """
    path = config_path()
    if not path.exists():
        raise ConfigError(
            f"No config found at {path}. Run `atlassian-api config init` and "
            f"fill it in."
        )
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed YAML in {path}: {exc}") from exc
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config in {path}:\n{exc}") from exc


CONFIG_TEMPLATE = """\
# atlassian-cli config — non-secret IDs only.
# Credentials come from the environment, never this file:
#   ATLASSIAN_EMAIL, JIRA_API_TOKEN, BITBUCKET_API_TOKEN
#
# Commands auto-route to an org by JIRA ticket prefix or Bitbucket repo slug.
# default_org covers commands with no prefix/slug to route by; --org overrides.

# default_org: my-org

orgs: {}
  # my-org:
  #   cloud_id: ""                     # Atlassian site cloud ID
  #   bitbucket_workspace: ""          # Bitbucket workspace slug
  #   account_id: ""                   # your Atlassian account ID (default assignee)
  #   sprint_field: customfield_10020
  #   projects:
  #     ABC:
  #       project_id: ""               # numeric JIRA project ID
  #       board_id: null               # agile board ID, or null if unavailable
  #       issue_types: {task: "", epic: "", bug: ""}
  #       transitions: {todo: "", in_progress: "", in_review: "", done: ""}
  #   repos:
  #     my-repo: {prefix: ABC, dest_branch: main}
"""
