"""CLI interface for Atlassian API operations."""

import json
import re
import sys
from pathlib import Path
from typing import Annotated, Any

import click
import typer
import yaml
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from atlassian_api_cli.bitbucket_api import BitbucketAPI
from atlassian_api_cli.config import (
    CONFIG_TEMPLATE,
    Config,
    ConfigError,
    OrgConfig,
    ProjectConfig,
    config_path,
    load_config,
)
from atlassian_api_cli.jira_api import JiraAPI, JiraAttachment, get_project_key

app = typer.Typer(
    help="Atlassian API CLI for Jira and Bitbucket operations", no_args_is_help=True
)
jira_app = typer.Typer(help="Jira API operations", no_args_is_help=True)
bitbucket_app = typer.Typer(help="Bitbucket API operations", no_args_is_help=True)
config_app = typer.Typer(help="Manage the atlassian-cli config file", no_args_is_help=True)

app.add_typer(jira_app, name="jira")
app.add_typer(bitbucket_app, name="bitbucket")
app.add_typer(config_app, name="config")

console = Console()

_ORG_OPTION = Annotated[
    str | None,
    typer.Option("--org", help="Target org (overrides auto-routing by prefix/repo)"),
]


@jira_app.callback()
def _jira_main(ctx: typer.Context, org: _ORG_OPTION = None) -> None:
    """Jira operations. Use --org to override auto-routing."""
    ctx.obj = org


@bitbucket_app.callback()
def _bitbucket_main(ctx: typer.Context, org: _ORG_OPTION = None) -> None:
    """Bitbucket operations. Use --org to override auto-routing."""
    ctx.obj = org


# === Config / org resolution ===


def _org_override() -> str | None:
    """The --org value from the current invocation, if any."""
    ctx = click.get_current_context(silent=True)
    obj = ctx.obj if ctx is not None else None
    return obj if isinstance(obj, str) else None


def _load() -> Config:
    """Load config, converting ConfigError into a clean CLI exit."""
    try:
        return load_config()
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


def _resolve_prefix(prefix: str) -> OrgConfig:
    """Resolve the org for a JIRA ticket prefix (or --org override)."""
    cfg = _load()
    override = _org_override()
    try:
        _, org = cfg.resolve_by_name(override) if override else cfg.resolve_by_prefix(prefix)
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    return org


def _resolve_repo(repo: str) -> OrgConfig:
    """Resolve the org for a Bitbucket repo slug (or --org override).

    Falls back to default_org when the repo is not listed in any org, so
    ad-hoc repos in the default workspace still work.
    """
    cfg = _load()
    override = _org_override()
    try:
        if override:
            _, org = cfg.resolve_by_name(override)
        else:
            found = cfg.resolve_by_repo(repo)
            _, org = found if found is not None else cfg.resolve_default()
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    return org


def _resolve_context() -> OrgConfig:
    """Resolve the org for a command with no prefix/repo to route by."""
    cfg = _load()
    override = _org_override()
    try:
        _, org = cfg.resolve_by_name(override) if override else cfg.resolve_default()
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    return org


def _find_project(org: OrgConfig, prefix: str) -> ProjectConfig:
    """Look up a project in an org by prefix (case-insensitive)."""
    upper = prefix.upper()
    for key, proj in org.projects.items():
        if key.upper() == upper:
            return proj
    raise ConfigError(f"Project '{prefix}' is not configured.")


def _project(org: OrgConfig, prefix: str) -> ProjectConfig:
    """_find_project, converting a miss into a clean CLI exit."""
    try:
        return _find_project(org, prefix)
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


def _jira(org: OrgConfig) -> JiraAPI:
    return JiraAPI(cloud_id=org.cloud_id, sprint_field=org.sprint_field)


def _bb(org: OrgConfig) -> BitbucketAPI:
    return BitbucketAPI(workspace=org.bitbucket_workspace)


# === Jira Commands ===


@jira_app.command("get")
def jira_get_issue(
    issue_key: Annotated[str, typer.Argument(help="Issue key (e.g., DA-1234)")],
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
) -> None:
    """Get Jira issue details."""
    jira = _jira(_resolve_prefix(get_project_key(issue_key)))
    issue = jira.get_issue(issue_key)

    if raw:
        rprint(json.dumps(issue.raw, indent=2, default=str))
        return

    table = Table(title=f"Issue: {issue.key}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Summary", issue.summary)
    table.add_row("Status", issue.status)
    table.add_row("Type", issue.issue_type)
    table.add_row("Priority", issue.priority or "-")
    table.add_row("Assignee", issue.assignee or "-")
    table.add_row("Labels", ", ".join(issue.labels) if issue.labels else "-")
    table.add_row("Created", issue.created or "-")
    table.add_row("Updated", issue.updated or "-")
    table.add_row(
        "Attachments",
        str(len(issue.attachments)) if issue.attachments else "-",
    )

    console.print(table)

    if issue.attachments:
        _print_attachments_table(issue.attachments)

    if issue.description:
        console.print("\n[bold]Description:[/bold]")
        console.print(issue.description)


