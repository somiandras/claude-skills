"""Bitbucket API wrapper using requests library.

This module provides direct Bitbucket REST API access for pull request
and repository operations.

Environment variables required:
    ATLASSIAN_EMAIL: Your Atlassian account email
    BITBUCKET_API_TOKEN: App password from https://bitbucket.org/account/settings/app-passwords/

Usage:
    from atlassian_api_cli import BitbucketAPI

    bb = BitbucketAPI()
    prs = bb.list_pull_requests("data-importer")
    bb.create_pull_request("data-importer", "feature/foo", "main", "Add feature")
"""

import os
from typing import Any

import requests
from pydantic import BaseModel

API_BASE_URL = "https://api.bitbucket.org/2.0"


class Branch(BaseModel):
    """Represents a Bitbucket branch."""

    name: str
    target_hash: str
    target_date: str | None = None


class PullRequest(BaseModel):
    """Represents a Bitbucket pull request."""

    id: int
    title: str
    state: str
    source_branch: str
    destination_branch: str
    author: str
    created_on: str
    updated_on: str
    description: str | None = None
    link: str | None = None
    raw: dict[str, Any] | None = None


class BitbucketAPI:
    """Wrapper for Bitbucket REST API operations."""

    def __init__(
        self,
        workspace: str,
        email: str | None = None,
        api_token: str | None = None,
    ) -> None:
        """Initialize Bitbucket API client.

        Args:
            workspace: Bitbucket workspace slug (from config).
            email: Atlassian account email. Defaults to ATLASSIAN_EMAIL env var.
            api_token: Bitbucket app password. Defaults to BITBUCKET_API_TOKEN env var.
        """
        self.email = email or os.environ["ATLASSIAN_EMAIL"]
        self.api_token = api_token or os.environ["BITBUCKET_API_TOKEN"]
        self.workspace = workspace
        self.auth = (self.email, self.api_token)

    def _url(self, path: str) -> str:
        """Build full API URL."""
        return f"{API_BASE_URL}{path}"

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated API request.

        Args:
            method: HTTP method.
            path: API path.
            params: Query parameters.
            json_data: JSON request body.

        Returns:
            Response JSON.

        Raises:
            requests.HTTPError: On non-2xx response.
        """
        response = requests.request(
            method=method,
            url=self._url(path),
            auth=self.auth,
            params=params,
            json=json_data,
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # Surface Bitbucket's own error body — raise_for_status alone drops it,
            # leaving only a bare status line.
            body = response.text.strip()
            if body:
                raise requests.HTTPError(
                    f"{exc}\nBitbucket response: {body}", response=response
                ) from exc
            raise
        if response.status_code == 204:
            return {}
        return response.json()

    def list_pull_requests(
        self,
        repo_slug: str,
        state: str = "OPEN",
        limit: int = 25,
    ) -> list[PullRequest]:
        """List pull requests for a repository.

        Args:
            repo_slug: Repository slug (e.g., "data-importer").
            state: PR state filter (OPEN, MERGED, DECLINED, SUPERSEDED).
            limit: Maximum number of results.

        Returns:
            List of PullRequest objects.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/pullrequests"
        result = self._request("GET", path, params={"state": state, "pagelen": limit})

        prs = []
        for item in result.get("values", []):
            prs.append(self._parse_pr(item))
        return prs

    def get_pull_request(self, repo_slug: str, pr_id: int) -> PullRequest:
        """Get a specific pull request.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.

        Returns:
            PullRequest object.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}"
        result = self._request("GET", path)
        return self._parse_pr(result)

    def get_pull_request_diff(self, repo_slug: str, pr_id: int) -> str:
        """Get the diff for a pull request.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.

        Returns:
            Unified diff as a string.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}/diff"
        response = requests.get(
            url=self._url(path),
            auth=self.auth,
            timeout=30,
        )
        response.raise_for_status()
        return response.text

    def create_pull_request(
        self,
        repo_slug: str,
        source_branch: str,
        destination_branch: str,
        title: str,
        description: str | None = None,
        close_source_branch: bool = True,
        reviewers: list[str] | None = None,
    ) -> PullRequest:
        """Create a new pull request.

        Args:
            repo_slug: Repository slug.
            source_branch: Source branch name.
            destination_branch: Destination branch name (e.g., "main").
            title: PR title.
            description: PR description (Markdown).
            close_source_branch: Whether to close source branch on merge.
            reviewers: List of reviewer account UUIDs.

        Returns:
            Created PullRequest object.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/pullrequests"

        # Never delete develop when merging to main (develop → main PRs)
        if source_branch in ("develop",) and destination_branch in ("main", "master"):
            close_source_branch = False

        data: dict[str, Any] = {
            "title": title,
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": destination_branch}},
            "close_source_branch": close_source_branch,
        }

        if description:
            data["description"] = description

        if reviewers:
            data["reviewers"] = [{"uuid": uuid} for uuid in reviewers]

        result = self._request("POST", path, json_data=data)
        return self._parse_pr(result)

    def update_pull_request(
        self,
        repo_slug: str,
        pr_id: int,
        title: str | None = None,
        description: str | None = None,
    ) -> PullRequest:
        """Update a pull request.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.
            title: New title (optional).
            description: New description (optional).

        Returns:
            Updated PullRequest object.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}"

        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description

        # Bitbucket's PUT requires a title; a description-only update would
        # otherwise blank it. Resend the current title when the caller omits one.
        if "title" not in data:
            data["title"] = self.get_pull_request(repo_slug, pr_id).title

        result = self._request("PUT", path, json_data=data)
        return self._parse_pr(result)

    def merge_pull_request(
        self,
        repo_slug: str,
        pr_id: int,
        merge_strategy: str = "squash",
        close_source_branch: bool = True,
        message: str | None = None,
    ) -> PullRequest:
        """Merge a pull request.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.
            merge_strategy: Merge strategy (merge_commit, squash, fast_forward).
            close_source_branch: Whether to close source branch after merge.
            message: Optional merge commit message.

        Returns:
            Merged PullRequest object.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}/merge"

        # Bitbucket 2.0 expects the field name "merge_strategy" (not "type"
        # — that confusingly appears elsewhere in their schema).
        data: dict[str, Any] = {
            "merge_strategy": merge_strategy,
            "close_source_branch": close_source_branch,
        }

        if message:
            data["message"] = message

        result = self._request("POST", path, json_data=data)
        # Bitbucket merges large PRs asynchronously and returns an empty body
        # (or a non-PR payload) with 202 Accepted instead of the merged PR.
        # Fall back to re-fetching the PR so callers always get a usable object.
        if isinstance(result, dict) and "id" in result:
            return self._parse_pr(result)
        return self.get_pull_request(repo_slug, pr_id)

    def decline_pull_request(self, repo_slug: str, pr_id: int) -> PullRequest:
        """Decline a pull request.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.

        Returns:
            Declined PullRequest object.
        """
        path = (
            f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}/decline"
        )
        result = self._request("POST", path)
        return self._parse_pr(result)

    def add_pr_comment(
        self,
        repo_slug: str,
        pr_id: int,
        content: str,
    ) -> dict[str, Any]:
        """Add a comment to a pull request.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.
            content: Comment content (Markdown).

        Returns:
            Created comment data.
        """
        path = (
            f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}/comments"
        )
        return self._request("POST", path, json_data={"content": {"raw": content}})

    def add_inline_comment(
        self,
        repo_slug: str,
        pr_id: int,
        content: str,
        file_path: str,
        line: int | None = None,
        old_line: int | None = None,
    ) -> dict[str, Any]:
        """Add an inline comment on a specific file/line in a pull request diff.

        Bitbucket anchors inline comments in two coordinate systems: ``to`` is a
        line in the destination (post-change) file, ``from`` a line in the source
        (pre-change) file. Added lines exist only on the destination side, removed
        lines only on the source side; a comment spanning a changed line may carry
        both.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.
            content: Comment content (Markdown).
            file_path: Path to the file relative to repo root.
            line: Destination-side line number (``to``). Use for added or context
                lines.
            old_line: Source-side line number (``from``). Use for removed lines.

        Returns:
            Created comment data.

        Raises:
            ValueError: If neither ``line`` nor ``old_line`` is given.
        """
        if line is None and old_line is None:
            raise ValueError("Provide line, old_line, or both.")
        inline: dict[str, Any] = {"path": file_path}
        if line is not None:
            inline["to"] = line
        if old_line is not None:
            inline["from"] = old_line
        path = (
            f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}/comments"
        )
        data: dict[str, Any] = {
            "content": {"raw": content},
            "inline": inline,
        }
        return self._request("POST", path, json_data=data)

    def reply_to_comment(
        self,
        repo_slug: str,
        pr_id: int,
        parent_comment_id: int,
        content: str,
    ) -> dict[str, Any]:
        """Reply to an existing comment on a pull request.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.
            parent_comment_id: ID of the comment to reply to.
            content: Reply content (Markdown).

        Returns:
            Created reply comment data.
        """
        path = (
            f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}/comments"
        )
        data: dict[str, Any] = {
            "content": {"raw": content},
            "parent": {"id": parent_comment_id},
        }
        return self._request("POST", path, json_data=data)

    def get_pr_comments(
        self,
        repo_slug: str,
        pr_id: int,
    ) -> list[dict[str, Any]]:
        """Get comments on a pull request.

        Handles Bitbucket API pagination to return all comments.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.

        Returns:
            List of comment dictionaries.
        """
        path = (
            f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}/comments"
        )
        comments: list[dict[str, Any]] = []
        result = self._request("GET", path, params={"pagelen": 100})
        comments.extend(result.get("values", []))
        while "next" in result:
            result = requests.get(result["next"], auth=self.auth).json()
            comments.extend(result.get("values", []))
        return comments

    def resolve_pr_comment(
        self,
        repo_slug: str,
        pr_id: int,
        comment_id: int,
    ) -> dict[str, Any]:
        """Resolve a comment on a pull request.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.
            comment_id: Comment ID to resolve.

        Returns:
            Resolution data.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}/comments/{comment_id}/resolve"
        return self._request("POST", path)

    def unresolve_pr_comment(
        self,
        repo_slug: str,
        pr_id: int,
        comment_id: int,
    ) -> None:
        """Unresolve a comment on a pull request.

        Args:
            repo_slug: Repository slug.
            pr_id: Pull request ID.
            comment_id: Comment ID to unresolve.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/pullrequests/{pr_id}/comments/{comment_id}/resolve"
        self._request("DELETE", path)

    def get_repository(self, repo_slug: str) -> dict[str, Any]:
        """Get repository information.

        Args:
            repo_slug: Repository slug.

        Returns:
            Repository data.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}"
        return self._request("GET", path)

    def list_branches(
        self,
        repo_slug: str,
        limit: int = 25,
    ) -> list[Branch]:
        """List branches in a repository.

        Args:
            repo_slug: Repository slug.
            limit: Maximum number of results.

        Returns:
            List of Branch objects.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/refs/branches"
        result = self._request("GET", path, params={"pagelen": limit})
        branches = []
        for item in result.get("values", []):
            branches.append(self._parse_branch(item))
        return branches

    def get_branch(self, repo_slug: str, branch_name: str) -> Branch:
        """Get a specific branch.

        Args:
            repo_slug: Repository slug.
            branch_name: Branch name.

        Returns:
            Branch object.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/refs/branches/{branch_name}"
        result = self._request("GET", path)
        return self._parse_branch(result)

    def create_branch(
        self,
        repo_slug: str,
        branch_name: str,
        source_branch: str = "master",
    ) -> Branch:
        """Create a new branch.

        Args:
            repo_slug: Repository slug.
            branch_name: Name for the new branch.
            source_branch: Branch to create from (default: master).

        Returns:
            Created Branch object.
        """
        # Get the commit hash from the source branch
        source = self.get_branch(repo_slug, source_branch)

        path = f"/repositories/{self.workspace}/{repo_slug}/refs/branches"
        data = {
            "name": branch_name,
            "target": {"hash": source.target_hash},
        }
        result = self._request("POST", path, json_data=data)
        return self._parse_branch(result)

    def delete_branch(self, repo_slug: str, branch_name: str) -> None:
        """Delete a branch.

        Args:
            repo_slug: Repository slug.
            branch_name: Branch name to delete.
        """
        path = f"/repositories/{self.workspace}/{repo_slug}/refs/branches/{branch_name}"
        self._request("DELETE", path)

    def _parse_branch(self, data: dict[str, Any]) -> Branch:
        """Parse branch data into Branch object."""
        return Branch(
            name=data.get("name", ""),
            target_hash=data.get("target", {}).get("hash", ""),
            target_date=data.get("target", {}).get("date"),
        )

    def _parse_pr(self, data: dict[str, Any]) -> PullRequest:
        """Parse PR data into PullRequest object."""
        return PullRequest(
            id=data["id"],
            title=data["title"],
            state=data["state"],
            source_branch=data["source"]["branch"]["name"],
            destination_branch=data["destination"]["branch"]["name"],
            author=data["author"]["display_name"],
            created_on=data["created_on"],
            updated_on=data["updated_on"],
            description=data.get("description"),
            link=data.get("links", {}).get("html", {}).get("href"),
            raw=data,
        )
