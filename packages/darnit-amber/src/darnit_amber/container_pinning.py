"""Classify how firmly a container build file pins its base images (issue #431).

This module takes text and returns a classification. It performs no file
discovery, constructs no ``HandlerResult``, and decides no verdict -- mapping a
classification to PASS or WARN belongs to the handler. Same boundary as
``requirements_pins`` from feature 037, for the same reason: the edge-case table
is worth testing as a pure function.

See specs/038-repro-false-pass/contracts/build-env-pinning.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class PinKind(str, Enum):
    """How firmly one ``FROM`` line identifies its image."""

    DIGEST = "digest"
    SCRATCH = "scratch"
    STAGE_REF = "stage_ref"
    TAG = "tag"
    INDETERMINATE = "indeterminate"


#: Kinds that do not weaken the build environment. A digest is immutable,
#: `scratch` is the empty image, and a stage reference is not an image at all.
_ACCEPTABLE: frozenset[PinKind] = frozenset({PinKind.DIGEST, PinKind.SCRATCH, PinKind.STAGE_REF})


class ContainerClassification(str, Enum):
    """The verdict about the file as a whole. The weakest reference governs."""

    PINNED = "pinned"
    UNPINNED = "unpinned"
    NO_IMAGES = "no_images"


@dataclass
class ImageReference:
    """One ``FROM`` line, after stage aliases are resolved."""

    raw: str
    image: str | None = None
    stage_name: str | None = None
    pin: PinKind = PinKind.INDETERMINATE


@dataclass
class ContainerReport:
    """What the classifier concluded and which references drove it."""

    classification: ContainerClassification
    references: list[ImageReference] = field(default_factory=list)
    unpinned: list[str] = field(default_factory=list)


_FROM = re.compile(r"^\s*FROM\s+(?P<rest>.+?)\s*$", re.IGNORECASE)
_AS_CLAUSE = re.compile(r"\s+AS\s+(?P<name>[A-Za-z0-9._-]+)\s*$", re.IGNORECASE)
_DIGEST = re.compile(r"@sha256:[0-9a-fA-F]{64}\b")
_VARIABLE = re.compile(r"\$\{?[A-Za-z_]")


def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0] if line.lstrip().startswith("#") else line


def _classify_reference(image: str, known_stages: set[str]) -> PinKind:
    if image.lower() in known_stages:
        # A multi-stage build refers back to an earlier stage by name. This is
        # not a registry image, and reporting it as unpinned produces a spurious
        # finding on every multi-stage Dockerfile -- including this repository's
        # own packaging/container/Dockerfile.
        return PinKind.STAGE_REF
    if image.lower() == "scratch":
        return PinKind.SCRATCH
    if _VARIABLE.search(image):
        # Built from an ARG. The tool cannot see what it resolves to, and
        # Principle II resolves doubt against the claim.
        return PinKind.INDETERMINATE
    if _DIGEST.search(image):
        return PinKind.DIGEST
    return PinKind.TAG


def parse(text: str) -> list[ImageReference]:
    """Parse ``FROM`` lines, classifying each against the stages defined above it.

    Docker resolves `FROM builder` to a stage only when `... AS builder`
    appeared on an earlier line. A line's own alias and any forward reference
    name a registry image, so counting them as stages would be a false PASS.
    """
    refs: list[ImageReference] = []
    known_stages: set[str] = set()

    for line in text.splitlines():
        clean = _strip_comment(line)
        match = _FROM.match(clean)
        if not match:
            continue
        rest = match.group("rest")

        stage_name = None
        alias = _AS_CLAUSE.search(rest)
        if alias:
            stage_name = alias.group("name")
            rest = rest[: alias.start()].strip()

        # `FROM --platform=... image` -- drop flags, keep the image.
        parts = [p for p in rest.split() if not p.startswith("--")]
        image = parts[0] if parts else ""
        refs.append(
            ImageReference(
                raw=line.strip(),
                image=image or None,
                stage_name=stage_name,
                pin=_classify_reference(image, known_stages),
            )
        )
        if stage_name:
            known_stages.add(stage_name.lower())

    return refs


def classify(text: str) -> ContainerReport:
    """Classify a container build file by its weakest base-image reference."""
    references = parse(text)
    if not references:
        return ContainerReport(classification=ContainerClassification.NO_IMAGES)

    unpinned = [r.image or r.raw for r in references if r.pin not in _ACCEPTABLE]
    return ContainerReport(
        classification=(ContainerClassification.UNPINNED if unpinned else ContainerClassification.PINNED),
        references=references,
        unpinned=unpinned,
    )