def _format_size(size_bytes: int) -> str:
    """Format byte size to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _print_attachments_table(attachments: list[JiraAttachment]) -> None:
    """Print a table of attachments."""
    att_table = Table(title="Attachments")
    att_table.add_column("ID", style="cyan")
    att_table.add_column("Filename", style="white")
    att_table.add_column("Size", style="blue", justify="right")
    att_table.add_column("Type", style="dim")
    att_table.add_column("Author", style="blue")

    for att in attachments:
        att_table.add_row(
            att.id,
            att.filename,
            _format_size(att.size),
            att.mime_type,
            att.author or "-",
        )

    console.print(att_table)


@jira_app.command("attachments")
def jira_list_attachments(
    issue_key: Annotated[str, typer.Argument(help="Issue key (e.g., DA-1234)")],
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
) -> None:
    """List attachments on a Jira issue."""
    jira = _jira(_resolve_prefix(get_project_key(issue_key)))
    issue = jira.get_issue(issue_key)

    if raw:
        rprint(
            json.dumps(
                [a.model_dump() for a in issue.attachments], indent=2, default=str
            )
        )
        return

    if not issue.attachments:
        console.print(f"No attachments on {issue_key}")
        return

    _print_attachments_table(issue.attachments)


@jira_app.command("download-attachment")
def jira_download_attachment(
    issue_key: Annotated[str, typer.Argument(help="Issue key (e.g., DA-1234)")],
    filename: Annotated[
        str | None,
        typer.Argument(help="Filename to download (omit to list available)"),
    ] = None,
    output_dir: Annotated[
        str, typer.Option("--output", "-o", help="Output directory")
    ] = ".",
    attachment_id: Annotated[
        str | None,
        typer.Option("--id", help="Download by attachment ID instead of filename"),
    ] = None,
) -> None:
    """Download an attachment from a Jira issue."""
    jira = _jira(_resolve_prefix(get_project_key(issue_key)))

    if attachment_id:
        # Direct download by ID
        path = jira.download_attachment(attachment_id, output_dir=output_dir)
        console.print(f"[green]✓[/green] Downloaded: {path}")
        return

    # Get issue to find attachment
    issue = jira.get_issue(issue_key)

    if not issue.attachments:
        console.print(f"[yellow]No attachments on {issue_key}[/yellow]")
        raise typer.Exit(1)

    if filename is None:
        # List available attachments
        console.print("[yellow]Specify a filename to download:[/yellow]")
        _print_attachments_table(issue.attachments)
        raise typer.Exit(1)

    # Find matching attachment
    matching = [a for a in issue.attachments if a.filename == filename]
    if not matching:
        console.print(f"[red]Attachment not found: {filename}[/red]")
        console.print("Available attachments:")
        _print_attachments_table(issue.attachments)
        raise typer.Exit(1)

    att = matching[0]
    path = jira.download_attachment(att.id, output_dir=output_dir, filename=filename)
    console.print(f"[green]✓[/green] Downloaded: {path}")


@jira_app.command("search")
def jira_search(
    jql: Annotated[str, typer.Argument(help="JQL query string")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results")] = 25,
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
) -> None:
    """Search Jira issues using JQL."""
    jira = _jira(_resolve_context())
    issues = jira.search_issues(jql, limit=limit)

    if raw:
        rprint(json.dumps([i.model_dump() for i in issues], indent=2, default=str))
        return

    table = Table(title=f"Search Results ({len(issues)} issues)")
    table.add_column("Key", style="cyan")
    table.add_column("Type", style="blue")
    table.add_column("Status", style="green")
    table.add_column("Summary", style="white")

    for issue in issues:
        table.add_row(issue.key, issue.issue_type, issue.status, issue.summary)

    console.print(table)


@jira_app.command("transition")
def jira_transition(
    issue_key: Annotated[str, typer.Argument(help="Issue key (e.g., DA-1234)")],
    status: Annotated[
        str,
        typer.Argument(help="Target status: todo, in_progress, in_review, done"),
    ],
) -> None:
    """Transition a Jira issue to a new status."""
    prefix = get_project_key(issue_key)
    org = _resolve_prefix(prefix)
    jira = _jira(org)
    project_transitions = _project(org, prefix).transitions

    status_lower = status.lower().replace(" ", "_").replace("-", "_")
    if status_lower in project_transitions:
        transition_id = project_transitions[status_lower]
    elif status.isdigit():
        transition_id = status
    else:
        # List available transitions
        transitions = jira.get_transitions(issue_key)
        console.print(f"[red]Unknown status: {status}[/red]")
        console.print("\nAvailable transitions:")
        for t in transitions:
            console.print(f"  - {t.name} (id: {t.id}) → {t.to_status}")
        raise typer.Exit(1)

    jira.transition_issue(issue_key, transition_id)
    console.print(f"[green]✓[/green] Transitioned {issue_key} to {status}")


@jira_app.command("transitions")
def jira_list_transitions(
    issue_key: Annotated[str, typer.Argument(help="Issue key (e.g., DA-1234)")],
) -> None:
    """List available transitions for an issue."""
    jira = _jira(_resolve_prefix(get_project_key(issue_key)))
    transitions = jira.get_transitions(issue_key)

    table = Table(title=f"Transitions for {issue_key}")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("To Status", style="green")

    for t in transitions:
        table.add_row(t.id, t.name, t.to_status)

    console.print(table)


@jira_app.command("comment")
def jira_add_comment(
    issue_key: Annotated[str, typer.Argument(help="Issue key (e.g., DA-1234)")],
    body: Annotated[str, typer.Argument(help="Comment body")],
) -> None:
    """Add a comment to a Jira issue."""
    jira = _jira(_resolve_prefix(get_project_key(issue_key)))
    jira.add_comment(issue_key, body)
    console.print(f"[green]✓[/green] Added comment to {issue_key}")


@jira_app.command("comments")
def jira_list_comments(
    issue_key: Annotated[str, typer.Argument(help="Issue key (e.g., DA-1234)")],
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
) -> None:
    """List comments on a Jira issue."""
    jira = _jira(_resolve_prefix(get_project_key(issue_key)))
    comments = jira.get_issue_comments(issue_key)

    if raw:
        rprint(json.dumps(comments, indent=2, default=str))
        return

    if not comments:
        console.print(f"No comments on {issue_key}")
        return

    # Show each comment with full body
    console.print(f"[bold]Comments on {issue_key}[/bold] ({len(comments)} total)\n")

    for c in comments:
        author = c.get("author", {}).get("displayName", "Unknown")
        created = c.get("created", "")[:16] if c.get("created") else ""
        body = c.get("body", "")

        console.print(
            f"[cyan]#{c.get('id', '-')}[/cyan] [blue]{author}[/blue] [dim]{created}[/dim]"
        )
        if body:
            console.print(body)
        console.print()  # blank line between comments


@jira_app.command("link")
def jira_create_link(
    outward_issue: Annotated[str, typer.Argument(help="Outward issue key (e.g., DA-1234 'blocks' DA-5678)")],
    link_type: Annotated[str, typer.Argument(help="Link type name (e.g., Blocks, Relates, Duplicate)")],
    inward_issue: Annotated[str, typer.Argument(help="Inward issue key")],
    comment: Annotated[str | None, typer.Option("--comment", "-c", help="Optional comment on outward issue")] = None,
) -> None:
    """Link two Jira issues. Reads as: <outward> <link_type> <inward>."""
    jira = _jira(_resolve_prefix(get_project_key(outward_issue)))
    jira.create_issue_link(
        inward_issue=inward_issue,
        outward_issue=outward_issue,
        link_type=link_type,
        comment=comment,
    )
    console.print(f"[green]✓[/green] Linked {outward_issue} → '{link_type}' → {inward_issue}")


@jira_app.command("unlink")
def jira_remove_link(
    link_id: Annotated[str, typer.Argument(help="Issue link ID (from `jira-api get <key>` issuelinks field)")],
) -> None:
    """Remove an issue link by its ID."""
    jira = _jira(_resolve_context())
    jira.remove_issue_link(link_id)
    console.print(f"[green]✓[/green] Removed link {link_id}")


@jira_app.command("link-types")
def jira_list_link_types(
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
) -> None:
    """List available Jira issue link types."""
    jira = _jira(_resolve_context())
    types = jira.get_issue_link_types()
    if raw:
        rprint(json.dumps(types, indent=2))
        return
    if not types:
        console.print("No link types found")
        return
    for t in types:
        console.print(
            f"[cyan]{t['name']}[/cyan] — outward: [green]{t['outward']}[/green], inward: [yellow]{t['inward']}[/yellow]"
        )


@jira_app.command("versions")
def jira_list_versions(
    project: Annotated[str, typer.Argument(help="Project key (e.g., DA)")],
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
) -> None:
    """List versions/releases for a project."""
    jira = _jira(_resolve_prefix(project))
    versions = jira.get_versions(project)

    if raw:
        rprint(json.dumps([v.model_dump() for v in versions], indent=2, default=str))
        return

    table = Table(title=f"Versions: {project}")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Released", style="green")
    table.add_column("Release Date", style="blue")

    for v in versions:
        table.add_row(
            v.id,
            v.name,
            "✓" if v.released else "-",
            v.release_date or "-",
        )

    console.print(table)


@jira_app.command("create-version")
def jira_create_version(
    name: Annotated[str, typer.Argument(help="Version name (e.g., 2026-02-10)")],
    project: Annotated[str, typer.Option("--project", "-p", help="Project key")],
    release_date: Annotated[
        str | None, typer.Option("--date", "-d", help="Release date (YYYY-MM-DD)")
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", help="Version description")
    ] = None,
) -> None:
    """Create a new version/release."""
    org = _resolve_prefix(project)
    project_id = _project(org, project).project_id
    version = _jira(org).create_version(
        project_key=project,
        project_id=project_id,
        name=name,
        release_date=release_date,
        description=description,
    )
    console.print(
        f"[green]✓[/green] Created version: {version.name} (id: {version.id})"
    )


@jira_app.command("release-version")
def jira_release_version(
    version_id: Annotated[str, typer.Argument(help="Version ID")],
    release_date: Annotated[
        str | None, typer.Option("--date", "-d", help="Release date (YYYY-MM-DD)")
    ] = None,
) -> None:
    """Mark a version as released."""
    jira = _jira(_resolve_context())
    jira.release_version(version_id, release_date=release_date)
    console.print(f"[green]✓[/green] Released version {version_id}")


@jira_app.command("set-fix-version")
def jira_set_fix_version(
    issue_key: Annotated[str, typer.Argument(help="Issue key (e.g., DA-1234)")],
    version: Annotated[str, typer.Argument(help="Version name or ID")],
    add: Annotated[
        bool,
        typer.Option("--add", "-a", help="Add to existing versions (don't replace)"),
    ] = False,
) -> None:
    """Set fix version(s) for an issue."""
    jira = _jira(_resolve_prefix(get_project_key(issue_key)))

    # Resolve version name to ID if needed
    if not version.isdigit():
        # Look up by name against the issue's own project
        versions = jira.get_versions(get_project_key(issue_key))
        matching = [v for v in versions if v.name == version]
        if not matching:
            console.print(f"[red]Version not found: {version}[/red]")
            raise typer.Exit(1)
        version_id = matching[0].id
    else:
        version_id = version

    if add:
        jira.add_fix_version(issue_key, version_id)
    else:
        jira.set_fix_versions(issue_key, [version_id])

    console.print(f"[green]✓[/green] Set fix version {version} on {issue_key}")


@jira_app.command("active-sprint")
def jira_active_sprint(
    prefix: Annotated[
        str | None,
        typer.Argument(help="Project prefix (omit to use the org's sole project)"),
    ] = None,
) -> None:
    """Show the active sprint for a project."""
    if prefix:
        key = prefix.upper()
        org = _resolve_prefix(key)
    else:
        org = _resolve_context()
        if len(org.projects) != 1:
            console.print(
                "[red]Specify a project prefix — the org has multiple projects.[/red]"
            )
            raise typer.Exit(1)
        key = next(iter(org.projects))

    proj = _project(org, key)
    sprint = _jira(org).get_active_sprint(key, proj.board_id)

    if sprint is None:
        console.print("[yellow]No active sprint found[/yellow]")
        raise typer.Exit(1)

    table = Table(title="Active Sprint")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("ID", str(sprint.id))
    table.add_row("Name", sprint.name)
    table.add_row("State", sprint.state)
    table.add_row("Board ID", str(sprint.board_id))
    table.add_row("Start", sprint.start_date[:10] if sprint.start_date else "-")
    table.add_row("End", sprint.end_date[:10] if sprint.end_date else "-")
    table.add_row("Goal", sprint.goal or "-")

    console.print(table)


@jira_app.command("set-sprint")
def jira_set_sprint(
    issue_key: Annotated[str, typer.Argument(help="Issue key (e.g., DA-1234)")],
    sprint_id: Annotated[
        int | None,
        typer.Argument(help="Sprint ID (omit for active sprint)"),
    ] = None,
) -> None:
    """Add an issue to a sprint. Defaults to the active sprint if no ID given."""
    prefix = get_project_key(issue_key)
    org = _resolve_prefix(prefix)
    jira = _jira(org)

    if sprint_id is None:
        proj = _project(org, prefix)
        sprint = jira.get_active_sprint(prefix, proj.board_id)
        if sprint is None:
            console.print("[red]No active sprint found[/red]")
            raise typer.Exit(1)
        sprint_id = sprint.id
        sprint_name = sprint.name
    else:
        sprint_name = str(sprint_id)

    jira.set_sprint(issue_key, sprint_id)
    console.print(
        f"[green]✓[/green] Added {issue_key} to sprint {sprint_name} (id: {sprint_id})"
    )


@jira_app.command("create-issue")
def jira_create_issue(
    summary: Annotated[str, typer.Argument(help="Issue summary/title")],
    project: Annotated[str, typer.Option("--project", "-p", help="Project key")],
    issue_type: Annotated[
        str, typer.Option("--type", "-t", help="Issue type: Task, Bug, Epic")
    ] = "Task",
    description: Annotated[
        str | None, typer.Option("--description", "-d", help="Issue description")
    ] = None,
    assignee: Annotated[
        str | None, typer.Option("--assignee", "-a", help="Assignee account ID")
    ] = None,
    labels: Annotated[
        str | None,
        typer.Option("--labels", "-l", help="Labels (comma-separated)"),
    ] = None,
    parent: Annotated[
        str | None, typer.Option("--parent", help="Parent issue key for subtasks")
    ] = None,
) -> None:
    """Create a new Jira issue."""
    jira = _jira(_resolve_prefix(project))
    label_list = (
        [lbl.strip() for lbl in labels.split(",") if lbl.strip()] if labels else None
    )
    issue_key = jira.create_issue(
        project_key=project,
        issue_type=issue_type,
        summary=summary,
        description=description,
        assignee_account_id=assignee,
        labels=label_list,
        parent_key=parent,
    )
    console.print(f"[green]✓[/green] Created {issue_key}: {summary}")


@jira_app.command("update")
def jira_update_issue(
    issue_key: Annotated[str, typer.Argument(help="Issue key (e.g., DA-1234)")],
    summary: Annotated[
        str | None, typer.Option("--summary", "-s", help="New summary/title")
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", "-d", help="New description")
    ] = None,
    labels: Annotated[
        str | None,
        typer.Option(
            "--labels", "-l", help="Labels (comma-separated, replaces existing)"
        ),
    ] = None,
    assignee: Annotated[
        str | None, typer.Option("--assignee", "-a", help="Assignee account ID")
    ] = None,
    priority: Annotated[
        str | None,
        typer.Option("--priority", "-p", help="Priority name (e.g., High, Medium)"),
    ] = None,
) -> None:
    """Update an existing issue's fields."""
    fields: dict[str, Any] = {}

    if summary is not None:
        fields["summary"] = summary
    if description is not None:
        fields["description"] = description
    if labels is not None:
        fields["labels"] = [lbl.strip() for lbl in labels.split(",") if lbl.strip()]
    if assignee is not None:
        fields["assignee"] = {"accountId": assignee}
    if priority is not None:
        fields["priority"] = {"name": priority}

    if not fields:
        console.print(
            "[yellow]No fields to update. Use --summary, --description, --labels, --assignee, or --priority.[/yellow]"
        )
        raise typer.Exit(1)

    jira = _jira(_resolve_prefix(get_project_key(issue_key)))
    jira.update_issue(issue_key, fields)

    updated = ", ".join(fields.keys())
    console.print(f"[green]✓[/green] Updated {issue_key}: {updated}")


