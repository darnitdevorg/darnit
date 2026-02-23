#!/usr/bin/env python3
"""Extract inline template content from a framework TOML to external .tmpl files.

Reads a TOML file, finds all [templates.*] sections with inline ``content``,
writes each to a ``templates/<name>.tmpl`` file (relative to the TOML), and
rewrites the TOML entry to use ``file = "templates/<name>.tmpl"`` instead.

Usage:
    python scripts/extract_templates.py [path/to/framework.toml]

Defaults to packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def extract_templates(toml_path: str) -> None:
    toml_file = Path(toml_path).resolve()
    if not toml_file.exists():
        print(f"Error: {toml_file} not found")
        sys.exit(1)

    templates_dir = toml_file.parent / "templates"
    templates_dir.mkdir(exist_ok=True)

    content = toml_file.read_text(encoding="utf-8")

    # Pattern: match [templates.NAME] sections with a content = """...""" block.
    # We process line-by-line to handle multi-line strings correctly.
    lines = content.split("\n")
    output_lines: list[str] = []
    extracted = 0
    skipped = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect [templates.NAME] section header
        section_match = re.match(r'^\[templates\.(\w+)\]', line)
        if not section_match:
            output_lines.append(line)
            i += 1
            continue

        template_name = section_match.group(1)
        output_lines.append(line)
        i += 1

        # Collect all lines in this section until we find content = """ or next section
        section_lines: list[str] = []
        content_start = -1
        content_end = -1
        content_value_lines: list[str] = []
        in_content = False

        j = i
        while j < len(lines):
            sline = lines[j]

            # Next section or end of file
            if re.match(r'^\[', sline) and not in_content:
                break

            if not in_content:
                # Check for content = """
                if re.match(r'^content\s*=\s*"""', sline):
                    in_content = True
                    content_start = len(section_lines)
                    # Check if opening and closing on same line (unlikely for templates)
                    rest = sline.split('"""', 2)
                    if len(rest) >= 3:
                        # content = """...""" on one line
                        content_value_lines.append(rest[1])
                        content_end = len(section_lines)
                        in_content = False
                    else:
                        # Multi-line: content after opening """
                        after_open = sline.split('"""', 1)[1]
                        if after_open:
                            content_value_lines.append(after_open)
                    section_lines.append(sline)
                    j += 1
                    continue
                else:
                    section_lines.append(sline)
                    j += 1
                    continue
            else:
                # Inside content = """..."""
                if '"""' in sline:
                    # Closing """
                    before_close = sline.split('"""', 1)[0]
                    if before_close:
                        content_value_lines.append(before_close)
                    content_end = len(section_lines)
                    in_content = False
                    section_lines.append(sline)
                    j += 1
                    continue
                else:
                    content_value_lines.append(sline)
                    section_lines.append(sline)
                    j += 1
                    continue

        if content_start == -1:
            # No inline content found — might already use file= or be empty
            output_lines.extend(section_lines)
            skipped += 1
            i = j
            continue

        # Write template content to .tmpl file
        template_content = "\n".join(content_value_lines)
        # Strip leading/trailing newlines that TOML triple-quotes add
        if template_content.startswith("\n"):
            template_content = template_content[1:]
        if template_content.endswith("\n"):
            template_content = template_content[:-1]

        tmpl_file = templates_dir / f"{template_name}.tmpl"
        tmpl_file.write_text(template_content, encoding="utf-8")

        # Replace content lines with file reference in output
        # Keep non-content section lines (description, etc.)
        for k, sline in enumerate(section_lines):
            if k < content_start:
                output_lines.append(sline)
            elif k == content_start:
                output_lines.append(f'file = "templates/{template_name}.tmpl"')
            elif k <= content_end:
                continue  # Skip content lines
            else:
                output_lines.append(sline)

        extracted += 1
        i = j

    # Write rewritten TOML
    new_content = "\n".join(output_lines)
    toml_file.write_text(new_content, encoding="utf-8")

    print(f"Extracted {extracted} templates to {templates_dir}/")
    if skipped:
        print(f"Skipped {skipped} templates (no inline content)")
    print(f"Rewrote {toml_file}")


if __name__ == "__main__":
    default = "packages/darnit-baseline/openssf-baseline.toml"
    path = sys.argv[1] if len(sys.argv) > 1 else default
    extract_templates(path)
