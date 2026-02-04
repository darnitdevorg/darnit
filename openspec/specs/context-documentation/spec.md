# context-documentation Specification

## Purpose
TBD - created by archiving change improve-context-docstring-examples. Update Purpose after archive.
## Requirements
### Requirement: Docstring Examples SHALL Show Practical Usage

Module docstring examples MUST demonstrate how to use the API results, not just how to print them.

#### Scenario: Developer reads context/__init__.py example

- **WHEN** a developer reads the module docstring example
- **THEN** the example shows how to access `result.is_high_confidence`, `result.value`, and `result.confidence`
- **AND** the example uses variable assignment rather than print statements
- **AND** comments explain the conditional logic

#### Scenario: Developer reads context/sieve.py example

- **WHEN** a developer reads the ContextSieve docstring example
- **THEN** the example shows checking confidence threshold
- **AND** the example uses comments to explain what would happen in each branch
- **AND** no print() calls appear in the example