# === Bitbucket Commands ===


@bitbucket_app.command("prs")
def bitbucket_list_prs(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    state: Annotated[str, typer.Option("--state", "-s", help="PR state")] = "OPEN",
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results")] = 25,
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
) -> None:
    """List pull requests for a repository."""
    bb = _bb(_resolve_repo(repo))
    prs = bb.list_pull_requests(repo, state=state, limit=limit)

    if raw:
        rprint(json.dumps([p.model_dump() for p in prs], indent=2, default=str))
        return

    table = Table(title=f"Pull Requests: {repo} ({state})")
    table.add_column("ID", style="cyan")
    table.add_column("State", style="green")
    table.add_column("Author", style="blue")
    table.add_column("Title", style="white")
    table.add_column("Branch", style="magenta")

    for pr in prs:
        table.add_row(
            str(pr.id),
            pr.state,
            pr.author,
            pr.title,
            pr.source_branch,
        )

    console.print(table)


@bitbucket_app.command("pr")
def bitbucket_get_pr(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    pr_id: Annotated[int, typer.Argument(help="Pull request ID")],
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
) -> None:
    """Get pull request details."""
    bb = _bb(_resolve_repo(repo))
    pr = bb.get_pull_request(repo, pr_id)

    if raw:
        rprint(json.dumps(pr.raw, indent=2, default=str))
        return

    table = Table(title=f"PR #{pr.id}: {pr.title}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("State", pr.state)
    table.add_row("Author", pr.author)
    table.add_row("Source", pr.source_branch)
    table.add_row("Destination", pr.destination_branch)
    table.add_row("Created", pr.created_on)
    table.add_row("Updated", pr.updated_on)
    table.add_row("Link", pr.link or "-")

    console.print(table)

    if pr.description:
        console.print("\n[bold]Description:[/bold]")
        console.print(pr.description)


# Pattern to extract a JIRA ticket from a branch name or title. Built from the
# configured project prefixes so it tracks whatever projects exist in config.
def _ticket_pattern(cfg: Config) -> re.Pattern[str]:
    prefixes = sorted(
        {p.upper() for org in cfg.orgs.values() for p in org.projects},
        key=len,
        reverse=True,
    )
    if not prefixes:
        # Match nothing when no projects are configured.
        return re.compile(r"(?!x)x")
    alternation = "|".join(re.escape(p) for p in prefixes)
    return re.compile(rf"\b((?:{alternation})-\d+)\b", re.IGNORECASE)


@bitbucket_app.command("create-pr")
def bitbucket_create_pr(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    source: Annotated[str, typer.Argument(help="Source branch")],
    title: Annotated[str, typer.Argument(help="PR title")],
    dest: Annotated[
        str | None,
        typer.Option("--dest", "-d", help="Destination branch (default: repo's configured dest)"),
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", help="PR description")
    ] = None,
    no_close: Annotated[
        bool, typer.Option("--no-close", help="Don't close source branch on merge")
    ] = False,
    no_transition: Annotated[
        bool,
        typer.Option("--no-transition", help="Don't transition JIRA ticket to Review"),
    ] = False,
) -> None:
    """Create a new pull request.

    Automatically transitions linked JIRA ticket (extracted from branch name
    or title) to Review status unless --no-transition is specified.
    """
    org = _resolve_repo(repo)

    if dest is None:
        repo_cfg = org.repos.get(repo)
        if repo_cfg is None:
            console.print(
                f"[red]No dest branch configured for '{repo}'. Pass --dest.[/red]"
            )
            raise typer.Exit(1)
        dest = repo_cfg.dest_branch

    pr = _bb(org).create_pull_request(
        repo_slug=repo,
        source_branch=source,
        destination_branch=dest,
        title=title,
        description=description,
        close_source_branch=not no_close,
    )

    console.print(f"[green]✓[/green] Created PR #{pr.id}: {pr.title}")
    console.print(f"  Link: {pr.link}")

    # Auto-transition JIRA ticket to Review
    if not no_transition:
        cfg = _load()
        pattern = _ticket_pattern(cfg)
        match = pattern.search(source) or pattern.search(title)
        if match:
            ticket = match.group(1).upper()
            try:
                _, ticket_org = cfg.resolve_by_prefix(get_project_key(ticket))
                transitions = _find_project(ticket_org, get_project_key(ticket)).transitions
                _jira(ticket_org).transition_issue(ticket, transitions["in_review"])
                console.print(f"[green]✓[/green] Transitioned {ticket} to Review")
            except Exception as e:  # noqa: BLE001 — best-effort auto-transition
                console.print(f"[yellow]⚠[/yellow] Could not transition {ticket}: {e}")


@bitbucket_app.command("update-pr")
def bitbucket_update_pr(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    pr_id: Annotated[int, typer.Argument(help="Pull request ID")],
    title: Annotated[
        str | None, typer.Option("--title", "-t", help="New PR title")
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", help="New PR description (Markdown)")
    ] = None,
    description_file: Annotated[
        Path | None,
        typer.Option(
            "--description-file",
            "-d",
            help="Read new PR description from a file (avoids shell newline escaping)",
        ),
    ] = None,
) -> None:
    """Update a pull request's title and/or description.

    Prefer --description-file for multi-line descriptions: passing newlines
    inline via the shell tends to leave literal backslash-n in the rendered PR.
    """
    if description is not None and description_file is not None:
        console.print(
            "[red]Error:[/red] Provide either --description or --description-file, not both"
        )
        raise typer.Exit(1)

    new_description = (
        description_file.read_text() if description_file is not None else description
    )

    changed_fields = []
    if title is not None:
        changed_fields.append("title")
    if new_description is not None:
        changed_fields.append("description")

    if not changed_fields:
        console.print(
            "[yellow]Nothing to update. Use --title, --description, or --description-file.[/yellow]"
        )
        raise typer.Exit(1)

    bb = _bb(_resolve_repo(repo))
    pr = bb.update_pull_request(repo, pr_id, title=title, description=new_description)
    console.print(f"[green]✓[/green] Updated PR #{pr.id} ({', '.join(changed_fields)})")
    console.print(f"  Link: {pr.link}")


@bitbucket_app.command("diff")
def bitbucket_diff(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    pr_id: Annotated[int, typer.Argument(help="Pull request ID")],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write the diff to this file instead of stdout.",
        ),
    ] = None,
) -> None:
    """Get the diff for a pull request."""
    bb = _bb(_resolve_repo(repo))
    diff = bb.get_pull_request_diff(repo, pr_id)
    if output is not None:
        output.write_text(diff)
        console.print(f"Diff written to {output}")
        return
    # Write raw diff to stdout — Rich console wraps lines to terminal width,
    # which corrupts diffs when piped to a file.
    sys.stdout.write(diff)


