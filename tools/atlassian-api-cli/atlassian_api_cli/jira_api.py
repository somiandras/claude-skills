"""Jira API wrapper using atlassian-python-api library.

This module provides a reliable alternative to the Atlassian MCP server,
which frequently disconnects.

Environment variables required:
    ATLASSIAN_EMAIL: Your Atlassian account email
    JIRA_API_TOKEN: Scoped API token from https://id.atlassian.com/manage-profile/security/api-tokens

The token must include the read:jira-user scope for myself()/find_users()
(and thus `--assignee me` / name resolution). Without it those user-directory
endpoints return 401 while issue operations still work.

Usage:
    from atlassian_api_cli import JiraAPI

    jira = JiraAPI()
    issue = jira.get_issue("DA-1234")
    jira.transition_issue("DA-1234", "21")  # To In Progress
"""

import os
from pathlib import Path
from typing import Any

from atlassian import Jira
from pydantic import BaseModel

def get_project_key(issue_key: str) -> str:
    """Extract project key from issue key (e.g., 'DA-1234' → 'DA')."""
    return issue_key.split("-")[0].upper()


class JiraTransition(BaseModel):
    """Represents a Jira transition."""

    id: str
    name: str
    to_status: str


class JiraSprint(BaseModel):
    """Represents a Jira sprint."""

    id: int
    name: str
    state: str
    board_id: int
    start_date: str | None = None
    end_date: str | None = None
    goal: str | None = None


class JiraVersion(BaseModel):
    """Represents a Jira version/release."""

    id: str
    name: str
    project_id: str
    released: bool = False
    archived: bool = False
    release_date: str | None = None
    start_date: str | None = None
    description: str | None = None


class JiraAttachment(BaseModel):
    """Represents a Jira attachment."""

    id: str
    filename: str
    size: int
    mime_type: str
    content_url: str
    created: str | None = None
    author: str | None = None


class JiraUser(BaseModel):
    """Represents a Jira user."""

    account_id: str
    display_name: str
    email: str | None = None
    active: bool = True


class JiraIssue(BaseModel):
    """Represents a Jira issue."""

    key: str
    summary: str
    status: str
    issue_type: str
    priority: str | None = None
    description: str | None = None
    assignee: str | None = None
    reporter: str | None = None
    created: str | None = None
    updated: str | None = None
    labels: list[str] = []
    attachments: list[JiraAttachment] = []
    raw: dict[str, Any] | None = None


