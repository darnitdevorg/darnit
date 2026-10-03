"""Remediation policy and digest-bound approval (feature 043, R4, R5; framework-design 15.1-15.3).

The policy comes only from operator configuration (feature 040); nothing in
the audited repository is read for it. Under ``prompt`` a change set is
written only when its own digest is approved, either listed by the caller or
accepted by a person at a terminal. An approval of anything else, including a
batch of other change sets, never covers it. A plan item that requires
individual approval is approved the same way, by its own ``PlanItem.digest``.
"""

from __future__ import annotations

import difflib
import getpass
import sys
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from darnit.config.operator.schema import RemediationMode, RemediationSettings
from darnit.remediation.plan import Approval, FileChange, PlanItem, content_digest
from darnit.remediation.platform.model import ChangeSet, PlatformTarget
from darnit.remediation.platform.targets import show_value

Approver = Callable[[ChangeSet], bool]
ItemApprover = Callable[[PlanItem, Sequence[str]], bool]


def _os_user() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return "unknown"


@dataclass(frozen=True)
class ResolvedPolicy:
    """The ``[remediation]`` policy in effect, with where it came from and who approves."""

    settings: RemediationSettings = field(default_factory=RemediationSettings)
    operator_config_digest: str | None = None
    operator: str = field(default_factory=_os_user)


def resolve_policy(audit_target: str | Path) -> ResolvedPolicy:
    """The operator's remediation policy for remediating ``audit_target``.

    Raises:
        OperatorConfigError: the operator configuration cannot be loaded safely.
    """
    from darnit.config.operator.loader import resolve_operator_config

    loaded = resolve_operator_config(audit_target)
    return ResolvedPolicy(
        settings=loaded.config.remediation,
        operator_config_digest=loaded.digest,
        operator=loaded.config.operator.identity or _os_user(),
    )


def mode_for(settings: RemediationSettings, target: PlatformTarget) -> RemediationMode:
    return settings.high_impact if target.impact == "high_impact" else settings.platform


def approval_for(
    change_set: ChangeSet,
    *,
    policy: ResolvedPolicy,
    approvals: Collection[str],
    approver: Approver | None = None,
    now: datetime | None = None,
) -> Approval | None:
    """The approval of ``change_set`` under ``prompt``: its own digest listed, or a person's yes."""
    if change_set.digest not in approvals and (approver is None or not approver(change_set)):
        return None
    return Approval(digest=change_set.digest, approved_by=policy.operator, approved_at=now or datetime.now(UTC))


def describe_change_set(change_set: ChangeSet) -> list[str]:
    """The lines a person reads before approving ``change_set``."""
    target = change_set.target
    where = f"{target.owner}/{target.repo}" + (f" branch {target.branch}" if target.branch else "")
    lines = [f"Platform change: {target.kind} on {where} ({target.impact})"]
    for operation in change_set.operations:
        lines.append(f"  {operation.method} {operation.endpoint}")
        for change in operation.changes:
            lines.append(f"    {change.field}: {show_value(change.before)} -> {show_value(change.after)}")
    lines += [f"  Impact: {note}" for note in change_set.impact_notes]
    lines.append(f"  Digest: {change_set.digest}")
    return lines


def _printable(text: str) -> str:
    """``text`` with every character outside printable ASCII escaped, so file content cannot drive the terminal."""
    return "".join(c if " " <= c <= "~" else c.encode("unicode_escape").decode("ascii") for c in text)


def _current_text(root: str | Path | None, change: FileChange) -> str | None:
    """The file ``change`` modifies as it is now, if it is still the content the change was planned against."""
    if root is None:
        return None
    try:
        current = (Path(root) / change.path).read_bytes()
    except OSError:
        return None
    if content_digest(current) != change.before_digest:
        return None
    try:
        return current.decode("utf-8")
    except UnicodeDecodeError:
        return None


_NO_FINAL_NEWLINE = "\\ No newline at end of file"


def _lines(text: str) -> list[str]:
    """``text`` split after each ``\\n`` only, every line keeping its ending; other separators stay inside lines."""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _shown(prefix: str, line: str) -> list[str]:
    """One content line: ``\\n`` implied, any other ending or separator escaped, and git's marker when none ends it."""
    if line.endswith("\n"):
        return [f"{prefix}{_printable(line[:-1])}"]
    return [f"{prefix}{_printable(line)}", _NO_FINAL_NEWLINE]


def _full_content(change: FileChange, note: str) -> list[str]:
    resulting = _lines(change.content or "")
    header = f"  {change.action} {_printable(change.path)} ({len(resulting)} lines{note}):"
    return [header] + [f"    {shown}" for line in resulting for shown in _shown("| ", line)]


