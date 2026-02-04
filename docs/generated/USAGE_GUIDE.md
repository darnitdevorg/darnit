# Darnit Framework Usage Guide

> Generated from framework specification
> Spec Version: Unknown

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
