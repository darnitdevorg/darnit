"""Context detection sieve using progressive verification pattern.

This module implements a 4-phase progressive detection pipeline for
context values (maintainers, security contacts, etc.):

1. DETERMINISTIC: Check explicit sources (files, configs)
2. HEURISTIC: Pattern matching + signals (git history, manifests)
3. API: External API calls (GitHub collaborators)
4. COMBINE: Aggregate signals and calculate confidence

This follows the same sieve pattern used for control verification,
but applied to context detection. The goal is to auto-detect values
and show them to the user for confirmation, rather than showing
empty prompts.

Example:
    sieve = ContextSieve()
    result = sieve.detect("maintainers", "/path/to/repo", "owner", "repo")
    if result.confidence >= 0.9:
        # High confidence - can use directly
        pass
    else:
        # Lower confidence - show to user for confirmation
        print(f"Detected: {result.value} ({result.confidence:.0%} confidence)")
"""

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger

from .confidence import (
    ContextSignal,
    SignalSource,
    calculate_confidence,
)

logger = get_logger("context.sieve")


@dataclass
class ContextDetectionResult:
    """Result from context detection sieve.

    Attributes:
        key: The context key (e.g., "maintainers")
        value: The detected value(s)
        confidence: Combined confidence score (0.0-1.0)
        signals: All detection signals
        needs_confirmation: Whether user should confirm
        auto_detected: True if value was auto-detected (not from storage)
        reasoning: Human-readable explanation
    """

    key: str
    value: Any
    confidence: float
    signals: list[ContextSignal] = field(default_factory=list)
    needs_confirmation: bool = True
    auto_detected: bool = True
    reasoning: str = ""

    @property
    def is_high_confidence(self) -> bool:
        """Check if confidence is high enough to use without confirmation."""
        return self.confidence >= 0.9

    @property
    def is_usable(self) -> bool:
        """Check if there's a usable value."""
        if self.value is None:
            return False
        if isinstance(self.value, (list, dict, str)):
            return len(self.value) > 0
        return True


