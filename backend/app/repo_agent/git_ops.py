"""Safe git, validation, and optional GitHub PR helpers for the SEO code agent."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import subprocess
from typing import Iterable, List, Optional

import httpx


@dataclass
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def output(self) -> str:
        return "\n".join(part for part in [self.stdout.strip(), self.stderr.strip()] if part)


@dataclass
class ValidationResult:
    passed: bool
    output: str


@dataclass
class PullRequestCreateResult:
    number: Optional[int]
    url: Optional[str]
    state: str


class GitCommandError(RuntimeError):
    """Raised when a required git command fails."""


class GitHubClientError(RuntimeError):
    """Raised when a GitHub API call cannot be completed."""


class GitCommandRunner:
    """Thin wrapper around git commands with timeout and captured output."""

    def __init__(self, timeout_seconds: int = 120):
        self.timeout_seconds = timeout_seconds

    def run(self, root: Path, args: List[str], timeout_seconds: Optional[int] = None) -> CommandResult:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout_seconds or self.timeout_seconds,
                check=False,
            )
            return CommandResult(completed.returncode, completed.stdout or "", completed.stderr or "")
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="ignore") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="ignore") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return CommandResult(-1, stdout, f"{stderr}\nCommand timed out".strip())
        except OSError as exc:
            return CommandResult(-1, "", str(exc))

    def require(self, root: Path, args: List[str], label: str) -> CommandResult:
        result = self.run(root, args)
        if result.returncode != 0:
            raise GitCommandError(f"{label} failed: {result.output}")
        return result

    def ensure_repo(self, root: Path) -> None:
        self.require(root, ["rev-parse", "--is-inside-work-tree"], "git repository check")

    def checkout_branch(self, root: Path, branch_name: str) -> None:
        self.require(root, ["checkout", "-B", branch_name], "git branch creation")

    def diff_summary(self, root: Path) -> str:
        result = self.run(root, ["diff", "--stat"])
        return result.output if result.returncode == 0 else result.output

    def add(self, root: Path, file_paths: Iterable[str]) -> None:
        paths = list(dict.fromkeys(file_paths))
        if paths:
            self.require(root, ["add", "--", *paths], "git add")

    def commit(self, root: Path, message: str) -> CommandResult:
        return self.run(root, ["commit", "-m", message])

    def commit_sha(self, root: Path) -> Optional[str]:
        result = self.run(root, ["rev-parse", "HEAD"])
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def push_branch(self, root: Path, branch_name: str) -> CommandResult:
        return self.run(root, ["push", "-u", "origin", branch_name])


class ValidationRunner:
    """Runs optional project validation commands in the repository root."""

    def __init__(self, timeout_seconds: int = 120):
        self.timeout_seconds = timeout_seconds

    def parse_commands(self, raw_commands: str) -> List[str]:
        if not raw_commands.strip():
            return []
        commands = [raw_commands]
        for separator in ["\n", ";", ","]:
            if any(separator in command for command in commands):
                commands = [
                    part.strip()
                    for command in commands
                    for part in command.split(separator)
                    if part.strip()
                ]
        return commands

    def run(self, root: Path, commands: List[str]) -> ValidationResult:
        outputs = []
        for command in commands:
            parts = shlex.split(command, posix=False)
            if not parts:
                continue
            try:
                completed = subprocess.run(
                    parts,
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                output = "\n".join(
                    part for part in [completed.stdout.strip(), completed.stderr.strip()] if part
                )
                outputs.append(f"$ {command}\n{output}".strip())
                if completed.returncode != 0:
                    return ValidationResult(False, "\n\n".join(outputs))
            except subprocess.TimeoutExpired:
                outputs.append(f"$ {command}\nCommand timed out")
                return ValidationResult(False, "\n\n".join(outputs))
            except OSError as exc:
                outputs.append(f"$ {command}\n{exc}")
                return ValidationResult(False, "\n\n".join(outputs))
        return ValidationResult(True, "\n\n".join(outputs))


class GitHubClient:
    """Minimal GitHub REST client for draft pull request creation."""

    API_BASE_URL = "https://api.github.com"

    def parse_repo(self, repo_url: str) -> tuple[str, str]:
        https_match = re.match(r"https://github\.com/([^/]+)/([^/.]+)(?:\.git)?/?$", repo_url or "")
        if https_match:
            return https_match.group(1), https_match.group(2)
        ssh_match = re.match(r"git@github\.com:([^/]+)/([^/.]+)(?:\.git)?$", repo_url or "")
        if ssh_match:
            return ssh_match.group(1), ssh_match.group(2)
        raise GitHubClientError("repo_url must be a GitHub repository URL")

    async def create_draft_pr(
        self,
        *,
        repo_url: str,
        token: str,
        branch_name: str,
        base_branch: str,
        title: str,
        body: str,
        draft: bool = True,
    ) -> PullRequestCreateResult:
        owner, repo = self.parse_repo(repo_url)
        payload = {
            "title": title,
            "head": branch_name,
            "base": base_branch,
            "body": body,
            "draft": draft,
        }
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{self.API_BASE_URL}/repos/{owner}/{repo}/pulls", json=payload, headers=headers)
        if response.status_code >= 400:
            raise GitHubClientError(f"GitHub PR creation failed with status {response.status_code}")
        data = response.json()
        return PullRequestCreateResult(
            number=data.get("number"),
            url=data.get("html_url"),
            state=data.get("state") or ("draft" if draft else "open"),
        )
