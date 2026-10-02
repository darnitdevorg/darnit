"""Shared utility functions for the baseline MCP server."""

import glob as glob_module
import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping
from typing import Any, NamedTuple

from darnit.core.error_class import ErrorClass
from darnit.core.logging import get_logger
from darnit.trust.identity import IdentitySource, RepositoryIdentity, canonical_identity

logger = get_logger("utils")

_GH_CLI_MISSING_MESSAGE = (
    "GitHub CLI (gh) not found. Install it from https://cli.github.com/ "
    "and run 'gh auth login' to authenticate."
)

# Feature 032: `go-gh` emits HTTP-error lines on stderr with the prefix
# ``HTTP <code>: <message>``; we parse the first three digits to surface
# the status code to callers that need to distinguish 404 from 403 from
# 5xx. `gh api`'s own error formatter puts the code at the END of the
# line instead: ``<message> (HTTP <code>)``, e.g. ``Not Found (HTTP 404)``,
# further wrapped by the root command as ``gh: <message> (HTTP <code>)``.
# Format is stable across gh 2.x per research decision R-001.
_HTTP_STATUS_RE = re.compile(
    r"^HTTP (\d{3}):"  # go-gh SDK `HTTPError.Error()`: "HTTP 404: Not Found (...)"
    r"|\(HTTP (\d{3})\)",  # `gh api` subcommand's own formatter: "gh: Not Found (HTTP 404)"
    re.MULTILINE,
)

GhApiResponse = tuple[dict[str, Any] | list[Any] | None, int, str]
GhApiResponder = Callable[[str, str, Any], GhApiResponse]

# Feature 041: when set, ``gh_api_with_status`` returns this responder's
# answer instead of running ``gh``. Tests and the adversarial corpus use it
# to serve recorded platform responses offline (see RecordedGhApi).
# Feature 043: the responder is called as ``(method, endpoint, body)``;
# ``gh_api_with_status`` calls it with ``("GET", endpoint, None)`` and
# ``gh_api_write`` with the write method and its JSON payload.
_gh_api_responder: GhApiResponder | None = None

_GH_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_GH_METHODS = _GH_WRITE_METHODS | {"GET"}


def set_gh_api_responder(responder: GhApiResponder | None) -> GhApiResponder | None:
    """Route ``gh_api_with_status`` and ``gh_api_write`` through ``responder`` (None restores ``gh``).

    Returns the previous responder so callers can restore it.
    """
    global _gh_api_responder
    previous = _gh_api_responder
    _gh_api_responder = responder
    return previous


class GhApiCall(NamedTuple):
    """One request seen by :class:`RecordedGhApi`.

    Compares equal to its recording key: the bare path (or ``"GET <path>"``)
    for a GET, ``"<METHOD> <path>"`` for a write.
    """

    method: str
    endpoint: str
    body: Any = None

    def _matches(self, key: str) -> bool:
        if self.method == "GET" and key == self.endpoint:
            return True
        return key == f"{self.method} {self.endpoint}"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self._matches(other)
        return tuple.__eq__(self, other)

    def __ne__(self, other: object) -> bool:
        return not self == other

    def __hash__(self) -> int:
        return hash((self.method, self.endpoint, json.dumps(self.body, sort_keys=True, default=str)))


