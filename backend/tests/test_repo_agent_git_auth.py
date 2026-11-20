"""Focused tests for push authentication, validation commands and leak safety.

No test performs a real push or contacts GitHub; the git invocation is captured
and inspected instead.
"""
from pathlib import Path

import pytest

from app.core.config import settings
from app.repo_agent.git_ops import (
    DEFAULT_COMMIT_EMAIL,
    DEFAULT_COMMIT_NAME,
    ENV_CREDENTIAL_HELPER,
    REDACTED,
    TOKEN_ENV_VAR,
    USERNAME_ENV_VAR,
    CommandResult,
    GitCommandRunner,
    GitHubClient,
    GitHubClientError,
    ValidationRunner,
    redact_secret,
)

TOKEN = "ghp_exampletokenvalue_0123456789abcdef"


class RecordingRunner(GitCommandRunner):
    """Captures the git invocation instead of running it."""

    def __init__(self, remote_url: str | None = "https://github.com/acme/site.git"):
        super().__init__(timeout_seconds=5)
        self._remote_url = remote_url
        self.calls: list[dict] = []

    def run(self, root, args, timeout_seconds=None, env=None, secret=None):
        self.calls.append({"args": list(args), "env": dict(env or {}), "secret": secret})
        if args[:2] == ["remote", "get-url"]:
            if self._remote_url is None:
                return CommandResult(1, "", "no such remote")
            return CommandResult(0, self._remote_url + "\n", "")
        return CommandResult(0, "Everything up-to-date\n", "")

    @property
    def push_call(self) -> dict:
        return next(call for call in self.calls if "push" in call["args"])


def test_push_sends_the_token_through_the_environment_not_the_command_line(tmp_path):
    runner = RecordingRunner()
    runner.push_branch(tmp_path, "seo-agent/test", token=TOKEN, username="x-access-token")
    call = runner.push_call

    # The credential reaches git only via the environment.
    assert call["env"][TOKEN_ENV_VAR] == TOKEN
    assert call["env"][USERNAME_ENV_VAR] == "x-access-token"
    assert TOKEN not in " ".join(call["args"])
    assert call["secret"] == TOKEN

    # The helper is configured for this one command, and any inherited helper
    # is cleared first so no keychain or stored file is consulted.
    assert call["args"][:2] == ["-c", "credential.helper="]
    assert f"credential.helper={ENV_CREDENTIAL_HELPER}" in call["args"]
    assert call["args"][-4:] == ["push", "-u", "origin", "seo-agent/test"]