class ContextSieve:
    """Progressive context detection using sieve pattern.

    Runs detection phases in order:
    1. Deterministic (explicit files)
    2. Heuristic (patterns, git history)
    3. API (GitHub)
    4. Combine signals

    If a deterministic source provides high-confidence data,
    later phases may be skipped.
    """

    # Confidence threshold to skip further phases
    HIGH_CONFIDENCE_THRESHOLD = 0.9

    def __init__(self):
        """Initialize the context sieve."""
        # Registry of detection methods by context key
        self._detectors: dict[str, dict[str, Callable]] = {
            "maintainers": {
                "deterministic": self._detect_maintainers_deterministic,
                "heuristic": self._detect_maintainers_heuristic,
                "api": self._detect_maintainers_api,
            },
            "security_contact": {
                "deterministic": self._detect_security_contact_deterministic,
                "heuristic": self._detect_security_contact_heuristic,
            },
            "governance_model": {
                "deterministic": self._detect_governance_deterministic,
            },
        }

    def detect(
        self,
        key: str,
        local_path: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> ContextDetectionResult:
        """Run the sieve pipeline for a context key.

        Args:
            key: Context key to detect (e.g., "maintainers")
            local_path: Path to the repository
            owner: GitHub owner (optional, needed for API phase)
            repo: GitHub repo name (optional, needed for API phase)

        Returns:
            ContextDetectionResult with detected value and confidence
        """
        logger.debug(f"Starting context detection for '{key}'")
        signals: list[ContextSignal] = []

        detectors = self._detectors.get(key, {})
        if not detectors:
            logger.warning(f"No detectors registered for context key '{key}'")
            return ContextDetectionResult(
                key=key,
                value=None,
                confidence=0.0,
                signals=[],
                needs_confirmation=True,
                reasoning=f"No detection methods available for '{key}'",
            )

        # Phase 1: Deterministic
        if "deterministic" in detectors:
            try:
                deterministic_signals = detectors["deterministic"](local_path)
                signals.extend(deterministic_signals)
                logger.debug(f"Deterministic phase: {len(deterministic_signals)} signals")

                # Check if we have high-confidence result
                if deterministic_signals:
                    combined = calculate_confidence(deterministic_signals)
                    if combined.confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
                        logger.debug(
                            f"High-confidence deterministic result: {combined.confidence:.0%}"
                        )
                        return ContextDetectionResult(
                            key=key,
                            value=combined.value,
                            confidence=combined.confidence,
                            signals=deterministic_signals,
                            needs_confirmation=False,
                            reasoning=combined.reasoning,
                        )
            except Exception as e:
                logger.warning(f"Deterministic detection failed for '{key}': {e}")

        # Phase 2: Heuristic
        if "heuristic" in detectors:
            try:
                heuristic_signals = detectors["heuristic"](local_path)
                signals.extend(heuristic_signals)
                logger.debug(f"Heuristic phase: {len(heuristic_signals)} signals")
            except Exception as e:
                logger.warning(f"Heuristic detection failed for '{key}': {e}")

        # Phase 3: API (requires owner/repo)
        if "api" in detectors and owner and repo:
            try:
                api_signals = detectors["api"](local_path, owner, repo)
                signals.extend(api_signals)
                logger.debug(f"API phase: {len(api_signals)} signals")
            except Exception as e:
                logger.warning(f"API detection failed for '{key}': {e}")

        # Phase 4: Combine all signals
        if not signals:
            return ContextDetectionResult(
                key=key,
                value=None,
                confidence=0.0,
                signals=[],
                needs_confirmation=True,
                reasoning="No detection signals found",
            )

        combined = calculate_confidence(signals)

        return ContextDetectionResult(
            key=key,
            value=combined.value,
            confidence=combined.confidence,
            signals=signals,
            needs_confirmation=combined.confidence < self.HIGH_CONFIDENCE_THRESHOLD,
            reasoning=combined.reasoning,
        )

    # =========================================================================
    # Maintainers Detection
    # =========================================================================

    def _detect_maintainers_deterministic(self, local_path: str) -> list[ContextSignal]:
        """Detect maintainers from explicit files.

        Sources:
        - MAINTAINERS.md / MAINTAINERS
        - CODEOWNERS
        """
        signals = []
        path = Path(local_path)

        # Check MAINTAINERS.md or MAINTAINERS
        for filename in ["MAINTAINERS.md", "MAINTAINERS", "maintainers.md"]:
            filepath = path / filename
            if filepath.exists():
                try:
                    content = filepath.read_text()
                    maintainers = self._parse_maintainers_file(content)
                    if maintainers:
                        signals.append(ContextSignal(
                            source=SignalSource.EXPLICIT_FILE,
                            value=maintainers,
                            raw_confidence=0.95,
                            method=f"Parsed {filename}",
                            evidence={"file": filename, "count": len(maintainers)},
                        ))
                        logger.debug(f"Found {len(maintainers)} maintainers in {filename}")
                except Exception as e:
                    logger.debug(f"Error reading {filename}: {e}")

        # Check CODEOWNERS
        for codeowners_path in [".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"]:
            filepath = path / codeowners_path
            if filepath.exists():
                try:
                    content = filepath.read_text()
                    owners = self._parse_codeowners(content)
                    if owners:
                        signals.append(ContextSignal(
                            source=SignalSource.EXPLICIT_FILE,
                            value=owners,
                            raw_confidence=0.85,  # Slightly lower - CODEOWNERS may have specific paths
                            method=f"Parsed {codeowners_path}",
                            evidence={"file": codeowners_path, "count": len(owners)},
                        ))
                        logger.debug(f"Found {len(owners)} owners in {codeowners_path}")
                except Exception as e:
                    logger.debug(f"Error reading {codeowners_path}: {e}")

        return signals

    def _detect_maintainers_heuristic(self, local_path: str) -> list[ContextSignal]:
        """Detect maintainers from heuristic sources.

        Sources:
        - package.json author/contributors
        - pyproject.toml authors
        - Git commit history (top contributors)
        """
        signals = []
        path = Path(local_path)

        # Check package.json
        package_json = path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                authors = []

                # Get author
                author = data.get("author")
                if author:
                    if isinstance(author, str):
                        # Parse "Name <email>" format
                        match = re.match(r"([^<]+)", author)
                        if match:
                            authors.append(match.group(1).strip())
                    elif isinstance(author, dict):
                        if author.get("name"):
                            authors.append(author["name"])

                # Get contributors
                contributors = data.get("contributors", [])
                for contrib in contributors:
                    if isinstance(contrib, str):
                        match = re.match(r"([^<]+)", contrib)
                        if match:
                            authors.append(match.group(1).strip())
                    elif isinstance(contrib, dict):
                        if contrib.get("name"):
                            authors.append(contrib["name"])

                if authors:
                    signals.append(ContextSignal(
                        source=SignalSource.PROJECT_MANIFEST,
                        value=authors,
                        raw_confidence=0.75,
                        method="Parsed package.json author/contributors",
                        evidence={"file": "package.json", "count": len(authors)},
                    ))
            except Exception as e:
                logger.debug(f"Error parsing package.json: {e}")

        # Check pyproject.toml
        pyproject = path / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib
                except ImportError:
                    tomllib = None

            if tomllib:
                try:
                    data = tomllib.loads(pyproject.read_text())
                    authors = []

                    # Get authors from [project] section
                    project = data.get("project", {})
                    for author in project.get("authors", []):
                        if isinstance(author, dict) and author.get("name"):
                            authors.append(author["name"])
                        elif isinstance(author, str):
                            authors.append(author)

                    # Get maintainers from [project] section
                    for maintainer in project.get("maintainers", []):
                        if isinstance(maintainer, dict) and maintainer.get("name"):
                            authors.append(maintainer["name"])
                        elif isinstance(maintainer, str):
                            authors.append(maintainer)

                    if authors:
                        signals.append(ContextSignal(
                            source=SignalSource.PROJECT_MANIFEST,
                            value=list(set(authors)),  # Dedupe
                            raw_confidence=0.75,
                            method="Parsed pyproject.toml authors/maintainers",
                            evidence={"file": "pyproject.toml", "count": len(authors)},
                        ))
                except Exception as e:
                    logger.debug(f"Error parsing pyproject.toml: {e}")

        # Get top contributors from git history
        try:
            contributors = self._get_git_contributors(local_path, limit=5)
            if contributors:
                signals.append(ContextSignal(
                    source=SignalSource.GIT_HISTORY,
                    value=contributors,
                    raw_confidence=0.65,
                    method="Top contributors from git log",
                    evidence={"count": len(contributors)},
                ))
        except Exception as e:
            logger.debug(f"Error getting git contributors: {e}")

        return signals

    def _detect_maintainers_api(
        self,
        local_path: str,
        owner: str,
        repo: str,
    ) -> list[ContextSignal]:
        """Detect maintainers from GitHub API.

        Sources:
        - Repository collaborators with admin/maintain permissions
        """
        signals = []

        try:
            result = subprocess.run(
                [
                    "gh", "api", f"/repos/{owner}/{repo}/collaborators",
                    "--jq",
                    '[.[] | select(.permissions.admin == true or .permissions.maintain == true) | .login] | unique',
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                maintainers = json.loads(result.stdout.strip())
                if maintainers:
                    # Format as @username
                    formatted = [f"@{m}" for m in maintainers]
                    signals.append(ContextSignal(
                        source=SignalSource.GITHUB_API,
                        value=formatted,
                        raw_confidence=0.7,
                        method="GitHub collaborators API (admin/maintain permissions)",
                        evidence={
                            "api": f"/repos/{owner}/{repo}/collaborators",
                            "count": len(formatted),
                        },
                    ))
        except subprocess.TimeoutExpired:
            logger.warning("GitHub API timed out")
        except (subprocess.SubprocessError, json.JSONDecodeError) as e:
            logger.debug(f"GitHub API call failed: {e}")

        return signals

    # =========================================================================
    # Security Contact Detection
    # =========================================================================

    def _detect_security_contact_deterministic(self, local_path: str) -> list[ContextSignal]:
        """Detect security contact from SECURITY.md."""
        signals = []
        path = Path(local_path)

        for filename in ["SECURITY.md", "security.md", ".github/SECURITY.md"]:
            filepath = path / filename
            if filepath.exists():
                try:
                    content = filepath.read_text()
                    contact = self._parse_security_contact(content)
                    if contact:
                        signals.append(ContextSignal(
                            source=SignalSource.EXPLICIT_FILE,
                            value=contact,
                            raw_confidence=0.9,
                            method=f"Parsed {filename}",
                            evidence={"file": filename},
                        ))
                except Exception as e:
                    logger.debug(f"Error reading {filename}: {e}")

        return signals

    def _detect_security_contact_heuristic(self, local_path: str) -> list[ContextSignal]:
        """Detect security contact from README or other files."""
        signals = []
        path = Path(local_path)

        # Check README for security section
        for filename in ["README.md", "README", "readme.md"]:
            filepath = path / filename
            if filepath.exists():
                try:
                    content = filepath.read_text()
                    # Look for security section
                    security_section = re.search(
                        r"(?:^|\n)#+\s*Security[^\n]*\n([\s\S]*?)(?=\n#+|\Z)",
                        content,
                        re.IGNORECASE,
                    )
                    if security_section:
                        section_content = security_section.group(1)
                        contact = self._parse_security_contact(section_content)
                        if contact:
                            signals.append(ContextSignal(
                                source=SignalSource.PATTERN_MATCH,
                                value=contact,
                                raw_confidence=0.6,
                                method=f"Security section in {filename}",
                                evidence={"file": filename},
                            ))
                except Exception as e:
                    logger.debug(f"Error reading {filename}: {e}")

        return signals

    # =========================================================================
    # Governance Model Detection
    # =========================================================================

    def _detect_governance_deterministic(self, local_path: str) -> list[ContextSignal]:
        """Detect governance model from GOVERNANCE.md."""
        signals = []
        path = Path(local_path)

        for filename in ["GOVERNANCE.md", "governance.md"]:
            filepath = path / filename
            if filepath.exists():
                try:
                    content = filepath.read_text()
                    model = self._parse_governance_model(content)
                    if model:
                        signals.append(ContextSignal(
                            source=SignalSource.EXPLICIT_FILE,
                            value=model,
                            raw_confidence=0.9,
                            method=f"Detected from {filename}",
                            evidence={"file": filename},
                        ))
                except Exception as e:
                    logger.debug(f"Error reading {filename}: {e}")

        return signals

    # =========================================================================
    # Parsing Helpers
    # =========================================================================

    def _parse_maintainers_file(self, content: str) -> list[str]:
        """Parse maintainers from MAINTAINERS.md content.

        Looks for:
        - @username mentions
        - GitHub usernames in lists
        - Email addresses with names
        """
        maintainers = []

        # Pattern for @username
        at_mentions = re.findall(r"@([a-zA-Z0-9][-a-zA-Z0-9]*)", content)
        maintainers.extend([f"@{m}" for m in at_mentions])

        # Pattern for "Name (email)" or "Name <email>"
        name_email = re.findall(
            r"[-*]\s*([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s*[(<]",
            content,
        )
        maintainers.extend(name_email)

        # Dedupe while preserving order
        seen = set()
        unique = []
        for m in maintainers:
            m_lower = m.lower().lstrip("@")
            if m_lower not in seen:
                seen.add(m_lower)
                unique.append(m)

        return unique

    def _parse_codeowners(self, content: str) -> list[str]:
        """Parse owners from CODEOWNERS file.

        Returns unique owners from all rules.
        """
        owners = set()

        for line in content.split("\n"):
            # Skip comments and empty lines
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Split path from owners
            parts = line.split()
            if len(parts) >= 2:
                # All parts after the first are owners
                for owner in parts[1:]:
                    if owner.startswith("@"):
                        owners.add(owner)

        return sorted(owners)

    def _parse_security_contact(self, content: str) -> str | None:
        """Parse security contact from content.

        Looks for:
        - Email addresses (especially security@...)
        - Mailto links
        - "Report to" patterns
        """
        # Pattern for security-related emails
        security_emails = re.findall(
            r"security[@][-a-zA-Z0-9.]+\.[a-zA-Z]{2,}",
            content,
            re.IGNORECASE,
        )
        if security_emails:
            return security_emails[0]

        # Pattern for any email after "report" or "contact"
        report_emails = re.findall(
            r"(?:report|contact|email|notify)[^@]*?([-a-zA-Z0-9.]+@[-a-zA-Z0-9.]+\.[a-zA-Z]{2,})",
            content,
            re.IGNORECASE,
        )
        if report_emails:
            return report_emails[0]

        # Any email address
        any_emails = re.findall(
            r"[-a-zA-Z0-9.]+@[-a-zA-Z0-9.]+\.[a-zA-Z]{2,}",
            content,
        )
        if any_emails:
            return any_emails[0]

        return None

    def _parse_governance_model(self, content: str) -> str | None:
        """Detect governance model type from GOVERNANCE.md content."""
        content_lower = content.lower()

        # Check for common governance patterns
        if "bdfl" in content_lower or "benevolent dictator" in content_lower:
            return "bdfl"
        elif "steering committee" in content_lower or "technical committee" in content_lower:
            return "committee"
        elif "meritocracy" in content_lower or "meritocratic" in content_lower:
            return "meritocracy"
        elif "consensus" in content_lower:
            return "consensus"
        elif "founder" in content_lower and "lead" in content_lower:
            return "founder-led"

        return "documented"  # Has governance doc but unclear model

    def _get_git_contributors(self, local_path: str, limit: int = 5) -> list[str]:
        """Get top contributors from git history."""
        try:
            # Get top contributors by commit count
            result = subprocess.run(
                [
                    "git", "shortlog", "-sne", "--no-merges", "HEAD",
                ],
                cwd=local_path,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return []

            contributors = []
            for line in result.stdout.strip().split("\n")[:limit]:
                if not line.strip():
                    continue
                # Format: "   123\tName <email>"
                match = re.match(r"\s*\d+\s+([^<]+)", line)
                if match:
                    name = match.group(1).strip()
                    if name and name not in ["dependabot[bot]", "github-actions[bot]"]:
                        contributors.append(name)

            return contributors
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            return []


# Singleton instance
_sieve_instance: ContextSieve | None = None


def get_context_sieve() -> ContextSieve:
    """Get the singleton context sieve instance."""
    global _sieve_instance
    if _sieve_instance is None:
        _sieve_instance = ContextSieve()
    return _sieve_instance


__all__ = [
    "ContextSieve",
    "ContextDetectionResult",
    "get_context_sieve",
]
