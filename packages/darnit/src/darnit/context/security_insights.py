"""Read a security contact from an OpenSSF Security Insights file (#497).

What this module reads is evidence for the ``security_contact`` context key,
never the key's value. ``security_contact`` is a user-judgment key
(``auto_detect = false``), so the context sieve offers it as a candidate
labelled with the file it came from, and a person must confirm it before
anything consumes it (framework-design.md 7.4, 7.12).

Only the contact is read. A Security Insights policy link is a URL, while
``security.policy`` in project context names a file in the repository, so it
is not imported.

Schemas (https://github.com/ossf/security-insights-spec):

- v1.0.0: ``security-contacts`` is a list of ``{type, value, primary}`` with
  ``type`` one of ``email``, ``phone``, ``url``;
  ``vulnerability-reporting.email-contact`` is a single address.
- v2.x: ``project.vulnerability-reporting.contact`` is a contact object
  ``{name, email, primary, ...}``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Where the spec says to look: the repository root (v1 used the upper-case
# name) or the source forge directory. The first file present is read.
SECURITY_INSIGHTS_LOCATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("", ("security-insights.yml", "SECURITY-INSIGHTS.yml")),
    (".github", ("security-insights.yml",)),
    (".gitlab", ("security-insights.yml",)),
)

# v1 contact types that can receive a vulnerability report in writing.
_V1_CONTACT_TYPES = ("email", "url")


def find_security_insights(local_path: str | Path) -> str | None:
    """The repository-relative name of the first Security Insights file present.

    Names are matched exactly against the directory listing, so the recorded
    name is the file's real name on case-insensitive file systems too.
    """
    root = Path(local_path)
    for directory, names in SECURITY_INSIGHTS_LOCATIONS:
        folder = root / directory if directory else root
        try:
            present = {entry.name for entry in folder.iterdir() if entry.is_file()}
        except OSError:
            continue
        for name in names:
            if name in present:
                return f"{directory}/{name}" if directory else name
    return None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _v1_contact(data: dict[str, Any]) -> str | None:
    contacts = data.get("security-contacts")
    if isinstance(contacts, list):
        usable = [
            c for c in contacts if isinstance(c, dict) and c.get("type") in _V1_CONTACT_TYPES and _text(c.get("value"))
        ]
        usable.sort(key=lambda c: c.get("primary") is not True)
        if usable:
            return _text(usable[0]["value"])
    reporting = data.get("vulnerability-reporting")
    if isinstance(reporting, dict):
        return _text(reporting.get("email-contact"))
    return None


def _v2_contact(data: dict[str, Any]) -> str | None:
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    reporting = project.get("vulnerability-reporting")
    if not isinstance(reporting, dict):
        return None
    contact = reporting.get("contact")
    if not isinstance(contact, dict):
        return None
    # A contact with only a name gives no way to report; propose nothing.
    return _text(contact.get("email"))


def security_contact_from_insights(data: Any) -> str | None:
    """The security contact a parsed Security Insights document names, if any.

    A document with no ``header.schema-version``, or a major version other
    than 1 or 2, yields nothing: an unknown shape is not guessed at.
    """
    if not isinstance(data, dict):
        return None
    header = data.get("header")
    if not isinstance(header, dict):
        return None
    version = str(header.get("schema-version", "")).strip()
    if version.startswith("1."):
        return _v1_contact(data)
    if version.startswith("2."):
        return _v2_contact(data)
    return None


__all__ = [
    "SECURITY_INSIGHTS_LOCATIONS",
    "find_security_insights",
    "security_contact_from_insights",
]
