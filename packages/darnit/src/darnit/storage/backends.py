"""Pluggable storage backends for Darnit.

Darnit needs to store three kinds of data:
  1. Attestations — signed in-toto statements from audits
  2. Project metadata — .project.yaml contents when we can't write to the repo
  3. Research results — reproducibility check outputs keyed by repo + commit

This module defines a pluggable StorageBackend interface so teams can
swap in a real database (Archivista, SQL, etc.) without changing the
rest of the codebase.

Configuration (a ``[storage]`` mapping passed by the caller):
    [storage]
    backend = "file"          # file | archivista | memory
    archivista_url = "http://localhost:8082"  # only for archivista backend

Usage:
    from darnit.storage.backends import get_backend

    storage = get_backend(config)
    storage.store_attestation(repo_url, commit, attestation_json)
    storage.store_metadata(repo_url, metadata_dict)
    storage.store_research_result(repo_url, commit, result_dict)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("storage.backends")


# =============================================================================
# Data model
# =============================================================================

class StorageRecord:
    """A single stored record with its key and value."""

    def __init__(self, key: str, value: Any, record_type: str) -> None:
        self.key = key
        self.value = value
        self.record_type = record_type  # "attestation" | "metadata" | "research"

    def __repr__(self) -> str:
        return f"StorageRecord(type={self.record_type}, key={self.key})"


# =============================================================================
# Base interface
# =============================================================================

class StorageBackend:
    """Base class for storage backends.

    All three kinds of data (attestations, metadata, research results)
    go through the same three methods. The backend decides where and
    how to store them.
    """

    def store_attestation(
        self,
        repo_url: str,
        commit: str,
        attestation: dict[str, Any],
    ) -> str | None:
        """Store a signed attestation.

        Args:
            repo_url: The repository URL (e.g. https://github.com/org/repo)
            commit: The git commit SHA the attestation is for
            attestation: The attestation dict (in-toto format)

        Returns:
            A reference ID or URL where the attestation was stored, or None on failure.
        """
        raise NotImplementedError

    def retrieve_attestation(
        self,
        repo_url: str,
        commit: str,
    ) -> dict[str, Any] | None:
        """Retrieve a stored attestation.

        Args:
            repo_url: The repository URL
            commit: The git commit SHA

        Returns:
            The attestation dict, or None if not found.
        """
        raise NotImplementedError

    def store_metadata(
        self,
        repo_url: str,
        metadata: dict[str, Any],
    ) -> bool:
        """Store project metadata externally.

        Used when Darnit can't write .project.yaml back to the repo
        (e.g. auditing a repo without write access).

        Args:
            repo_url: The repository URL (used as the key)
            metadata: The project metadata dict (.project.yaml contents)

        Returns:
            True if stored successfully, False otherwise.
        """
        raise NotImplementedError

    def retrieve_metadata(
        self,
        repo_url: str,
    ) -> dict[str, Any] | None:
        """Retrieve stored project metadata.

        Args:
            repo_url: The repository URL

        Returns:
            The metadata dict, or None if not found.
        """
        raise NotImplementedError

    def store_research_result(
        self,
        repo_url: str,
        commit: str,
        result: dict[str, Any],
    ) -> bool:
        """Store a reproducibility research result.

        Args:
            repo_url: The repository URL
            commit: The git commit SHA the result is for
            result: The research result dict (reproducibility check outputs)

        Returns:
            True if stored successfully, False otherwise.
        """
        raise NotImplementedError

    def retrieve_research_result(
        self,
        repo_url: str,
        commit: str,
    ) -> dict[str, Any] | None:
        """Retrieve a stored research result.

        Args:
            repo_url: The repository URL
            commit: The git commit SHA

        Returns:
            The result dict, or None if not found.
        """
        raise NotImplementedError


# =============================================================================
# File backend — default, stores in .darnit/ directory
# =============================================================================

class FileBackend(StorageBackend):
    """Stores data as JSON files in a local directory.

    This is the default backend. It keeps the current behaviour of
    storing everything locally, but now in a structured directory
    rather than scattered files.

    Directory structure:
        .darnit/
          attestations/<repo_slug>/<commit>.json
          metadata/<repo_slug>.json
          research/<repo_slug>/<commit>.json
    """

    def __init__(self, base_dir: str = ".darnit") -> None:
        self.base_dir = Path(base_dir)

    def _repo_slug(self, repo_url: str) -> str:
        """Convert a repo URL to a safe directory name.

        Uses double underscore as separator to avoid collisions between
        org/repo and org_repo — e.g. github.com/org/repo becomes
        github.com__org__repo.
        """
        return repo_url.replace("https://", "").replace("http://", "").replace("/", "__")

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def store_attestation(self, repo_url: str, commit: str, attestation: dict[str, Any]) -> str | None:
        slug = self._repo_slug(repo_url)
        dir_path = self.base_dir / "attestations" / slug
        self._ensure_dir(dir_path)
        file_path = dir_path / f"{commit}.json"
        try:
            file_path.write_text(json.dumps(attestation, indent=2), encoding="utf-8")
            logger.info(f"Stored attestation for {repo_url}@{commit[:8]} at {file_path}")
            return str(file_path)
        except OSError as e:
            logger.error(f"Failed to store attestation: {e}")
            return None

    def retrieve_attestation(self, repo_url: str, commit: str) -> dict[str, Any] | None:
        slug = self._repo_slug(repo_url)
        file_path = self.base_dir / "attestations" / slug / f"{commit}.json"
        if not file_path.exists():
            return None
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to retrieve attestation: {e}")
            return None

    def store_metadata(self, repo_url: str, metadata: dict[str, Any]) -> bool:
        slug = self._repo_slug(repo_url)
        dir_path = self.base_dir / "metadata"
        self._ensure_dir(dir_path)
        file_path = dir_path / f"{slug}.json"
        try:
            file_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            logger.info(f"Stored metadata for {repo_url} at {file_path}")
            return True
        except OSError as e:
            logger.error(f"Failed to store metadata: {e}")
            return False

    def retrieve_metadata(self, repo_url: str) -> dict[str, Any] | None:
        slug = self._repo_slug(repo_url)
        file_path = self.base_dir / "metadata" / f"{slug}.json"
        if not file_path.exists():
            return None
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to retrieve metadata: {e}")
            return None

    def store_research_result(self, repo_url: str, commit: str, result: dict[str, Any]) -> bool:
        slug = self._repo_slug(repo_url)
        dir_path = self.base_dir / "research" / slug
        self._ensure_dir(dir_path)
        file_path = dir_path / f"{commit}.json"
        try:
            file_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            logger.info(f"Stored research result for {repo_url}@{commit[:8]} at {file_path}")
            return True
        except OSError as e:
            logger.error(f"Failed to store research result: {e}")
            return False

    def retrieve_research_result(self, repo_url: str, commit: str) -> dict[str, Any] | None:
        slug = self._repo_slug(repo_url)
        file_path = self.base_dir / "research" / slug / f"{commit}.json"
        if not file_path.exists():
            return None
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to retrieve research result: {e}")
            return None


# =============================================================================
# Archivista backend — stores attestations via Archivista HTTP API
# =============================================================================

class ArchivistaBackend(StorageBackend):
    """Stores attestations in an Archivista instance.

    Archivista is a graph and storage service for in-toto attestations.
    It exposes two simple HTTP endpoints:
      POST /upload  — upload an attestation (body = attestation JSON)
      GET /download/:gitoid — download by gitoid

    Metadata and research results fall back to the FileBackend since
    Archivista only handles in-toto attestations.

    Config:
        archivista_url = "http://localhost:8082"
    """

    def __init__(self, archivista_url: str = "http://localhost:8082", base_dir: str = ".darnit") -> None:
        self.archivista_url = archivista_url.rstrip("/")
        self._file_fallback = FileBackend(base_dir=base_dir)
        # Maps repo_url+commit -> gitoid for later retrieval
        self._gitoid_index: dict[str, str] = {}

    def store_attestation(self, repo_url: str, commit: str, attestation: dict[str, Any]) -> str | None:
        try:
            import urllib.request
            payload = json.dumps(attestation).encode("utf-8")
            req = urllib.request.Request(
                f"{self.archivista_url}/upload",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                gitoid = data.get("gitoid", "unknown")
                self._gitoid_index[f"{repo_url}@{commit}"] = gitoid
                logger.info(f"Stored attestation in Archivista for {repo_url}@{commit[:8]}, gitoid={gitoid}")
                return f"{self.archivista_url}/download/{gitoid}"
        except Exception as e:
            logger.error(f"Archivista upload failed: {e}, falling back to file storage")
            return self._file_fallback.store_attestation(repo_url, commit, attestation)

    def retrieve_attestation(self, repo_url: str, commit: str) -> dict[str, Any] | None:
        gitoid = self._gitoid_index.get(f"{repo_url}@{commit}")
        if gitoid:
            try:
                import urllib.request
                url = f"{self.archivista_url}/download/{gitoid}"
                with urllib.request.urlopen(url, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                logger.error(f"Archivista retrieval failed: {e}, falling back to file storage")
        return self._file_fallback.retrieve_attestation(repo_url, commit)

    def store_metadata(self, repo_url: str, metadata: dict[str, Any]) -> bool:
        # Archivista only handles attestations — metadata goes to file
        return self._file_fallback.store_metadata(repo_url, metadata)

    def retrieve_metadata(self, repo_url: str) -> dict[str, Any] | None:
        return self._file_fallback.retrieve_metadata(repo_url)

    def store_research_result(self, repo_url: str, commit: str, result: dict[str, Any]) -> bool:
        return self._file_fallback.store_research_result(repo_url, commit, result)

    def retrieve_research_result(self, repo_url: str, commit: str) -> dict[str, Any] | None:
        return self._file_fallback.retrieve_research_result(repo_url, commit)


# =============================================================================
# Memory backend — for testing only
# =============================================================================

class MemoryBackend(StorageBackend):
    """Stores everything in memory. For testing only — nothing persists."""

    def __init__(self) -> None:
        self._attestations: dict[str, dict[str, Any]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._research: dict[str, dict[str, Any]] = {}

    def _key(self, repo_url: str, commit: str | None = None) -> str:
        return f"{repo_url}@{commit}" if commit else repo_url

    def store_attestation(self, repo_url: str, commit: str, attestation: dict[str, Any]) -> str | None:
        self._attestations[self._key(repo_url, commit)] = attestation
        return f"memory://{self._key(repo_url, commit)}"

    def retrieve_attestation(self, repo_url: str, commit: str) -> dict[str, Any] | None:
        return self._attestations.get(self._key(repo_url, commit))

    def store_metadata(self, repo_url: str, metadata: dict[str, Any]) -> bool:
        self._metadata[repo_url] = metadata
        return True

    def retrieve_metadata(self, repo_url: str) -> dict[str, Any] | None:
        return self._metadata.get(repo_url)

    def store_research_result(self, repo_url: str, commit: str, result: dict[str, Any]) -> bool:
        self._research[self._key(repo_url, commit)] = result
        return True

    def retrieve_research_result(self, repo_url: str, commit: str) -> dict[str, Any] | None:
        return self._research.get(self._key(repo_url, commit))


# =============================================================================
# Factory
# =============================================================================

def get_backend(config: dict[str, Any] | None = None) -> StorageBackend:
    """Return the configured storage backend.

    Args:
        config: A ``[storage]`` mapping, e.g.:
                {"backend": "archivista", "archivista_url": "http://localhost:8082"}

    Returns:
        A StorageBackend instance ready to use.
    """
    if not config:
        return FileBackend()

    backend_name = config.get("backend", "file").lower()
    base_dir = config.get("base_dir", ".darnit")

    if backend_name == "file":
        return FileBackend(base_dir=base_dir)
    elif backend_name == "archivista":
        archivista_url = config.get("archivista_url", os.environ.get("ARCHIVISTA_URL", "http://localhost:8082"))
        return ArchivistaBackend(archivista_url=archivista_url, base_dir=base_dir)
    elif backend_name == "memory":
        return MemoryBackend()
    else:
        logger.warning(f"Unknown storage backend '{backend_name}', defaulting to file")
        return FileBackend(base_dir=base_dir)