def _file_lines(change: FileChange, root: str | Path | None) -> list[str]:
    """``change`` in full: a created file's content, or a modified file's diff against its current content.

    Line endings and separators are shown escaped (``\\r``, ``\\u2028``), and a
    missing final newline is marked, so a change only in whitespace or line
    endings is never an empty diff.
    """
    current = _current_text(root, change) if change.action == "modify" else None
    if current is None:
        note = "; the current file cannot be read, so the full resulting content follows" if change.action == "modify" else ""
        return _full_content(change, note)
    diff = list(
        difflib.unified_diff(
            _lines(current), _lines(change.content or ""), fromfile=f"a/{change.path}", tofile=f"b/{change.path}", n=3
        )
    )
    if not diff and current.encode("utf-8") != (change.content or "").encode("utf-8"):
        return _full_content(
            change,
            "; no line differs as text, so the change is in whitespace or line endings; "
            "the full resulting content follows, escaped",
        )
    lines = [f"  modify {_printable(change.path)} (diff against the current file):"]
    lines += [f"    {_printable(header.rstrip(chr(10)))}" for header in diff[:2]]
    for line in diff[2:]:
        if line.startswith("@@"):
            lines.append(f"    {_printable(line.rstrip(chr(10)))}")
        else:
            lines += [f"    {shown}" for shown in _shown(line[0], line[1:])]
    return lines


def describe_plan_item(item: PlanItem, reasons: Sequence[str], root: str | Path | None = None) -> list[str]:
    """The lines a person reads before approving ``item`` individually (framework-design 15.3, 15.8).

    Nothing is truncated: a created file is shown in full, a modified file as
    a unified diff against its current content under ``root`` (in full when
    that cannot be read), every character escaped to printable ASCII.
    """
    lines = [f"Remediation step: {item.control_id} {item.step}"]
    lines += [f"  Needs individual approval: {reason}" for reason in reasons]
    for change in item.file_changes:
        if not change.changes:
            lines.append(f"  {_printable(change.path)}: not written ({change.reason})")
            continue
        lines += _file_lines(change, root)
    lines += [f"  Command: {_printable(' '.join(command))}" for command in item.commands]
    for change_set in item.change_sets:
        lines += [f"  {line}" for line in describe_change_set(ChangeSet.model_validate(change_set))]
    if not item.previewable:
        lines.append("  Cannot be previewed exactly: it may change files or settings not listed here")
    lines.append(f"  Digest: {item.digest}")
    return lines


class TerminalApprover:
    """Asks a person at the terminal to approve each change set or plan item (the feature 027 ``/dev/tty`` pattern).

    Both streams None opens ``/dev/tty`` on first use, so the prompt never
    mixes with the report on stdout. Anything but ``y``/``yes`` is a refusal,
    and so is end of input.
    """

    def __init__(
        self,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        *,
        root: str | Path | None = None,
    ) -> None:
        if (input_stream is None) != (output_stream is None):
            raise ValueError("TerminalApprover takes both streams or neither")
        self._input = input_stream
        self._output = output_stream
        self._root = root

    def _streams(self) -> tuple[TextIO, TextIO]:
        if self._input is None or self._output is None:
            tty = open("/dev/tty", "r+", buffering=1, encoding="utf-8")  # noqa: SIM115
            self._input = self._output = tty
        return self._input, self._output

    def _ask(self, lines: list[str], question: str) -> bool:
        source, sink = self._streams()
        sink.write("\n" + "\n".join(lines) + f"\n{question} [y/N] ")
        sink.flush()
        try:
            answer = source.readline()
        except (KeyboardInterrupt, OSError):
            return False
        return answer.strip().lower() in ("y", "yes")

    def __call__(self, change_set: ChangeSet) -> bool:
        return self._ask(describe_change_set(change_set), "Apply this change?")

    def approve_item(self, item: PlanItem, reasons: Sequence[str]) -> bool:
        return self._ask(describe_plan_item(item, reasons, self._root), "Apply this step?")


def terminal_approver(root: str | Path | None = None) -> TerminalApprover | None:
    """A :class:`TerminalApprover` when a person can be asked, else None (outcome ``needs_approval``).

    ``root`` is the checkout whose current files a modified file is diffed against.
    """
    if not sys.stdin.isatty():
        return None
    try:
        tty = open("/dev/tty", "r+", buffering=1, encoding="utf-8")  # noqa: SIM115
    except OSError:
        return None
    return TerminalApprover(tty, tty, root=root)


__all__ = [
    "Approver",
    "ItemApprover",
    "ResolvedPolicy",
    "TerminalApprover",
    "approval_for",
    "describe_change_set",
    "describe_plan_item",
    "mode_for",
    "resolve_policy",
    "terminal_approver",
]