@bitbucket_app.command("merge")
def bitbucket_merge_pr(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    pr_id: Annotated[int, typer.Argument(help="Pull request ID")],
    strategy: Annotated[
        str, typer.Option("--strategy", "-s", help="Merge strategy")
    ] = "squash",
    message: Annotated[
        str | None, typer.Option("--message", "-m", help="Merge commit message")
    ] = None,
) -> None:
    """Merge a pull request."""
    bb = _bb(_resolve_repo(repo))
    pr = bb.merge_pull_request(repo, pr_id, merge_strategy=strategy, message=message)
    console.print(f"[green]✓[/green] Merged PR #{pr.id}: {pr.title}")


@bitbucket_app.command("comment")
def bitbucket_add_comment(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    pr_id: Annotated[int, typer.Argument(help="Pull request ID")],
    content: Annotated[str | None, typer.Argument(help="Comment content")] = None,
    content_file: Annotated[
        Path | None,
        typer.Option("--content-file", "-c", help="Read comment content from file"),
    ] = None,
) -> None:
    """Add a comment to a pull request."""
    if content_file:
        body = content_file.read_text()
    elif content:
        body = content
    else:
        console.print("[red]Error:[/red] Provide content as argument or via --content-file")
        raise typer.Exit(1)
    bb = _bb(_resolve_repo(repo))
    result = bb.add_pr_comment(repo, pr_id, body)
    comment_id = result.get("id", "?")
    console.print(f"[green]✓[/green] Added comment #{comment_id} to PR #{pr_id}")