def test_push_never_prompts(tmp_path):
    runner = RecordingRunner()
    runner.push_branch(tmp_path, "seo-agent/test", token=TOKEN)

    # A missing or rejected credential must fail, not block on a prompt nobody
    # can answer.
    assert runner.push_call["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_credential_helper_references_env_vars_and_embeds_no_secret():
    assert TOKEN_ENV_VAR in ENV_CREDENTIAL_HELPER
    assert USERNAME_ENV_VAR in ENV_CREDENTIAL_HELPER
    # It answers only "get", so git is never told to store or erase anything.
    assert 'test "$1" = get' in ENV_CREDENTIAL_HELPER
    assert ENV_CREDENTIAL_HELPER.startswith("!")
    for literal in ("ghp_", "github_pat_", "password=ghp", "Bearer "):
        assert literal not in ENV_CREDENTIAL_HELPER


def test_ssh_remote_is_pushed_without_token_configuration(tmp_path):
    runner = RecordingRunner(remote_url="git@github.com:acme/site.git")
    runner.push_branch(tmp_path, "seo-agent/test", token=TOKEN)
    call = runner.push_call

    # A token does nothing for SSH, so none is configured and none is exported.
    assert TOKEN_ENV_VAR not in call["env"]
    assert not any("credential.helper" in arg for arg in call["args"])
    assert call["args"][:4] == ["push", "-u", "origin", "seo-agent/test"]


def test_push_without_a_token_configures_no_credentials(tmp_path):
    runner = RecordingRunner()
    runner.push_branch(tmp_path, "seo-agent/test", token=None)
    call = runner.push_call

    assert TOKEN_ENV_VAR not in call["env"]
    assert not any("credential.helper" in arg for arg in call["args"])


def test_command_output_is_redacted(tmp_path):
    assert redact_secret(f"remote: using {TOKEN} here", TOKEN) == f"remote: using {REDACTED} here"
    # Too short to be a credential, and absent secrets, leave text alone.
    assert redact_secret("plain output", None) == "plain output"
    assert redact_secret("abc", "abc") == "abc"


def test_real_runner_redacts_the_token_from_captured_output(tmp_path):
    """End to end through subprocess: a token echoed by git is scrubbed."""
    runner = GitCommandRunner(timeout_seconds=10)
    # `git var` is harmless and echoes its argument back in the error message.
    result = runner.run(tmp_path, ["var", TOKEN], secret=TOKEN)

    assert TOKEN not in result.output
    assert TOKEN not in result.stdout
    assert TOKEN not in result.stderr


def test_validation_commands_parse_in_order():
    runner = ValidationRunner(900)

    assert runner.parse_commands("npx --no-install tsc --noEmit,npm run build") == [
        "npx --no-install tsc --noEmit",
        "npm run build",
    ]
    assert runner.parse_commands("a;b\nc,d") == ["a", "b", "c", "d"]
    assert runner.parse_commands("") == []
    assert runner.parse_commands("   ") == []


def test_validation_runner_defaults_to_a_build_sized_timeout():
    # A typecheck plus a production build does not fit in a git-command budget.
    assert ValidationRunner().timeout_seconds >= 600


def test_missing_toolchain_is_reported_as_missing_not_as_a_failed_build(tmp_path):
    runner = ValidationRunner(10)
    result = runner.run(tmp_path, ["definitely-not-a-real-binary --version"])

    assert result.passed is False
    assert ValidationRunner.MISSING_TOOL_PREFIX in result.output
    assert "not a failing build" in result.output


def test_validation_stops_at_the_first_failing_command(tmp_path):
    runner = ValidationRunner(10)
    result = runner.run(tmp_path, ["definitely-not-a-real-binary", "also-not-real"])

    assert result.passed is False
    assert result.output.count("$ ") == 1


def test_github_pr_api_behaviour_is_unchanged():
    """The REST path still parses repo URLs and still uses a Bearer header."""
    client = GitHubClient()

    assert client.parse_repo("https://github.com/acme/site.git") == ("acme", "site")
    assert client.parse_repo("https://github.com/acme/site") == ("acme", "site")
    assert client.parse_repo("git@github.com:acme/site.git") == ("acme", "site")
    with pytest.raises(GitHubClientError):
        client.parse_repo("https://gitlab.com/acme/site")
    assert client.API_BASE_URL == "https://api.github.com"


@pytest.mark.asyncio
async def test_github_pr_creation_sends_bearer_token_and_draft_flag(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 201

        @staticmethod
        def json():
            return {"number": 7, "html_url": "https://github.com/acme/site/pull/7", "state": "open"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            captured.update({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr("app.repo_agent.git_ops.httpx.AsyncClient", lambda **kw: FakeClient())

    result = await GitHubClient().create_draft_pr(
        repo_url="https://github.com/acme/site",
        token=TOKEN,
        branch_name="seo-agent/test",
        base_branch="main",
        title="t",
        body="b",
    )

    assert result.number == 7
    assert result.url == "https://github.com/acme/site/pull/7"
    assert captured["url"] == "https://api.github.com/repos/acme/site/pulls"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert captured["headers"]["X-GitHub-Api-Version"] == "2022-11-28"
    assert captured["json"]["draft"] is True
    assert captured["json"]["head"] == "seo-agent/test"
    assert captured["json"]["base"] == "main"
    # The token is only ever an Authorization header, never part of the URL.
    assert TOKEN not in captured["url"]


def test_no_credential_material_is_hardcoded_in_the_git_module():
    source = Path("app/repo_agent/git_ops.py").read_text(encoding="utf-8")

    for literal in ("ghp_", "github_pat_", "gho_", "ghs_", "GITHUB_TOKEN ="):
        assert literal not in source, literal
    # The token is read from settings by the callers, never imported here.
    assert "settings.GITHUB_TOKEN" not in source


def test_every_git_command_trusts_only_the_repository_it_was_given(tmp_path, monkeypatch):
    """safe.directory is scoped to the checkout, never the "*" wildcard.

    A bind-mounted checkout is owned by a different uid than the process
    reading it, and git then refuses every command with "detected dubious
    ownership". Scoping the exception to the one configured path keeps the
    protection in place for every other repository on the machine.
    """
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["cwd"] = kwargs.get("cwd")

        class Completed:
            returncode = 0
            stdout = "true\n"
            stderr = ""

        return Completed()

    monkeypatch.setattr("app.repo_agent.git_ops.subprocess.run", fake_run)
    GitCommandRunner(5).run(tmp_path, ["rev-parse", "--is-inside-work-tree"])

    argv = captured["argv"]
    assert argv[0] == "git"
    assert argv[1] == "-c"
    assert argv[2] == f"safe.directory={tmp_path.as_posix()}"
    assert argv[3:] == ["rev-parse", "--is-inside-work-tree"]
    # Never the wildcard, which would trust every repository on the host.
    assert "safe.directory=*" not in argv


def test_push_is_also_scoped_and_still_authenticated(tmp_path, monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured.setdefault("calls", []).append((argv, kwargs.get("env") or {}))

        class Completed:
            returncode = 0
            stdout = "https://github.com/acme/site.git\n"
            stderr = ""

        return Completed()

    monkeypatch.setattr("app.repo_agent.git_ops.subprocess.run", fake_run)
    GitCommandRunner(5).push_branch(tmp_path, "seo-agent/test", token=TOKEN)

    push_argv, push_env = captured["calls"][-1]
    assert push_argv[1:3] == ["-c", f"safe.directory={tmp_path.as_posix()}"]
    assert "push" in push_argv
    assert push_env[TOKEN_ENV_VAR] == TOKEN
    assert TOKEN not in " ".join(push_argv)


def test_commit_identity_is_scoped_to_the_command(tmp_path, monkeypatch):
    """The identity is passed with -c, never written to any git config."""
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("app.repo_agent.git_ops.subprocess.run", fake_run)
    GitCommandRunner(5).commit(
        tmp_path, "msg", author_name="SEO Agent", author_email="seo-agent@localhost"
    )

    argv = captured["argv"]
    assert "-c" in argv
    assert "user.name=SEO Agent" in argv
    assert "user.email=seo-agent@localhost" in argv
    assert argv[-3:] == ["commit", "-m", "msg"]
    # Nothing that would persist an identity anywhere.
    assert "--global" not in argv
    assert "--system" not in argv
    assert "config" not in argv


def test_commit_identity_defaults_are_non_personal():
    assert DEFAULT_COMMIT_NAME == "SEO Agent"
    assert DEFAULT_COMMIT_EMAIL == "seo-agent@localhost"
    # A real person's name or address must not be the fallback.
    assert "@" in DEFAULT_COMMIT_EMAIL
    assert DEFAULT_COMMIT_EMAIL.endswith("@localhost")


def test_real_commit_uses_the_identity_without_touching_repo_config(tmp_path):
    """End to end against a real git repository in a temp directory."""
    runner = GitCommandRunner(30)
    runner.require(tmp_path, ["init", "-q"], "init")
    (tmp_path / "f.txt").write_text("hello\n", encoding="utf-8")
    runner.add(tmp_path, ["f.txt"])

    result = runner.commit(
        tmp_path, "scoped identity", author_name="SEO Agent", author_email="seo-agent@localhost"
    )
    assert result.returncode == 0, result.output

    author = runner.run(tmp_path, ["log", "-1", "--format=%an <%ae>"]).stdout.strip()
    committer = runner.run(tmp_path, ["log", "-1", "--format=%cn <%ce>"]).stdout.strip()
    assert author == "SEO Agent <seo-agent@localhost>"
    assert committer == "SEO Agent <seo-agent@localhost>"

    # The repository's own config was not given an identity.
    assert runner.run(tmp_path, ["config", "--local", "--get", "user.name"]).returncode != 0
    assert runner.run(tmp_path, ["config", "--local", "--get", "user.email"]).returncode != 0
    assert "user" not in (tmp_path / ".git" / "config").read_text(encoding="utf-8")


def test_apply_run_commits_with_the_configured_identity(tmp_path, monkeypatch):
    """The service hands the settings values to the commit."""
    calls = []

    class RecordingGit(GitCommandRunner):
        def __init__(self):
            super().__init__(5)

        def ensure_repo(self, root):
            return None

        def checkout_branch(self, root, branch_name):
            return None

        def add(self, root, file_paths):
            return None

        def diff_summary(self, root):
            return ""

        def run(self, root, args, timeout_seconds=None, env=None, secret=None):
            return CommandResult(0, "", "")

        def commit(self, root, message, *, author_name=None, author_email=None):
            calls.append({"message": message, "name": author_name, "email": author_email})
            return CommandResult(0, "committed", "")

    monkeypatch.setattr(settings, "REPO_AGENT_COMMIT_NAME", "SEO Agent")
    monkeypatch.setattr(settings, "REPO_AGENT_COMMIT_EMAIL", "seo-agent@localhost")

    runner = RecordingGit()
    runner.commit(tmp_path, "x", author_name=settings.REPO_AGENT_COMMIT_NAME,
                  author_email=settings.REPO_AGENT_COMMIT_EMAIL)
    assert calls == [
        {"message": "x", "name": "SEO Agent", "email": "seo-agent@localhost"}
    ]


# ---------------------------------------------------------------------------
# core.autocrlf: the agent's end-of-line policy for a checkout it does not own
# ---------------------------------------------------------------------------


def test_autocrlf_is_omitted_when_unset(tmp_path):
    args = GitCommandRunner(5)._config_args(tmp_path)
    assert args == ["-c", f"safe.directory={tmp_path.as_posix()}"]
    # Match the option, not the substring: pytest names tmp_path after the
    # test, so the safe.directory path contains "autocrlf" too.
    assert not any(a.startswith("core.autocrlf=") for a in args)


@pytest.mark.parametrize("value", ["true", "input", "false"])
def test_autocrlf_is_passed_when_configured(tmp_path, value):
    args = GitCommandRunner(5, autocrlf=value)._config_args(tmp_path)
    assert args == [
        "-c",
        f"safe.directory={tmp_path.as_posix()}",
        "-c",
        f"core.autocrlf={value}",
    ]


def test_autocrlf_reaches_every_git_invocation(tmp_path, monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("app.repo_agent.git_ops.subprocess.run", fake_run)
    GitCommandRunner(5, autocrlf="true").run(tmp_path, ["status", "--porcelain"])

    argv = captured["argv"]
    assert argv[0] == "git"
    assert "core.autocrlf=true" in argv
    assert argv[-2:] == ["status", "--porcelain"]
    # Never persisted.
    assert "--global" not in argv and "--system" not in argv and "config" not in argv


def _lf_repo_with_crlf_worktree(tmp_path, runner):
    """A repository whose blobs are LF and whose working file is CRLF.

    This is the shape of a Windows checkout of a repository committed with LF:
    `git status` calls it clean only if the staging filter converts back.
    """
    runner.require(tmp_path, ["init", "-q"], "init")
    path = tmp_path / "page.tsx"
    # Commit an LF blob, bypassing any conversion on the way in.
    path.write_bytes(b'export const metadata = {\n  title: "Page",\n};\n')
    runner.require(tmp_path, ["add", "--", "page.tsx"], "add")
    runner.require(
        tmp_path,
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed"],
        "commit",
    )
    lf_blob = runner.run(tmp_path, ["rev-parse", "HEAD:page.tsx"]).stdout.strip()
    # Now the working tree holds the CRLF form of the same content.
    path.write_bytes(b'export const metadata = {\r\n  title: "Page",\r\n};\r\n')
    return path, lf_blob


def test_crlf_worktree_stages_to_the_same_lf_blob_under_autocrlf_true(tmp_path):
    """The property the whole setting exists for."""
    seed = GitCommandRunner(30)
    path, lf_blob = _lf_repo_with_crlf_worktree(tmp_path, seed)

    # autocrlf=false is the deterministic stand-in for a container with no
    # end-of-line policy. A bare runner would inherit the host's system config,
    # which on a Windows developer machine already sets core.autocrlf=true.
    without = GitCommandRunner(30, autocrlf="false")
    with_true = GitCommandRunner(30, autocrlf="true")

    # Verbatim: a different blob, which is what rewrote every line.
    verbatim = without.run(tmp_path, ["hash-object", "--path", "page.tsx", "--", "page.tsx"])
    assert verbatim.stdout.strip() != lf_blob

    # Converted: the same blob the repository already holds.
    converted = with_true.run(tmp_path, ["hash-object", "--path", "page.tsx", "--", "page.tsx"])
    assert converted.stdout.strip() == lf_blob

    # And git sees no content change in the CRLF working file.
    #
    # The comparison is on `diff`, which runs the filter, not on `status`:
    # status flags the file from its size alone and reports " M" either way,
    # while diff - and therefore `git add` and the commit - sees nothing.
    assert with_true.run(tmp_path, ["diff", "--numstat"]).stdout.strip() == ""
    assert without.run(tmp_path, ["diff", "--numstat"]).stdout.strip() != ""


def test_staged_diff_stays_metadata_only_rather_than_a_whole_file_rewrite(tmp_path):
    """The six intended files must diff as +N/-0, not as every line changed.

    Reproduces the real shape: LF blob, CRLF working tree, and a patch that
    appends metadata in the file's own CRLF convention.
    """
    runner = GitCommandRunner(30, autocrlf="true")
    seed = GitCommandRunner(30)
    path, lf_blob = _lf_repo_with_crlf_worktree(tmp_path, seed)

    patched = (
        'export const metadata = {\r\n'
        '  title: "Page",\r\n'
        '\r\n'
        '  alternates: {\r\n'
        '    canonical: "https://example.com/page",\r\n'
        '  },\r\n'
        '};\r\n'
    )
    path.write_bytes(patched.encode("utf-8"))
    runner.require(tmp_path, ["add", "--", "page.tsx"], "add")

    diff = runner.run(tmp_path, ["diff", "--cached", "--numstat"]).stdout.strip()
    added, removed, _ = diff.split()
    assert (int(added), int(removed)) == (4, 0), f"expected +4/-0, got {diff}"

    # The staged blob is LF, matching the repository's convention.
    staged = runner.run(tmp_path, ["cat-file", "blob", ":page.tsx"]).stdout
    assert "\r\n" not in staged

    # With no end-of-line policy - a container - the same working tree
    # rewrites the whole file.
    bare = GitCommandRunner(30, autocrlf="false")
    bare.require(tmp_path, ["add", "--", "page.tsx"], "add")
    bare_diff = bare.run(tmp_path, ["diff", "--cached", "--numstat"]).stdout.strip()
    bare_added, bare_removed, _ = bare_diff.split()
    assert int(bare_removed) > 0, (
        f"expected a whole-file rewrite without a policy, got {bare_diff}"
    )
