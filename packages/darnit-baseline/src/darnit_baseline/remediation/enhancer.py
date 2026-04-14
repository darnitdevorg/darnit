"""LLM enhancement for complex remediation documents.

Provides an optional post-generation pass that enriches deterministically
generated files (ARCHITECTURE.md, threat model, security assessment) with
LLM-generated descriptions.  Enhancement is additive — it never removes
or restructures the deterministic content.

This module is only invoked when ``enhance_with_llm=True`` is passed to
``remediate_audit_findings``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from darnit.core.logging import get_logger

logger = get_logger("remediation.enhancer")

#: Templates eligible for LLM enhancement.  Maps output filename patterns
#: to the type of enhancement to apply.
LLM_ENHANCEABLE_FILES: dict[str, str] = {
    "ARCHITECTURE.md": "architecture",
    "THREAT_MODEL.md": "threat_model",
    "docs/threatmodel/SUMMARY.md": "threat_model",
    "SECURITY-ASSESSMENT.md": "security_assessment",
    "docs/SECURITY-ASSESSMENT.md": "security_assessment",
}


def is_enhanceable(file_path: str) -> bool:
    """Check if a generated file is eligible for LLM enhancement."""
    basename = os.path.basename(file_path)
    if basename in LLM_ENHANCEABLE_FILES:
        return True
    # Also check with directory prefix
    for pattern in LLM_ENHANCEABLE_FILES:
        if file_path.endswith(pattern):
            return True
    return False


def get_enhancement_type(file_path: str) -> str | None:
    """Get the enhancement type for a file path."""
    basename = os.path.basename(file_path)
    if basename in LLM_ENHANCEABLE_FILES:
        return LLM_ENHANCEABLE_FILES[basename]
    for pattern, etype in LLM_ENHANCEABLE_FILES.items():
        if file_path.endswith(pattern):
            return etype
    return None


def enhance_generated_file(
    file_path: str,
    local_path: str,
    file_type: str,
    *,
    llm_fn: object | None = None,
) -> str | None:
    """Enrich a deterministically generated file with LLM analysis.

    Reads the generated file and relevant source code, then uses an LLM
    to add meaningful descriptions while preserving the existing structure.

    Args:
        file_path: Absolute path to the generated file.
        local_path: Repository root path.
        file_type: Enhancement type (``"architecture"``, ``"threat_model"``,
            ``"security_assessment"``).
        llm_fn: Optional callable for LLM invocation.  If ``None``, attempts
            to use the framework's LLM evaluation support.  For testing,
            pass a mock callable.

    Returns:
        Enhanced file content as a string, or ``None`` if enhancement
        could not be performed (original file is left unchanged).
    """
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except OSError:
        logger.warning("Cannot read file for enhancement: %s", file_path)
        return None

    if file_type == "architecture":
        return _enhance_architecture(content, local_path, llm_fn=llm_fn)
    if file_type == "threat_model":
        return _enhance_threat_model(content, local_path, llm_fn=llm_fn)
    if file_type == "security_assessment":
        return _enhance_security_assessment(content, local_path, llm_fn=llm_fn)

    logger.debug("Unknown enhancement type: %s", file_type)
    return None


def _enhance_architecture(content: str, local_path: str, *, llm_fn: object | None = None) -> str | None:
    """Enhance ARCHITECTURE.md with component descriptions.

    Reads top-level module docstrings from source directories mentioned in
    the components table, then asks the LLM to add one-line descriptions.
    """
    # Collect source context: top-level __init__.py or main module docstrings
    source_context = _collect_source_docstrings(local_path, max_files=20)
    if not source_context:
        logger.debug("No source docstrings found for architecture enhancement")
        return None

    prompt = (
        "You are enhancing an ARCHITECTURE.md file for an open source project. "
        "The file already contains a components table with real directory paths. "
        "For each component listed, add a brief (1-2 sentence) description of "
        "what that component does based on the source code context below.\n\n"
        "IMPORTANT: Do NOT change the table structure. Only add descriptions "
        "in a new column or as text below the table. Do NOT remove any paths.\n\n"
        f"Current ARCHITECTURE.md:\n```\n{content}\n```\n\n"
        f"Source code context:\n```\n{source_context}\n```\n\n"
        "Return the enhanced ARCHITECTURE.md content."
    )

    if llm_fn is not None:
        try:
            result = llm_fn(prompt)
            if isinstance(result, str) and result.strip():
                return result
        except Exception as e:
            logger.warning("LLM enhancement failed: %s", e)
            return None
    else:
        # Try using the framework's LLM evaluation
        try:
            from darnit.sieve.builtin_handlers import _call_llm

            result = _call_llm(prompt)
            if isinstance(result, str) and result.strip():
                return result
        except Exception:
            logger.debug("No LLM available for enhancement")
            return None

    return None


def _enhance_threat_model(content: str, local_path: str, *, llm_fn: object | None = None) -> str | None:
    """Enhance threat model with refined analysis."""
    # Threat model enhancement is more complex — for now, return None
    # to indicate no enhancement available. The deterministic threat model
    # from the threat_model module is already substantial.
    logger.debug("Threat model enhancement not yet implemented")
    return None


def _enhance_security_assessment(content: str, local_path: str, *, llm_fn: object | None = None) -> str | None:
    """Enhance security assessment with project-specific checklist items."""
    logger.debug("Security assessment enhancement not yet implemented")
    return None


def _collect_source_docstrings(local_path: str, max_files: int = 20) -> str:
    """Collect module docstrings from source files for context."""
    docstrings: list[str] = []
    count = 0

    # Walk conventional source directories
    for source_dir in ("src", "pkg", "cmd", "packages", "lib", "internal"):
        dir_path = os.path.join(local_path, source_dir)
        if not os.path.isdir(dir_path):
            continue

        for root, _dirs, files in os.walk(dir_path):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                if fname.startswith("test_"):
                    continue
                if count >= max_files:
                    break

                fpath = os.path.join(root, fname)
                rel_path = os.path.relpath(fpath, local_path)
                try:
                    first_lines = Path(fpath).read_text(encoding="utf-8", errors="replace")[:500]
                except OSError:
                    continue

                # Extract module docstring (first triple-quoted string)
                docstring_match = re.match(
                    r'^(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')',
                    first_lines,
                    re.DOTALL,
                )
                if docstring_match:
                    doc = (docstring_match.group(1) or docstring_match.group(2) or "").strip()
                    if doc:
                        # Take first line only
                        first_line = doc.split("\n")[0].strip()
                        docstrings.append(f"- {rel_path}: {first_line}")
                        count += 1

            if count >= max_files:
                break

    return "\n".join(docstrings)