@bitbucket_app.command("inline-comment")
def bitbucket_inline_comment(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    pr_id: Annotated[int, typer.Argument(help="Pull request ID")],
    content: Annotated[str | None, typer.Argument(help="Comment content")] = None,
    file: Annotated[str, typer.Option("--file", "-f", help="File path in the diff")] = "",
    line: Annotated[int, typer.Option("--line", "-l", help="Line number in the diff")] = 0,
    content_file: Annotated[
        Path | None,
        typer.Option("--content-file", "-c", help="Read comment content from file"),
    ] = None,
) -> None:
    """Add an inline comment on a specific file/line in a PR diff."""
    if content_file:
        body = content_file.read_text()
    elif content:
        body = content
    else:
        console.print("[red]Error:[/red] Provide content as argument or via --content-file")
        raise typer.Exit(1)
    bb = _bb(_resolve_repo(repo))
    result = bb.add_inline_comment(repo, pr_id, body, file_path=file, line=line)
    comment_id = result.get("id", "?")
    console.print(
        f"[green]✓[/green] Added inline comment #{comment_id} on {file}:{line} in PR #{pr_id}"
    )


@bitbucket_app.command("reply-comment")
def bitbucket_reply_comment(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    pr_id: Annotated[int, typer.Argument(help="Pull request ID")],
    comment_id: Annotated[int, typer.Argument(help="Parent comment ID to reply to")],
    content: Annotated[str, typer.Argument(help="Reply content")],
) -> None:
    """Reply to an existing comment on a pull request."""
    bb = _bb(_resolve_repo(repo))
    result = bb.reply_to_comment(repo, pr_id, comment_id, content)
    reply_id = result.get("id", "?")
    console.print(
        f"[green]✓[/green] Added reply #{reply_id} to comment #{comment_id} on PR #{pr_id}"
    )