class RecordedGhApi:
    """A responder serving recorded platform responses keyed by method and API path.

    ``responses`` maps a key to ``{"status": int, "body": ..., "error": str}``.
    A key is ``"<METHOD> <endpoint>"`` (e.g. ``"PUT /repos/o/r/branches/main/protection"``)
    or a bare endpoint, which means GET; the endpoint is taken after
    ``$OWNER``/``$REPO``/``$BRANCH`` substitution, leading slash optional.
    A request with no recording answers as a transport failure (status 0),
    so an offline run never reaches the network and never mistakes a
    missing recording for a platform answer. ``gh_missing=True`` answers
    every call as if ``gh`` were not installed. Every request is appended
    to ``calls`` as a :class:`GhApiCall`, including the body it sent.
    """

    def __init__(self, responses: Mapping[str, Mapping[str, Any]] | None = None, *, gh_missing: bool = False):
        self.responses: dict[tuple[str, str], dict[str, Any]] = {}
        for key, response in (responses or {}).items():
            self.record(key, response)
        self.gh_missing = gh_missing
        self.calls: list[GhApiCall] = []

    @staticmethod
    def _path(endpoint: str) -> str:
        return "/" + endpoint.lstrip("/")

    @classmethod
    def _key(cls, key: str) -> tuple[str, str]:
        head, sep, rest = key.strip().partition(" ")
        if sep and head.upper() in _GH_METHODS:
            return head.upper(), cls._path(rest.strip())
        return "GET", cls._path(key.strip())

    def record(self, key: str, response: Mapping[str, Any]) -> None:
        """Add or replace the recording for ``key``."""
        self.responses[self._key(key)] = dict(response)

    @property
    def writes(self) -> list[GhApiCall]:
        return [call for call in self.calls if call.method != "GET"]

    def __call__(self, method: str, endpoint: str | None = None, body: Any = None) -> GhApiResponse:
        if endpoint is None:
            method, endpoint = "GET", method
        method = method.upper()
        self.calls.append(GhApiCall(method, endpoint, body))
        if self.gh_missing:
            return None, 0, _GH_CLI_MISSING_MESSAGE
        recorded = self.responses.get((method, self._path(endpoint)))
        if recorded is None:
            return None, 0, f"no recorded response for {method} {endpoint}"
        status = int(recorded.get("status", 200))
        if 200 <= status < 300:
            return recorded.get("body"), status, ""
        return None, status, str(recorded.get("error") or f"HTTP {status}")


_GH_RATE_LIMIT_MARKERS: tuple[str, ...] = (
    "api rate limit exceeded",
    "secondary rate limit",
    "abuse detection mechanism",
)


def gh_api_error_class(status: int, error: str) -> ErrorClass:
    """Classify a non-2xx ``gh_api_with_status`` answer (feature 041).

    ``missing_tool`` when ``gh`` is not installed; ``rate_limit`` for 429 or
    a 403 whose message is a rate limit; ``auth`` for 401 and other 403s;
    ``unavailable`` for everything else (5xx, transport failure, an
    undeclared status).
    """
    if status == 0 and (error or "").startswith(_GH_CLI_MISSING_MESSAGE[:25]):
        return "missing_tool"
    lowered = (error or "").lower()
    if status == 429 or (status == 403 and any(m in lowered for m in _GH_RATE_LIMIT_MARKERS)):
        return "rate_limit"
    if status in (401, 403):
        return "auth"
    return "unavailable"


def gh_api_with_status(
    endpoint: str, *, paginate: bool = False
) -> tuple[dict[str, Any] | list[Any] | None, int, str]:
    """Execute a GitHub API call via ``gh api`` and return ``(body, status, error)``.

    Contract (feature 032):

    * On 2xx: ``(parsed_json, status_code, "")``. ``parsed_json`` may be a
      dict OR a list -- the rulesets endpoint returns a top-level list.
    * On non-2xx with a parseable status code in stderr -- either the
      go-gh SDK's ``HTTP <code>: <message>`` prefix or the `gh api`
      subcommand's own ``<message> (HTTP <code>)`` suffix form --:
      ``(None, status_code, stderr_message)``.
    * On subprocess-not-found, JSON-decode failure on a 2xx body, or any
      other pre-response failure: ``(None, 0, error_message)``. Callers
      MUST treat ``status == 0`` as ambiguous (WARN, not FAIL) per the
      Constitution's conservative-by-default posture.

    When ``paginate=True``, ``gh api --paginate`` is invoked; ``gh``
    concatenates all pages into a single JSON array at the top level.

    When a responder is installed with :func:`set_gh_api_responder`, its
    answer is returned instead (feature 041).
    """
    if _gh_api_responder is not None:
        return _gh_api_responder("GET", endpoint, None)
    args = ["gh", "api"]
    if paginate:
        args.append("--paginate")
    args.append(endpoint)
    try:
        result = subprocess.run(args, capture_output=True, text=True)
    except FileNotFoundError:
        return None, 0, _GH_CLI_MISSING_MESSAGE

    if result.returncode == 0:
        try:
            body = json.loads(result.stdout) if result.stdout.strip() else None
        except json.JSONDecodeError as err:
            return None, 0, f"GitHub API returned invalid JSON for {endpoint}: {err}"
        return body, 200, ""

    stderr = (result.stderr or "").strip()
    match = _HTTP_STATUS_RE.search(stderr)
    if match:
        status = int(match.group(1) or match.group(2))
        return None, status, stderr
    return None, 0, stderr or f"gh api failed with exit code {result.returncode}"


