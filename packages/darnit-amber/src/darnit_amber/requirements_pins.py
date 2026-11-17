"""Classify the pinning strength of a requirements.txt (feature 037, issue #429).

This module takes text and returns a classification. It performs no file
discovery, constructs no ``HandlerResult``, and decides no verdict -- mapping a
classification to PASS / WARN / FAIL belongs to the handler. Keeping the
boundary here is what lets the classification table be tested as a pure
function.

See specs/037-pinned-requirements-detection/contracts/requirements-classification.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from packaging.requirements import InvalidRequirement, Requirement


class PinClassification(str, Enum):
    """The verdict about a single requirement line."""

    HASH_PINNED = "hash_pinned"
    EXACTLY_PINNED = "exactly_pinned"
    NOT_PINNED = "not_pinned"


class FileClassification(str, Enum):
    """The verdict about the file as a whole. The weakest line governs."""

    HASH_PINNED = "hash_pinned"
    VERSION_PINNED = "version_pinned"
    UNPINNED = "unpinned"
    NOT_INSPECTABLE = "not_inspectable"
    NO_REQUIREMENTS = "no_requirements"


@dataclass
class RequirementLine:
    """One logical dependency declaration, after preprocessing."""

    raw: str
    name: str | None = None
    specifier: str = ""
    hashes: list[str] = field(default_factory=list)
    url: str | None = None
    pin: PinClassification = PinClassification.NOT_PINNED


@dataclass
class ClassificationReport:
    """What the classifier concluded, and the lines that drove it."""

    classification: FileClassification
    lines: list[RequirementLine] = field(default_factory=list)
    unpinned: list[str] = field(default_factory=list)
    unhashed: list[str] = field(default_factory=list)
    reason: str = ""


# A full git object id. 40 hex for SHA-1, 64 for SHA-256. Anything shorter is
# an abbreviation, and git resolves abbreviations against repository state at
# fetch time, so it does not pin (FR-010).
_FULL_OBJECT_ID = re.compile(r"^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$")

_HASH_OPTION = re.compile(r"--hash[= ]([A-Za-z0-9_]+:[0-9a-fA-F]+)")

# pip option lines. These configure resolution; they are not dependency
# declarations and are skipped rather than classified (FR-018).
_OPTION_PREFIXES = (
    "--index-url",
    "--extra-index-url",
    "--find-links",
    "--no-binary",
    "--only-binary",
    "--prefer-binary",
    "--require-hashes",
    "--no-index",
    "--pre",
    "--trusted-host",
    "--use-feature",
    "-i ",
    "-f ",
)

# Includes defer part of the file to another file. Following them is out of
# scope for v0, and a file with an unresolved include has not been fully
# inspected (FR-007).
_INCLUDE_PREFIXES = ("-r ", "-r=", "--requirement", "-c ", "-c=", "--constraint")


def _strip_comment(line: str) -> str:
    """Remove a trailing comment.

    pip treats ``#`` as a comment only at line start or after whitespace, which
    is what keeps a URL fragment such as ``...#egg=name`` intact.
    """
    return re.split(r"(?:^|\s)#", line, maxsplit=1)[0]


def _join_continuations(text: str) -> list[str]:
    """Fold backslash continuations into logical lines.

    Must run before hash collection: ``pip-compile --generate-hashes`` emits
    hashes on continuation lines, so collecting first would miss them.
    """
    logical: list[str] = []
    buffer = ""
    for physical in text.splitlines():
        stripped = physical.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1].rstrip() + " "
            continue
        buffer += stripped
        logical.append(buffer)
        buffer = ""
    if buffer:
        logical.append(buffer)
    return logical


def _is_self_reference(line: str) -> bool:
    """True for an editable or path install naming the project, not a dependency.

    ``-e .`` is the overwhelmingly common shape. ``-e git+https://...`` is a
    real dependency and is not skipped.
    """
    body = line
    for prefix in ("-e ", "--editable ", "-e=", "--editable="):
        if body.startswith(prefix):
            body = body[len(prefix) :].strip()
            break
    else:
        # Not editable. A bare local path is still a self-reference.
        return body in (".", "..") or body.startswith(("./", "../"))
    return "://" not in body and "+" not in body


def _is_bare_url(body: str) -> bool:
    """True for a pip-style bare URL requirement.

    ``pkg @ git+https://...`` is PEP 508 and parses. A bare
    ``git+https://.../repo@<sha>#egg=pkg`` is valid pip input but NOT valid
    PEP 508, so ``Requirement`` rejects it. Treating that rejection as "we
    could not read the file" would report a genuinely SHA-pinned dependency
    as uninspectable.
    """
    return "://" in body and "@" not in body.split("://", 1)[0]


def _url_is_pinned(url: str) -> bool:
    """A direct reference pins only at a full object id."""
    target = url.split("#", 1)[0]
    candidate = target.rsplit("@", 1)[-1] if "@" in target else ""
    return bool(_FULL_OBJECT_ID.match(candidate))


def _classify_line(req: Requirement, hashes: list[str]) -> PinClassification:
    if req.url is not None:
        if _url_is_pinned(req.url):
            # Pinned, but never hash evidence: pip cannot enforce hashes on a
            # VCS reference, so a file containing one is not a require-hashes
            # file and must not borrow that tier's justification (FR-010).
            return PinClassification.EXACTLY_PINNED
        return PinClassification.NOT_PINNED

    clauses = list(req.specifier)
    if len(clauses) != 1:
        # No specifier at all, or a compound one such as `pkg>=1.0,<2.0`.
        return PinClassification.NOT_PINNED

    clause = clauses[0]
    if clause.operator not in ("==", "==="):
        return PinClassification.NOT_PINNED
    if "*" in clause.version:
        # `pkg==1.*` parses with operator `==`, which is why the wildcard test
        # is on the version and not the operator (FR-008).
        return PinClassification.NOT_PINNED

    return PinClassification.HASH_PINNED if hashes else PinClassification.EXACTLY_PINNED


def parse(text: str) -> tuple[list[RequirementLine], str | None]:
    """Preprocess and parse. Returns (lines, not_inspectable_reason)."""
    lines: list[RequirementLine] = []

    for logical in _join_continuations(text):
        stripped = _strip_comment(logical).strip()
        if not stripped:
            continue

        lowered = stripped.lower()
        if lowered.startswith(_INCLUDE_PREFIXES):
            return lines, f"unresolved include: {stripped}"
        if lowered.startswith(_OPTION_PREFIXES):
            continue
        if _is_self_reference(stripped):
            continue

        hashes = _HASH_OPTION.findall(stripped)
        body = _HASH_OPTION.sub("", stripped).strip()
        for prefix in ("-e ", "--editable ", "-e=", "--editable="):
            if body.startswith(prefix):
                body = body[len(prefix) :].strip()
                break

        if _is_bare_url(body):
            lines.append(
                RequirementLine(
                    raw=stripped,
                    name=None,
                    hashes=hashes,
                    url=body,
                    pin=(PinClassification.EXACTLY_PINNED if _url_is_pinned(body) else PinClassification.NOT_PINNED),
                )
            )
            continue

        try:
            req = Requirement(body)
        except InvalidRequirement as exc:
            # A line that survived preprocessing but cannot be read. The tool
            # must not claim to have understood the file (FR-007).
            return lines, f"unparseable requirement {stripped!r}: {exc}"

        lines.append(
            RequirementLine(
                raw=stripped,
                name=req.name,
                specifier=str(req.specifier),
                hashes=hashes,
                url=req.url,
                pin=_classify_line(req, hashes),
            )
        )

    return lines, None


def classify(text: str) -> ClassificationReport:
    """Classify a requirements.txt by the strength of its weakest line."""
    lines, problem = parse(text)
    if problem is not None:
        return ClassificationReport(
            classification=FileClassification.NOT_INSPECTABLE,
            lines=lines,
            reason=problem,
        )

    if not lines:
        return ClassificationReport(
            classification=FileClassification.NO_REQUIREMENTS,
            reason="no requirement lines",
        )

    unpinned = [ln.raw for ln in lines if ln.pin is PinClassification.NOT_PINNED]
    unhashed = [ln.raw for ln in lines if ln.pin is PinClassification.EXACTLY_PINNED]

    if unpinned:
        result = FileClassification.UNPINNED
    elif unhashed:
        result = FileClassification.VERSION_PINNED
    else:
        result = FileClassification.HASH_PINNED

    return ClassificationReport(classification=result, lines=lines, unpinned=unpinned, unhashed=unhashed)
