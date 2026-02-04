#!/usr/bin/env python3
"""Hybrid documentation generator for darnit framework.

This script generates human-readable documentation from the authoritative
framework specification (openspec/specs/framework-design/spec.md).

Generation Strategy:
- Static content: Copied directly from spec (deterministic, always fresh)
- LLM markers: Content generated via LLM, cached by section hash
- Only regenerates LLM sections when source content changes

LLM Markers in Spec:
    <!-- llm:explain max_words=200 -->
    Explain when to use this feature...
    <!-- /llm:explain -->

    <!-- llm:example control_type=security -->
    Generate practical examples...
    <!-- /llm:example -->

Usage:
    python scripts/generate_docs.py [--force] [--no-llm] [--verbose]

    --force    Force regeneration of all LLM sections (ignore cache)
    --no-llm   Skip LLM generation, keep cached content
    --verbose  Show detailed progress

Output:
    docs/generated/ARCHITECTURE.md
    docs/generated/SCHEMA_REFERENCE.md
    docs/generated/USAGE_GUIDE.md
"""

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SPEC_PATH = PROJECT_ROOT / "openspec" / "specs" / "framework-design" / "spec.md"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "generated"
CACHE_DIR = PROJECT_ROOT / ".doc-cache"


@dataclass
class LLMMarker:
    """Represents an LLM marker in the spec."""

    marker_type: str  # "explain" or "example"
    params: dict[str, str]
    prompt_content: str
    start_pos: int
    end_pos: int
    section_hash: str


@dataclass
class Section:
    """A section of the spec document."""

    title: str
    level: int
    content: str
    llm_markers: list[LLMMarker]


def compute_hash(content: str) -> str:
    """Compute a short hash of content for cache keying."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def parse_llm_markers(content: str) -> list[LLMMarker]:
    """Extract LLM markers from content.

    Supports:
        <!-- llm:explain max_words=200 -->
        prompt text here
        <!-- /llm:explain -->

        <!-- llm:example control_type=security -->
        prompt text here
        <!-- /llm:example -->
    """
    markers = []

    # Pattern for LLM markers
    pattern = r"<!-- llm:(\w+)(.*?) -->(.*?)<!-- /llm:\1 -->"

    for match in re.finditer(pattern, content, re.DOTALL):
        marker_type = match.group(1)
        params_str = match.group(2).strip()
        prompt_content = match.group(3).strip()

        # Parse parameters (key=value pairs)
        params = {}
        if params_str:
            for param in params_str.split():
                if "=" in param:
                    key, value = param.split("=", 1)
                    params[key] = value

        # Compute hash of the prompt for cache keying
        section_hash = compute_hash(f"{marker_type}:{params_str}:{prompt_content}")

        markers.append(
            LLMMarker(
                marker_type=marker_type,
                params=params,
                prompt_content=prompt_content,
                start_pos=match.start(),
                end_pos=match.end(),
                section_hash=section_hash,
            )
        )

    return markers


def parse_spec(spec_path: Path) -> tuple[dict[str, Any], str]:
    """Parse the spec file into metadata and content.

    Returns:
        Tuple of (metadata dict, content string)
    """
    content = spec_path.read_text()

    # Extract front matter if present (between --- lines)
    metadata = {}
    if content.startswith("---"):
        end_idx = content.find("---", 3)
        if end_idx != -1:
            # Simple YAML-like parsing
            front_matter = content[3:end_idx].strip()
            for line in front_matter.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key.strip()] = value.strip()
            content = content[end_idx + 3 :].strip()

    return metadata, content


def load_cache(cache_dir: Path, section_hash: str) -> str | None:
    """Load cached LLM output if it exists.

    Args:
        cache_dir: Cache directory path
        section_hash: Hash identifying the section

    Returns:
        Cached content or None if not found
    """
    cache_file = cache_dir / f"{section_hash}.md"
    if cache_file.exists():
        return cache_file.read_text()
    return None


def save_cache(cache_dir: Path, section_hash: str, content: str) -> None:
    """Save LLM output to cache.

    Args:
        cache_dir: Cache directory path
        section_hash: Hash identifying the section
        content: Content to cache
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{section_hash}.md"
    cache_file.write_text(content)