@bitbucket_app.command("comments")
def bitbucket_list_comments(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    pr_id: Annotated[int, typer.Argument(help="Pull request ID")],
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
    active: Annotated[bool, typer.Option("--active", "-a", help="Only show unresolved comments")] = False,
) -> None:
    """List comments on a pull request."""
    bb = _bb(_resolve_repo(repo))
    comments = bb.get_pr_comments(repo, pr_id)

    if active:
        comments = [c for c in comments if c.get("resolution") is None]

    if raw:
        rprint(json.dumps(comments, indent=2, default=str))
        return

    if not comments:
        msg = "No unresolved comments" if active else "No comments"
        console.print(f"{msg} on PR #{pr_id}")
        return

    total = len(comments)
    label = f"{total} unresolved" if active else f"{total} total"
    console.print(f"[bold]Comments on PR #{pr_id}[/bold] ({label})\n")

    for c in comments:
        author = c.get("user", {}).get("display_name", "Unknown")
        created = c.get("created_on", "")[:16] if c.get("created_on") else ""
        content = c.get("content", {}).get("raw", "")
        inline = c.get("inline")
        parent = c.get("parent")
        resolved = c.get("resolution") is not None

        # Build header line
        indent = "  ↳ " if parent else ""
        status = " [green]✓ resolved[/green]" if resolved else ""
        console.print(
            f"{indent}[cyan]#{c.get('id', '-')}[/cyan] [blue]{author}[/blue] [dim]{created}[/dim]{status}"
        )

        # Show inline location if present
        if inline:
            file_path = inline.get("path", "?")
            line_from = inline.get("from")
            line_to = inline.get("to")
            loc = f"{file_path}:{line_from}" if line_from else file_path
            if line_to and line_to != line_from:
                loc = f"{file_path}:{line_from}-{line_to}"
            console.print(f"{indent}[yellow]📍 {loc}[/yellow]")

        if content:
            if parent:
                # Indent reply content
                for line in content.splitlines():
                    console.print(f"  {line}")
            else:
                console.print(content)
        console.print()  # blank line between comments