_INCLUDED_STATUS_RE = re.compile(r"^HTTP/\d(?:\.\d)?\s+(\d{3})\b")


def _split_included(stdout: str) -> tuple[int | None, str]:
    """Split ``gh api --include`` output into the HTTP status and the raw body."""
    text = stdout.replace("\r\n", "\n")
    match = _INCLUDED_STATUS_RE.match(text)
    if match is None:
        return None, ""
    _headers, _sep, body = text.partition("\n\n")
    return int(match.group(1)), body


def _error_body_message(raw_body: str) -> str:
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        return ""
    return str(parsed.get("message") or "") if isinstance(parsed, dict) else ""


def gh_api_write(method: str, endpoint: str, payload: Mapping[str, Any] | list[Any] | None = None) -> GhApiResponse:
    """Send a write to the GitHub API via ``gh api`` and return ``(body, status, error)`` (feature 043).

    ``payload`` is sent as JSON on stdin (``--input -``), never as
    ``-f``/``-F`` fields, so booleans, numbers, nulls and nested objects
    keep their types. The status comes from the ``--include`` status line.

    * On 2xx: ``(parsed_json_or_None, status, "")``.
    * On an HTTP error: ``(None, status, message)``; never raises.
    * When no status can be read (``gh`` missing, transport failure, a
      2xx body that is not JSON): ``(None, 0, message)``. Callers MUST
      treat ``status == 0`` as unknown -- the write may or may not have
      happened -- and read the setting back.

    Raises ``ValueError`` only for a method that is not a write. When a
    responder is installed with :func:`set_gh_api_responder`, it answers
    ``(method, endpoint, payload)`` instead.
    """
    verb = method.upper()
    if verb not in _GH_WRITE_METHODS:
        raise ValueError(f"gh_api_write: unsupported method {method!r}")
    if _gh_api_responder is not None:
        return _gh_api_responder(verb, endpoint, payload)
    args = ["gh", "api", "-X", verb, endpoint, "--include"]
    stdin = None
    if payload is not None:
        args += ["--input", "-"]
        stdin = json.dumps(payload)
    try:
        result = subprocess.run(args, input=stdin, capture_output=True, text=True)
    except FileNotFoundError:
        return None, 0, _GH_CLI_MISSING_MESSAGE

    stderr = (result.stderr or "").strip()
    status, raw_body = _split_included(result.stdout or "")
    if status is None:
        match = _HTTP_STATUS_RE.search(stderr)
        if match:
            return None, int(match.group(1) or match.group(2)), stderr
        return None, 0, stderr or f"gh api -X {verb} {endpoint} failed with exit code {result.returncode}"

    if 200 <= status < 300:
        try:
            body = json.loads(raw_body) if raw_body.strip() else None
        except json.JSONDecodeError as err:
            return None, 0, f"GitHub API returned invalid JSON for {verb} {endpoint}: {err}"
        return body, status, ""
    return None, status, stderr or _error_body_message(raw_body) or f"HTTP {status}"


def gh_api(endpoint: str) -> dict[str, Any]:
    """Execute a GitHub API call using the gh CLI.

    Preserved contract for existing callers: returns the parsed dict on
    2xx, raises ``RuntimeError`` on any non-2xx or non-dict response.
    Implementation is a thin wrapper over :func:`gh_api_with_status`.

    Raises:
        RuntimeError: If the API call fails, returns invalid JSON, or
            returns a non-dict body (e.g., a list from a paginated list
            endpoint -- such callers MUST use ``gh_api_with_status``
            directly).
    """
    body, status, error = gh_api_with_status(endpoint)
    if status == 200 and isinstance(body, dict):
        return body
    if status == 200:
        raise RuntimeError(
            f"gh api {endpoint}: expected dict body but got {type(body).__name__}"
        )
    raise RuntimeError(f"gh api failed: {error or 'status ' + str(status)}")