def generate_llm_content(marker: LLMMarker, verbose: bool = False) -> str:
    """Generate content for an LLM marker.

    In a full implementation, this would call an LLM API.
    For now, we generate placeholder content.

    Args:
        marker: The LLM marker to process
        verbose: Show progress

    Returns:
        Generated content
    """
    # For now, generate descriptive placeholder content
    # In production, this would call Claude API or similar

    if marker.marker_type == "explain":
        max_words = marker.params.get("max_words", "150")
        return f"""*[This section provides an explanation of the feature described above.
The explanation is limited to approximately {max_words} words and covers
common use cases and best practices.]*

{marker.prompt_content}
"""

    elif marker.marker_type == "example":
        control_type = marker.params.get("control_type", "general")
        return f"""*[This section contains practical examples for {control_type}-related controls.]*

{marker.prompt_content}
"""

    return marker.prompt_content


def process_content_with_markers(
    content: str,
    cache_dir: Path,
    force_regenerate: bool = False,
    skip_llm: bool = False,
    verbose: bool = False,
) -> str:
    """Process content, replacing LLM markers with generated content.

    Args:
        content: Original content with LLM markers
        cache_dir: Cache directory for LLM outputs
        force_regenerate: Force regeneration of all LLM sections
        skip_llm: Skip LLM generation, keep markers or cached content
        verbose: Show progress

    Returns:
        Processed content with LLM markers replaced
    """
    markers = parse_llm_markers(content)

    if not markers:
        return content

    # Process markers in reverse order to preserve positions
    result = content
    for marker in reversed(markers):
        # Check cache
        cached = None if force_regenerate else load_cache(cache_dir, marker.section_hash)

        if cached:
            if verbose:
                print(f"  Cache hit: {marker.marker_type} ({marker.section_hash[:8]})")
            replacement = cached
        elif skip_llm:
            if verbose:
                print(f"  Skipping LLM: {marker.marker_type} ({marker.section_hash[:8]})")
            # Keep the marker as-is or use placeholder
            replacement = f"*[LLM content pending: {marker.marker_type}]*\n\n{marker.prompt_content}"
        else:
            if verbose:
                print(f"  Generating: {marker.marker_type} ({marker.section_hash[:8]})")
            replacement = generate_llm_content(marker, verbose)
            save_cache(cache_dir, marker.section_hash, replacement)

        # Replace the marker with generated content
        result = result[: marker.start_pos] + replacement + result[marker.end_pos :]

    return result


def extract_sections(content: str) -> list[Section]:
    """Extract sections from markdown content.

    Args:
        content: Markdown content

    Returns:
        List of Section objects
    """
    sections = []
    current_title = "Introduction"
    current_level = 1
    current_lines = []

    for line in content.split("\n"):
        # Check for header
        header_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if header_match:
            # Save previous section
            if current_lines:
                section_content = "\n".join(current_lines)
                sections.append(
                    Section(
                        title=current_title,
                        level=current_level,
                        content=section_content,
                        llm_markers=parse_llm_markers(section_content),
                    )
                )
                current_lines = []

            current_level = len(header_match.group(1))
            current_title = header_match.group(2)
        else:
            current_lines.append(line)

    # Save last section
    if current_lines:
        section_content = "\n".join(current_lines)
        sections.append(
            Section(
                title=current_title,
                level=current_level,
                content=section_content,
                llm_markers=parse_llm_markers(section_content),
            )
        )

    return sections


def generate_architecture_doc(spec_content: str, metadata: dict[str, Any]) -> str:
    """Generate ARCHITECTURE.md from spec.

    Args:
        spec_content: Processed spec content
        metadata: Spec metadata

    Returns:
        Generated architecture documentation
    """
    # Extract relevant sections for architecture doc
    sections = extract_sections(spec_content)

    doc = f"""# Darnit Framework Architecture

> Generated from framework specification
> Spec Version: {metadata.get('Version', 'Unknown')}

This document describes the architecture of the Darnit framework, including
the sieve orchestrator, plugin system, and TOML configuration schema.

---

"""

    # Include Overview and Architecture sections
    for section in sections:
        if section.title in [
            "Overview",
            "Architecture Diagram",
            "Sieve Orchestrator",
            "Plugin Protocol",
        ] or section.title.startswith("1.") or section.title.startswith("5.") or section.title.startswith("6."):
            doc += f"{'#' * section.level} {section.title}\n\n"
            doc += section.content.strip() + "\n\n"

    return doc