@bitbucket_app.command("resolve-comment")
def bitbucket_resolve_comment(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    pr_id: Annotated[int, typer.Argument(help="Pull request ID")],
    comment_id: Annotated[int, typer.Argument(help="Comment ID to resolve")],
) -> None:
    """Resolve a comment on a pull request."""
    bb = _bb(_resolve_repo(repo))
    bb.resolve_pr_comment(repo, pr_id, comment_id)
    console.print(f"[green]✓[/green] Resolved comment {comment_id} on PR #{pr_id}")


@bitbucket_app.command("unresolve-comment")
def bitbucket_unresolve_comment(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    pr_id: Annotated[int, typer.Argument(help="Pull request ID")],
    comment_id: Annotated[int, typer.Argument(help="Comment ID to unresolve")],
) -> None:
    """Unresolve a comment on a pull request."""
    bb = _bb(_resolve_repo(repo))
    bb.unresolve_pr_comment(repo, pr_id, comment_id)
    console.print(f"[green]✓[/green] Unresolved comment {comment_id} on PR #{pr_id}")


@bitbucket_app.command("branches")
def bitbucket_list_branches(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results")] = 25,
    raw: Annotated[bool, typer.Option("--raw", "-r", help="Output raw JSON")] = False,
) -> None:
    """List branches in a repository."""
    bb = _bb(_resolve_repo(repo))
    branches = bb.list_branches(repo, limit=limit)

    if raw:
        rprint(json.dumps([b.model_dump() for b in branches], indent=2, default=str))
        return

    table = Table(title=f"Branches: {repo}")
    table.add_column("Name", style="cyan")
    table.add_column("Commit", style="white", max_width=12)
    table.add_column("Date", style="blue")

    for b in branches:
        table.add_row(
            b.name,
            b.target_hash[:12] if b.target_hash else "-",
            b.target_date[:10] if b.target_date else "-",
        )

    console.print(table)