def gh_api_safe(endpoint: str) -> dict[str, Any] | None:
    """Execute a GitHub API call, returning None on failure."""
    try:
        return gh_api(endpoint)
    except RuntimeError as e:
        logger.debug(f"GitHub API call failed for {endpoint}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"GitHub API returned invalid JSON for {endpoint}: {e}")
        return None


def validate_local_path(
    local_path: str,
    expected_owner: str | None = None,
    expected_repo: str | None = None
) -> tuple[str, str | None]:
    """
    Validate and resolve the local_path.
    Returns (resolved_path, error_message).
    If error_message is not None, the path is invalid.

    Args:
        local_path: Path to validate
        expected_owner: If provided, used for mismatch detection
        expected_repo: If provided, used for mismatch detection
    """
    # Resolve to absolute path
    abs_path = os.path.abspath(local_path)

    # Check if path exists
    if not os.path.exists(abs_path):
        return abs_path, f"Path does not exist: {abs_path}"

    # Check if it's a directory
    if not os.path.isdir(abs_path):
        return abs_path, f"Path is not a directory: {abs_path}"

    # Check if it's a git repository
    git_dir = os.path.join(abs_path, ".git")
    if not os.path.exists(git_dir):
        # Special warning for "." since it's a common mistake with MCP servers
        if local_path == ".":
            return abs_path, (
                f"Path '{abs_path}' is not a git repository. "
                f"Note: When using MCP tools, '.' resolves to the MCP server's directory, "
                f"not your current working directory. Please provide an absolute path instead."
            )
        return abs_path, f"Path is not a git repository (no .git directory): {abs_path}"

    # If local_path is "." and we have expected owner/repo, do extra validation
    if local_path == "." and expected_owner and expected_repo:
        dir_name = os.path.basename(abs_path)
        if dir_name.lower() != expected_repo.lower():
            try:
                result = subprocess.run(
                    ["git", "-C", abs_path, "remote", "get-url", "origin"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    remote_url = result.stdout.strip()
                    match = re.search(r'[:/]([^/:]+)/([^/]+?)(?:\.git)?$', remote_url)
                    if match:
                        detected_owner, detected_repo = match.groups()
                        if detected_owner.lower() != expected_owner.lower() or detected_repo.lower() != expected_repo.lower():
                            return abs_path, (
                                f"Path mismatch detected!\n\n"
                                f"You requested audit for: {expected_owner}/{expected_repo}\n"
                                f"But local_path='.' resolved to: {abs_path}\n"
                                f"Which is actually: {detected_owner}/{detected_repo}\n\n"
                                f"When using MCP tools, '.' resolves to the MCP server's directory, "
                                f"NOT your current working directory.\n\n"
                                f"Solution: Use an absolute path:\n"
                                f"  local_path=\"/path/to/{expected_repo}\""
                            )
                else:
                    return abs_path, (
                        f"Potential path mismatch!\n\n"
                        f"You requested audit for: {expected_owner}/{expected_repo}\n"
                        f"But local_path='.' resolved to: {abs_path}\n"
                        f"Directory name '{dir_name}' doesn't match expected repo '{expected_repo}'.\n\n"
                        f"When using MCP tools, '.' resolves to the MCP server's directory, "
                        f"NOT your current working directory.\n\n"
                        f"Solution: Use an absolute path:\n"
                        f"  local_path=\"/path/to/{expected_repo}\""
                    )
            except subprocess.TimeoutExpired:
                logger.debug(f"Git command timed out checking remote for {abs_path}")
                return abs_path, (
                    f"Potential path mismatch!\n\n"
                    f"You requested audit for: {expected_owner}/{expected_repo}\n"
                    f"But local_path='.' resolved to: {abs_path}\n"
                    f"Directory name '{dir_name}' doesn't match expected repo '{expected_repo}'.\n\n"
                    f"When using MCP tools, '.' resolves to the MCP server's directory, "
                    f"NOT your current working directory.\n\n"
                    f"Solution: Use an absolute path:\n"
                    f"  local_path=\"/path/to/{expected_repo}\""
                )
            except (OSError, subprocess.SubprocessError) as e:
                logger.debug(f"Git command failed for {abs_path}: {type(e).__name__}")
                return abs_path, (
                    f"Potential path mismatch!\n\n"
                    f"You requested audit for: {expected_owner}/{expected_repo}\n"
                    f"But local_path='.' resolved to: {abs_path}\n"
                    f"Directory name '{dir_name}' doesn't match expected repo '{expected_repo}'.\n\n"
                    f"When using MCP tools, '.' resolves to the MCP server's directory, "
                    f"NOT your current working directory.\n\n"
                    f"Solution: Use an absolute path:\n"
                    f"  local_path=\"/path/to/{expected_repo}\""
                )

    return abs_path, None


def _get_remote_url(remote_name: str, cwd: str) -> str | None:
    """Get the URL of a named git remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote_name],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def _parse_github_url(url: str) -> tuple[str, str] | None:
    """Parse owner/repo from a GitHub remote URL."""
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
    if match:
        return match.group(1), match.group(2)
    return None


def detect_checkout_identity(
    local_path: str, case_insensitive_hosts: Iterable[str] = ()
) -> RepositoryIdentity | None:
    """Canonical identity of the checkout's ``origin`` remote, as a hint only.

    Remotes are part of the audited checkout, so this identity is never
    eligible for trust (feature 040, FR-016a); an ``upstream`` remote is
    never consulted.
    """
    url = _get_remote_url("origin", local_path)
    canonical = canonical_identity(url, case_insensitive_hosts) if url else None
    if canonical is None:
        return None
    return RepositoryIdentity(canonical, IdentitySource.CHECKOUT_HINT)


def detect_repo_from_git(
    local_path: str,
    *,
    prefer_upstream: bool = False,
    owner: str | None = None,
    repo: str | None = None,
) -> dict[str, Any] | None:
    """Canonical repo identity detection — single source of truth.

    Resolves the repository owner, name, and metadata. This is the ONLY
    function in the codebase that should parse git remotes or call external
    tools for owner/repo detection.

    Resolution order:
    1. If both owner and repo are provided explicitly, return immediately.
    2. Check git remotes (origin first, then upstream) for owner/repo.
    3. Enrich with metadata from gh CLI if available.

    The result describes the checkout and is never a basis for trust; see
    :func:`detect_checkout_identity`.

    Args:
        local_path: Path to the git repository.
        prefer_upstream: If True, check 'upstream' remote before 'origin'.
            Default False: a fork clone is identified as itself.
        owner: Explicit owner override. Skips detection if both owner and
            repo are provided.
        repo: Explicit repo override. Skips detection if both owner and
            repo are provided.

    Returns:
        Dict with owner, repo, url, is_private, default_branch,
        resolved_path, source, and identity (the remote's canonical
        ``host/namespace/name``, or None) -- or None if detection fails
        entirely.
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return None

    # Short-circuit: both explicitly provided
    if owner and repo:
        return {
            "owner": owner,
            "repo": repo,
            "url": "",
            "is_private": False,
            "default_branch": "main",
            "resolved_path": resolved_path,
            "source": "explicit",
            "identity": None,
        }

    # Detect from git remotes
    remotes = ["upstream", "origin"] if prefer_upstream else ["origin", "upstream"]
    detected_owner = None
    detected_repo = None
    source = None
    identity = None

    for remote in remotes:
        url = _get_remote_url(remote, resolved_path)
        if url:
            parsed = _parse_github_url(url)
            if parsed:
                detected_owner, detected_repo = parsed
                source = remote
                identity = canonical_identity(url)
                break

    # Apply explicit overrides for partial specification
    final_owner = owner or detected_owner
    final_repo = repo or detected_repo

    if not final_owner or not final_repo:
        return None

    if (owner and not repo) or (repo and not owner):
        source = source or "explicit"

    # Enrich with gh metadata
    metadata = _gh_enrich(final_owner, final_repo, resolved_path)

    return {
        "owner": final_owner,
        "repo": final_repo,
        "url": metadata.get("url", ""),
        "is_private": metadata.get("is_private", False),
        "default_branch": metadata.get("default_branch", "main"),
        "resolved_path": resolved_path,
        "source": source or "fallback",
        "identity": identity,
    }


def _gh_enrich(owner: str, repo: str, cwd: str) -> dict[str, Any]:
    """Fetch enriched metadata from gh CLI for a specific owner/repo."""
    try:
        result = subprocess.run(
            [
                "gh", "repo", "view", f"{owner}/{repo}",
                "--json", "url,isPrivate,defaultBranchRef",
            ],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        return {
            "url": data.get("url", ""),
            "is_private": data.get("isPrivate", False),
            "default_branch": data.get("defaultBranchRef", {}).get("name", "main"),
        }
    except FileNotFoundError:
        logger.debug(_GH_CLI_MISSING_MESSAGE)
        return {}
    except (subprocess.TimeoutExpired, json.JSONDecodeError,
            OSError, subprocess.SubprocessError) as e:
        logger.debug(f"gh enrichment failed for {owner}/{repo}: {type(e).__name__}: {e}")
        return {}


def detect_owner_repo(
    local_path: str,
    *,
    prefer_upstream: bool = False,
    owner: str | None = None,
    repo: str | None = None,
) -> tuple[str, str]:
    """Convenience wrapper returning (owner, repo) tuple.

    Delegates to detect_repo_from_git() and extracts the owner/repo.
    Returns ("", directory_name) if detection fails.
    """
    info = detect_repo_from_git(
        local_path,
        prefer_upstream=prefer_upstream,
        owner=owner,
        repo=repo,
    )
    if info:
        return info["owner"], info["repo"]
    path_name = os.path.basename(os.path.abspath(local_path))
    return "", path_name


def file_exists(local_path: str, *patterns: str) -> bool:
    """Check if any file matching the patterns exists."""
    for pattern in patterns:
        matches = glob_module.glob(os.path.join(local_path, pattern), recursive=True)
        if matches:
            return True
    return False


def file_contains(local_path: str, filename_patterns: list[str], content_pattern: str) -> bool:
    """Check if any matching file contains the content pattern."""
    for pattern in filename_patterns:
        for filepath in glob_module.glob(os.path.join(local_path, pattern), recursive=True):
            try:
                with open(filepath, encoding='utf-8', errors='ignore') as f:
                    if re.search(content_pattern, f.read(), re.IGNORECASE):
                        return True
            except OSError as e:
                logger.debug(f"Could not read {filepath}: {type(e).__name__}")
                continue
    return False


def read_file(local_path: str, filename: str) -> str | None:
    """Read a file's contents, returning None if not found."""
    filepath = os.path.join(local_path, filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding='utf-8', errors='ignore') as f:
                return f.read()
        except OSError as e:
            logger.debug(f"Could not read {filepath}: {type(e).__name__}")
            return None
    return None


def make_result(control_id: str, status: str, details: str, level: int = 1) -> dict[str, Any]:
    """Create a standardized result dictionary."""
    return {"id": control_id, "status": status, "details": details, "level": level}


def get_git_commit(local_path: str) -> str | None:
    """Get the current git commit SHA."""
    try:
        result = subprocess.run(
            ["git", "-C", local_path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"git rev-parse timed out for {local_path}")
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as e:
        logger.debug(f"git rev-parse failed: {type(e).__name__}")
    return None


def get_git_ref(local_path: str) -> str | None:
    """Get the current git branch/ref."""
    try:
        result = subprocess.run(
            ["git", "-C", local_path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            if ref != "HEAD":
                return ref
        # Try to get tag
        result = subprocess.run(
            ["git", "-C", local_path, "describe", "--tags", "--exact-match"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"git ref command timed out for {local_path}")
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as e:
        logger.debug(f"git ref command failed: {type(e).__name__}")
    return None