def generate_schema_reference(spec_content: str, metadata: dict[str, Any]) -> str:
    """Generate SCHEMA_REFERENCE.md from spec.

    Args:
        spec_content: Processed spec content
        metadata: Spec metadata

    Returns:
        Generated schema reference documentation
    """
    sections = extract_sections(spec_content)

    doc = f"""# Darnit TOML Schema Reference

> Generated from framework specification
> Spec Version: {metadata.get('Version', 'Unknown')}

This document provides a complete reference for the TOML configuration schema
used to define controls, passes, and remediations.

---

"""

    # Include TOML Schema and Pass Types sections
    for section in sections:
        if (
            "TOML" in section.title
            or "Schema" in section.title
            or "Pass" in section.title
            or "Remediation" in section.title
            or section.title.startswith("2.")
            or section.title.startswith("3.")
            or section.title.startswith("4.")
        ):
            doc += f"{'#' * section.level} {section.title}\n\n"
            doc += section.content.strip() + "\n\n"

    return doc


def generate_usage_guide(spec_content: str, metadata: dict[str, Any]) -> str:
    """Generate USAGE_GUIDE.md from spec.

    Args:
        spec_content: Processed spec content
        metadata: Spec metadata

    Returns:
        Generated usage guide
    """
    doc = f"""# Darnit Framework Usage Guide

> Generated from framework specification
> Spec Version: {metadata.get('Version', 'Unknown')}

This guide explains how to use the Darnit framework for compliance auditing.

---

## Quick Start

1. Install darnit and a compliance framework:
   ```bash
   pip install darnit darnit-baseline
   ```

2. Run an audit:
   ```bash
   darnit audit --level 1
   ```

3. View results in SARIF format:
   ```bash
   darnit audit --level 1 --format sarif > results.sarif
   ```

## Configuration

Create a `.baseline.toml` file in your repository to customize control behavior:

```toml
extends = "openssf-baseline"

[controls."OSPS-QA-04.01"]
status = "n/a"
reason = "Single-repo project without subprojects"
```

## Available Frameworks

The default framework is `openssf-baseline` implementing the OpenSSF Baseline
security controls. Custom frameworks can be registered via Python entry points.

## Output Formats

- **SARIF**: For GitHub Code Scanning integration
- **JSON**: For programmatic consumption
- **Markdown**: For human-readable reports

---

*For detailed schema information, see [SCHEMA_REFERENCE.md](SCHEMA_REFERENCE.md)*
*For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md)*
"""
    return doc


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate documentation from framework specification"
    )
    parser.add_argument(
        "--force", action="store_true", help="Force regeneration of LLM sections"
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="Skip LLM generation"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed progress"
    )
    args = parser.parse_args()

    # Verify spec exists
    if not SPEC_PATH.exists():
        print(f"Error: Spec not found at {SPEC_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading spec from: {SPEC_PATH}")

    # Parse spec
    metadata, content = parse_spec(SPEC_PATH)

    if args.verbose:
        print(f"Spec metadata: {metadata}")

    # Process LLM markers
    print("Processing content...")
    processed_content = process_content_with_markers(
        content,
        CACHE_DIR,
        force_regenerate=args.force,
        skip_llm=args.no_llm,
        verbose=args.verbose,
    )

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate documents
    print(f"Generating documentation to {OUTPUT_DIR}/")

    arch_doc = generate_architecture_doc(processed_content, metadata)
    arch_path = OUTPUT_DIR / "ARCHITECTURE.md"
    arch_path.write_text(arch_doc)
    print(f"  Written: {arch_path.name}")

    schema_doc = generate_schema_reference(processed_content, metadata)
    schema_path = OUTPUT_DIR / "SCHEMA_REFERENCE.md"
    schema_path.write_text(schema_doc)
    print(f"  Written: {schema_path.name}")

    usage_doc = generate_usage_guide(processed_content, metadata)
    usage_path = OUTPUT_DIR / "USAGE_GUIDE.md"
    usage_path.write_text(usage_doc)
    print(f"  Written: {usage_path.name}")

    print("\nDone!")


if __name__ == "__main__":
    main()