@bitbucket_app.command("create-branch")
def bitbucket_create_branch(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    branch_name: Annotated[str, typer.Argument(help="New branch name")],
    source: Annotated[
        str, typer.Option("--source", "-s", help="Source branch")
    ] = "master",
) -> None:
    """Create a new branch."""
    bb = _bb(_resolve_repo(repo))
    branch = bb.create_branch(repo, branch_name, source_branch=source)
    console.print(f"[green]✓[/green] Created branch: {branch.name}")
    console.print(f"  From: {source} ({branch.target_hash[:12]})")


@bitbucket_app.command("delete-branch")
def bitbucket_delete_branch(
    repo: Annotated[str, typer.Argument(help="Repository slug")],
    branch_name: Annotated[str, typer.Argument(help="Branch name to delete")],
) -> None:
    """Delete a branch."""
    bb = _bb(_resolve_repo(repo))
    bb.delete_branch(repo, branch_name)
    console.print(f"[green]✓[/green] Deleted branch: {branch_name}")


# === Config Commands ===


@config_app.command("init")
def config_init(
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite an existing config file")
    ] = False,
) -> None:
    """Write a blank config template to the XDG config path."""
    path = config_path()
    if path.exists() and not force:
        console.print(
            f"[yellow]Config already exists at {path}. Use --force to overwrite.[/yellow]"
        )
        raise typer.Exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONFIG_TEMPLATE)
    console.print(f"[green]✓[/green] Wrote config template to {path}")


@config_app.command("show")
def config_show() -> None:
    """Print the resolved, validated config."""
    cfg = _load()
    console.print(yaml.safe_dump(cfg.model_dump(), sort_keys=False))


@config_app.command("path")
def config_show_path() -> None:
    """Print the resolved config file path."""
    console.print(str(config_path()))


if __name__ == "__main__":
    app()