class JiraAPI:
    """Wrapper for Jira REST API operations."""

    def __init__(
        self,
        cloud_id: str,
        sprint_field: str,
        email: str | None = None,
        api_token: str | None = None,
    ) -> None:
        """Initialize Jira API client.

        Args:
            cloud_id: Atlassian site cloud ID (from config).
            sprint_field: Sprint custom-field ID (from config).
            email: Atlassian account email. Defaults to ATLASSIAN_EMAIL env var.
            api_token: Jira API token. Defaults to JIRA_API_TOKEN env var.
        """
        self.email = email or os.environ["ATLASSIAN_EMAIL"]
        self.api_token = api_token or os.environ["JIRA_API_TOKEN"]
        self.cloud_id = cloud_id
        self.sprint_field = sprint_field
        self.url = f"https://api.atlassian.com/ex/jira/{cloud_id}"

        self._client = Jira(
            url=self.url,
            username=self.email,
            password=self.api_token,
            cloud=True,
        )

    def get_issue(
        self,
        issue_key: str,
        fields: str | None = None,
    ) -> JiraIssue:
        """Fetch issue details.

        Args:
            issue_key: Issue key (e.g., "DA-1234")
            fields: Comma-separated field names to fetch. None for default fields.

        Returns:
            JiraIssue object with issue details.

        Raises:
            ValueError: If issue not found.
        """
        # Default fields if none specified
        if fields is None:
            fields = "summary,status,issuetype,priority,description,assignee,reporter,created,updated,labels,attachment"
        result = self._client.issue(issue_key, fields=fields)
        if result is None:
            raise ValueError(f"Issue {issue_key} not found")

        fields_data = result.get("fields", {})
        return JiraIssue(
            key=result["key"],
            summary=fields_data.get("summary", ""),
            status=fields_data.get("status", {}).get("name", ""),
            issue_type=fields_data.get("issuetype", {}).get("name", ""),
            priority=fields_data.get("priority", {}).get("name")
            if fields_data.get("priority")
            else None,
            description=fields_data.get("description"),
            assignee=fields_data.get("assignee", {}).get("displayName")
            if fields_data.get("assignee")
            else None,
            reporter=fields_data.get("reporter", {}).get("displayName")
            if fields_data.get("reporter")
            else None,
            created=fields_data.get("created"),
            updated=fields_data.get("updated"),
            labels=fields_data.get("labels", []),
            attachments=[
                JiraAttachment(
                    id=str(a["id"]),
                    filename=a["filename"],
                    size=a.get("size", 0),
                    mime_type=a.get("mimeType", ""),
                    content_url=a.get("content", ""),
                    created=a.get("created"),
                    author=a.get("author", {}).get("displayName"),
                )
                for a in fields_data.get("attachment", [])
            ],
            raw=result,
        )

    def myself(self) -> JiraUser:
        """Return the authenticated user (the API token's owner).

        Use this to resolve "assign to me" without an external lookup.

        Returns:
            JiraUser for the token owner.
        """
        result = self._client.myself()
        if result is None:
            raise ValueError("Could not fetch current user")
        return JiraUser(
            account_id=result["accountId"],
            display_name=result.get("displayName", ""),
            email=result.get("emailAddress"),
            active=result.get("active", True),
        )

    def find_users(self, query: str) -> list[JiraUser]:
        """Fuzzy-search users by display name or email address.

        Args:
            query: String matched against displayName and emailAddress.

        Returns:
            List of matching JiraUser objects (may be empty).
        """
        result = self._client.user_find_by_user_string(query=query)
        # On error the client returns an explanatory string instead of a list.
        if not isinstance(result, list):
            raise ValueError(str(result))
        return [
            JiraUser(
                account_id=u["accountId"],
                display_name=u.get("displayName", ""),
                email=u.get("emailAddress"),
                active=u.get("active", True),
            )
            for u in result
            if isinstance(u, dict)
        ]

    def search_issues(
        self,
        jql: str,
        fields: list[str] | None = None,
        limit: int = 50,
        start: int = 0,
    ) -> list[JiraIssue]:
        """Search issues using JQL.

        Args:
            jql: JQL query string.
            fields: List of field names to fetch. None for default fields.
            limit: Maximum number of results.
            start: Starting index for pagination.

        Returns:
            List of JiraIssue objects.
        """
        default_fields = [
            "summary",
            "status",
            "issuetype",
            "priority",
            "created",
            "labels",
        ]
        fields_str = ",".join(fields or default_fields)

        result = self._client.jql(jql, limit=limit, start=start, fields=fields_str)
        if result is None:
            return []

        issues = []
        for item in result.get("issues", []):
            fields_data = item.get("fields", {})
            issues.append(
                JiraIssue(
                    key=item["key"],
                    summary=fields_data.get("summary", ""),
                    status=fields_data.get("status", {}).get("name", ""),
                    issue_type=fields_data.get("issuetype", {}).get("name", ""),
                    priority=fields_data.get("priority", {}).get("name")
                    if fields_data.get("priority")
                    else None,
                    created=fields_data.get("created"),
                    labels=fields_data.get("labels", []),
                    raw=item,
                )
            )
        return issues

    def create_issue(
        self,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str | None = None,
        assignee_account_id: str | None = None,
        labels: list[str] | None = None,
        parent_key: str | None = None,
        additional_fields: dict[str, Any] | None = None,
    ) -> str:
        """Create a new issue.

        Args:
            project_key: Project key (e.g., "DA").
            issue_type: Issue type name (Task, Bug, Epic, etc.).
            summary: Issue summary/title.
            description: Issue description (Markdown).
            assignee_account_id: Account ID of assignee.
            labels: List of labels.
            parent_key: Parent issue key for subtasks.
            additional_fields: Additional custom fields.

        Returns:
            Created issue key.
        """
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "issuetype": {"name": issue_type},
            "summary": summary,
        }

        if description:
            fields["description"] = description

        if assignee_account_id:
            fields["assignee"] = {"accountId": assignee_account_id}

        if labels:
            fields["labels"] = labels

        if parent_key:
            fields["parent"] = {"key": parent_key}

        if additional_fields:
            fields.update(additional_fields)

        result = self._client.create_issue(fields=fields)
        if result is None:
            raise ValueError("Failed to create issue")
        return str(result["key"])

    def update_issue(
        self,
        issue_key: str,
        fields: dict[str, Any],
    ) -> None:
        """Update an existing issue.

        Args:
            issue_key: Issue key to update.
            fields: Dictionary of fields to update.
        """
        self._client.update_issue_field(issue_key, fields=fields)

    def set_fix_versions(
        self,
        issue_key: str,
        version_ids: list[str],
    ) -> None:
        """Set fix versions for an issue.

        Args:
            issue_key: Issue key to update.
            version_ids: List of version IDs to set as fix versions.
        """
        self.update_issue(
            issue_key,
            fields={"fixVersions": [{"id": vid} for vid in version_ids]},
        )

    def add_fix_version(
        self,
        issue_key: str,
        version_id: str,
    ) -> None:
        """Add a fix version to an issue (preserving existing versions).

        Args:
            issue_key: Issue key to update.
            version_id: Version ID to add.
        """
        # Get current fix versions
        issue = self._client.issue(issue_key, fields="fixVersions")
        if issue is None:
            raise ValueError(f"Issue {issue_key} not found")
        current_versions = issue.get("fields", {}).get("fixVersions", [])
        current_ids = [v.get("id") for v in current_versions]

        # Add new version if not already present
        if version_id not in current_ids:
            current_ids.append(version_id)
            self.set_fix_versions(issue_key, current_ids)

    def get_transitions(self, issue_key: str) -> list[JiraTransition]:
        """Get available transitions for an issue.

        Args:
            issue_key: Issue key.

        Returns:
            List of available transitions.
        """
        # Returns List[dict] directly, not a dict with "transitions" key
        # The "to" field is a string, not a dict
        result = self._client.get_issue_transitions(issue_key)
        transitions = []
        for t in result:
            to_status = t.get("to", "")
            # Handle both string and dict formats for "to" field
            if isinstance(to_status, dict):
                to_status = to_status.get("name", "")
            transitions.append(
                JiraTransition(
                    id=str(t.get("id", "")),
                    name=str(t.get("name", "")),
                    to_status=str(to_status),
                )
            )
        return transitions

    def transition_issue(
        self,
        issue_key: str,
        transition_id: str,
    ) -> None:
        """Transition an issue to a new status.

        Args:
            issue_key: Issue key to transition.
            transition_id: Transition ID (e.g., "21" for In Progress).
        """
        # Use direct API call - the library's issue_transition tries to match
        # by name which fails when passing an ID directly
        self._client.post(
            f"rest/api/3/issue/{issue_key}/transitions",
            data={"transition": {"id": transition_id}},
        )

    def add_comment(self, issue_key: str, body: str) -> None:
        """Add a comment to an issue.

        Args:
            issue_key: Issue key.
            body: Comment body (Markdown).
        """
        self._client.issue_add_comment(issue_key, body)

    def get_issue_comments(self, issue_key: str) -> list[dict[str, Any]]:
        """Get all comments on an issue.

        Args:
            issue_key: Issue key.

        Returns:
            List of comment dictionaries.
        """
        result = self._client.issue_get_comments(issue_key)
        if result is None:
            return []
        return result.get("comments", [])

    # === Issue Link Methods ===

    def get_issue_link_types(self) -> list[dict[str, str]]:
        """Get all available issue link types.

        Returns:
            List of dicts with keys: id, name, inward, outward.
        """
        result = self._client.get_issue_link_types()
        if result is None:
            return []
        # API may return either a list or a dict with "issueLinkTypes" key
        items = result if isinstance(result, list) else result.get("issueLinkTypes", [])
        return [
            {
                "id": str(t.get("id", "")),
                "name": t.get("name", ""),
                "inward": t.get("inward", ""),
                "outward": t.get("outward", ""),
            }
            for t in items
        ]

    def create_issue_link(
        self,
        inward_issue: str,
        outward_issue: str,
        link_type: str,
        comment: str | None = None,
    ) -> None:
        """Create a link between two issues.

        The link reads: outward_issue <link_type.outward> inward_issue.
        e.g. for type "Blocks": outward_issue "blocks" inward_issue, and
        inward_issue "is blocked by" outward_issue.

        Args:
            inward_issue: Key of the issue on the inward side of the link.
            outward_issue: Key of the issue on the outward side.
            link_type: Link type name (e.g., "Blocks", "Relates", "Duplicate").
            comment: Optional comment to add to the outward issue.
        """
        data: dict[str, Any] = {
            "type": {"name": link_type},
            "inwardIssue": {"key": inward_issue},
            "outwardIssue": {"key": outward_issue},
        }
        if comment:
            data["comment"] = {"body": comment}
        self._client.create_issue_link(data)

    def remove_issue_link(self, link_id: str) -> None:
        """Remove an issue link by its ID.

        Args:
            link_id: Link ID (find via get_issue with fields="issuelinks").
        """
        self._client.remove_issue_link(link_id)

    # === Version/Release Methods ===

    def get_versions(self, project_key: str) -> list[JiraVersion]:
        """Get all versions for a project.

        Args:
            project_key: Project key (e.g., "DA").

        Returns:
            List of JiraVersion objects.
        """
        result = self._client.get_project_versions(project_key)
        if result is None:
            return []
        versions = []
        for v in result:
            versions.append(
                JiraVersion(
                    id=str(v.get("id", "")),
                    name=v.get("name", ""),
                    project_id=str(v.get("projectId", "")),
                    released=v.get("released", False),
                    archived=v.get("archived", False),
                    release_date=v.get("releaseDate"),
                    start_date=v.get("startDate"),
                    description=v.get("description"),
                )
            )
        return versions

    def create_version(
        self,
        project_key: str,
        project_id: str,
        name: str,
        release_date: str | None = None,
        description: str | None = None,
        released: bool = False,
    ) -> JiraVersion:
        """Create a new version/release.

        Args:
            project_key: Project key (e.g., "DA").
            project_id: Numeric project ID for the same project (from config).
            name: Version name (e.g., "2026-02-10").
            release_date: Release date in YYYY-MM-DD format.
            description: Version description.
            released: Whether the version is already released.

        Returns:
            Created JiraVersion object.
        """
        result = self._client.add_version(
            project_key=project_key,
            project_id=project_id,
            version=name,
            is_released=released,
        )
        if result is None:
            raise ValueError("Failed to create version")

        version_id = str(result.get("id", ""))

        # Update with additional fields if provided
        if release_date or description:
            self._client.update_version(
                version=version_id,
                release_date=release_date,
                description=description,
            )
            # Re-fetch to get updated data
            return self.get_version(version_id)

        return JiraVersion(
            id=version_id,
            name=result.get("name", name),
            project_id=str(result.get("projectId", project_id)),
            released=result.get("released", released),
            archived=result.get("archived", False),
            release_date=release_date,
            description=description,
        )

    def get_version(self, version_id: str) -> JiraVersion:
        """Get a specific version by ID.

        Args:
            version_id: Version ID.

        Returns:
            JiraVersion object.
        """
        result = self._client.get_version(version_id)
        if result is None:
            raise ValueError(f"Version {version_id} not found")
        return JiraVersion(
            id=str(result.get("id", "")),
            name=result.get("name", ""),
            project_id=str(result.get("projectId", "")),
            released=result.get("released", False),
            archived=result.get("archived", False),
            release_date=result.get("releaseDate"),
            start_date=result.get("startDate"),
            description=result.get("description"),
        )

    def release_version(self, version_id: str, release_date: str | None = None) -> None:
        """Mark a version as released.

        Args:
            version_id: Version ID to release.
            release_date: Release date in YYYY-MM-DD format. Defaults to today.
        """
        self._client.update_version(
            version=version_id,
            is_released=True,
            release_date=release_date,
        )

    # === Sprint Methods ===

    def get_active_sprint(
        self, project_key: str, board_id: int | None = None
    ) -> JiraSprint | None:
        """Get the active sprint for a project.

        Uses JQL to find an issue in the active sprint and extracts sprint
        metadata from it. The agile board API requires separate OAuth scopes
        that our token doesn't have.

        Args:
            project_key: Project key to look up the active sprint for.
            board_id: Fallback board ID if the sprint payload omits it.

        Returns:
            JiraSprint for the active sprint, or None if no active sprint.
        """
        result = self._client.jql(
            f"project={project_key} AND sprint in openSprints()",
            limit=1,
            fields=self.sprint_field,
        )
        if result is None:
            return None
        issues = result.get("issues", [])
        if not issues:
            return None

        sprints = issues[0].get("fields", {}).get(self.sprint_field, [])
        active = [s for s in sprints if s.get("state") == "active"]
        if not active:
            return None

        s = active[0]
        return JiraSprint(
            id=s["id"],
            name=s["name"],
            state=s["state"],
            board_id=s.get("boardId") or board_id or 0,
            start_date=s.get("startDate"),
            end_date=s.get("endDate"),
            goal=s.get("goal") or None,
        )

    def download_attachment(
        self,
        attachment_id: str,
        output_dir: str = ".",
        filename: str | None = None,
    ) -> Path:
        """Download an attachment by ID.

        Args:
            attachment_id: Attachment ID.
            output_dir: Directory to save the file to.
            filename: Override filename. If None, uses the original filename.

        Returns:
            Path to the downloaded file.
        """
        if filename is None:
            # Fetch metadata to get original filename
            metadata = self._client.get_attachment(attachment_id)
            if metadata is None:
                raise ValueError(f"Attachment {attachment_id} not found")
            filename = metadata.get("filename", f"attachment_{attachment_id}")

        output_path = Path(output_dir) / str(filename)
        content = self._client.get_attachment_content(attachment_id)
        output_path.write_bytes(content)
        return output_path

    def set_sprint(self, issue_key: str, sprint_id: int) -> None:
        """Set the sprint for an issue.

        Args:
            issue_key: Issue key (e.g., "DA-1234").
            sprint_id: Sprint ID (integer).
        """
        self._client.update_issue_field(
            issue_key, fields={self.sprint_field: sprint_id}
        )
