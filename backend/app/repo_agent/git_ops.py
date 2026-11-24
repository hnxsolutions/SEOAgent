"""Safe git, validation, and optional GitHub PR helpers for the SEO code agent."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Dict, Iterable, List, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# The environment variable the credential helper below reads the token from.
#
# HTTPS push needs a credential, and every way of supplying one has a leak to
# avoid: a token in the remote URL or in `-c http.extraHeader=` shows up in the
# process list and in git's own error messages, and `credential.helper store`
# writes it to disk in plain text. Passing it in the child process environment
# and having git read it from there keeps it out of argv, out of .git/config and
# off the filesystem.
TOKEN_ENV_VAR = "SEO_AGENT_GIT_TOKEN"
USERNAME_ENV_VAR = "SEO_AGENT_GIT_USERNAME"

# A git credential helper is run through the shell when it starts with "!".
# This one answers only the "get" action and prints nothing for store/erase, so
# git never caches or writes the credential anywhere.
ENV_CREDENTIAL_HELPER = (
    f'!f() {{ test "$1" = get && printf "username=%s\\npassword=%s\\n" '
    f'"${USERNAME_ENV_VAR}" "${TOKEN_ENV_VAR}"; }}; f'
)

REDACTED = "***"

# Fallback authorship, used when a caller does not pass one. The real values
# come from settings, so a deployment can change them without touching code.
DEFAULT_COMMIT_NAME = "SEO Agent"
DEFAULT_COMMIT_EMAIL = "seo-agent@localhost"


def redact_secret(text: str, secret: Optional[str]) -> str:
    """Remove a secret from captured output.

    Belt and braces. The token is not passed on the command line, so git has no
    reason to echo it - but command output is stored on the apply run and shown
    in the dashboard, and a credential must never reach either by accident.
    """
    if not text or not secret or len(secret) < 8:
        return text
    return text.replace(secret, REDACTED)


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

    def __init__(self, timeout_seconds: int = 120, autocrlf: Optional[str] = None):
        self.timeout_seconds = timeout_seconds
        # End-of-line policy for every command this runner issues.
        #
        # git decides whether to convert line endings from core.autocrlf, which
        # it reads from the repository, the user's config and the system config.
        # A container sees none of the host's system config, so the same
        # checkout gets one answer from the owner's git and another from the
        # agent's: on a Windows checkout with LF blobs, the host cleans CRLF
        # back to LF on staging while the container stores the CRLF verbatim.
        # The agent's commit then rewrites every line of every file it touched.
        #
        # None keeps git's own resolution, so nothing changes unless a
        # deployment states the policy its checkouts actually use.
        self.autocrlf = autocrlf

    def _config_args(self, root: Path) -> List[str]:
        """Configuration applied to one command, never persisted anywhere.

        Trust this one repository for this one command: a checkout
        bind-mounted into a container is owned by a different uid than the
        process reading it, and git then refuses every command with "detected
        dubious ownership". The operator chose this path, so trusting it is
        their decision; it is scoped to exactly that directory rather than the
        "*" wildcard, and nothing is written to the repository's config or to
        any global config.
        """
        args = ["-c", f"safe.directory={Path(root).as_posix()}"]
        if self.autocrlf is not None:
            args += ["-c", f"core.autocrlf={self.autocrlf}"]
        return args

    def run(
        self,
        root: Path,
        args: List[str],
        timeout_seconds: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        secret: Optional[str] = None,
    ) -> CommandResult:
        child_env = None
        if env:
            child_env = {**os.environ, **env}
        config_args = self._config_args(root)
        try:
            completed = subprocess.run(
                ["git", *config_args, *args],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout_seconds or self.timeout_seconds,
                check=False,
                env=child_env,
            )
            return CommandResult(
                completed.returncode,
                redact_secret(completed.stdout or "", secret),
                redact_secret(completed.stderr or "", secret),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="ignore") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="ignore") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return CommandResult(
                -1,
                redact_secret(stdout, secret),
                redact_secret(f"{stderr}\nCommand timed out".strip(), secret),
            )
        except OSError as exc:
            return CommandResult(-1, "", redact_secret(str(exc), secret))

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

    def commit(
        self,
        root: Path,
        message: str,
        *,
        author_name: str = DEFAULT_COMMIT_NAME,
        author_email: str = DEFAULT_COMMIT_EMAIL,
        paths: Optional[Iterable[str]] = None,
    ) -> CommandResult:
        """Commit the staged changes under the agent's own authorship.

        When `paths` is given the commit is limited to those pathspecs, so
        anything the checkout's owner had already staged stays staged and
        uncommitted. Without it the whole index is committed, which is only
        appropriate where the caller controls the index.

        The identity is passed with -c on this one command. A container has no
        git identity of its own, and without this the commit fails with
        "Author identity unknown" - which is how the first real apply run
        ended, after the patches had already been applied and validated.

        Not `git config --global` and not a write to the repository's own
        config: the agent must not leave identity behind in a checkout it was
        only lent, and must not inherit or alter whatever identity the owner of
        that checkout uses for their own commits.
        """
        args = [
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "commit",
            "-m",
            message,
        ]
        pathspecs = list(dict.fromkeys(paths or []))
        if pathspecs:
            args += ["--", *pathspecs]
        return self.run(root, args)

    def commit_sha(self, root: Path) -> Optional[str]:
        result = self.run(root, ["rev-parse", "HEAD"])
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def remote_url(self, root: Path, remote: str = "origin") -> Optional[str]:
        result = self.run(root, ["remote", "get-url", remote])
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def push_branch(
        self,
        root: Path,
        branch_name: str,
        *,
        token: Optional[str] = None,
        username: str = "x-access-token",
        remote: str = "origin",
    ) -> CommandResult:
        """Push a branch, authenticating an HTTPS remote with a token.

        The token travels in the child process environment and is read back by
        the credential helper configured for this one command, so it never
        appears in argv, in .git/config, or in any file. An SSH remote is pushed
        untouched - it authenticates with the host's keys and a token would do
        nothing.

        GIT_TERMINAL_PROMPT=0 makes a missing or rejected credential fail
        immediately instead of blocking on a prompt that nothing can answer.
        """
        args: List[str] = []
        env: Dict[str, str] = {"GIT_TERMINAL_PROMPT": "0"}
        url = self.remote_url(root, remote)
        https_remote = bool(url and url.startswith(("http://", "https://")))

        if token and https_remote:
            env[TOKEN_ENV_VAR] = token
            env[USERNAME_ENV_VAR] = username
            args += [
                # Drop any helper the environment already configured, so only
                # this one answers and no system keychain is consulted.
                "-c",
                "credential.helper=",
                "-c",
                f"credential.helper={ENV_CREDENTIAL_HELPER}",
            ]
        elif token and url and not https_remote:
            logger.info(
                "Pushing to a non-HTTPS remote; token authentication does not apply",
                remote=remote,
                scheme=url.split(":", 1)[0],
            )
        elif not token:
            logger.info("Pushing without token authentication; no GitHub token is configured")

        args += ["push", "-u", remote, branch_name]
        return self.run(root, args, env=env, secret=token)


class ValidationRunner:
    """Runs optional project validation commands in the repository root."""

    # A missing interpreter is not a failing build. Reported as the same plain
    # "validation failed" it reads as "the patch broke the project", which is
    # the one conclusion that would tempt someone to force the pull request
    # through. This marker keeps the two apart in the stored output.
    MISSING_TOOL_PREFIX = "VALIDATION TOOLING MISSING"

    def __init__(self, timeout_seconds: int = 900):
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
                outputs.append(
                    f"$ {command}\nCommand timed out after {self.timeout_seconds}s"
                )
                return ValidationResult(False, "\n\n".join(outputs))
            except OSError as exc:
                outputs.append(
                    f"$ {command}\n{self.MISSING_TOOL_PREFIX}: {parts[0]} could not be run "
                    f"where the agent is running ({exc}). This is not a failing build - the "
                    "validation toolchain is absent."
                )
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
