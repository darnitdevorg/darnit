# Contributing to darnit

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please read and follow our Code of Conduct to maintain a welcoming environment for all contributors.

## Getting Started

### Prerequisites

- Git
- A GitHub account

### Setup

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/darnit.git
   cd darnit
   ```
3. Add the upstream remote:
   ```bash
   git remote add upstream https://github.com/kusari-oss/darnit.git
   ```

## Making Changes

### Branch Naming

Create a branch with a descriptive name:
- `feat/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring

### Commit Messages

Write clear, concise commit messages:
```
type: short description

Longer description if needed explaining the what and why.
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `ci`, `chore`

### Pull Request Process

1. Update your fork with the latest upstream changes:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```
2. Push your changes to your fork
3. Open a Pull Request against the `main` branch
4. Fill out the PR template with relevant details
5. Wait for review and address any feedback

## Development Guidelines

### Code Style

- Follow existing code patterns and conventions
- Write clear, self-documenting code
- Add comments only where necessary to explain complex logic

### Testing

- Write tests for new functionality
- Ensure all tests pass before submitting a PR
- Maintain or improve test coverage

### Documentation

- Update relevant documentation for any changes
- Document public APIs and interfaces
- Include examples where helpful

## Questions?

If you have questions, feel free to:
- Open a GitHub Issue
- Start a Discussion

Thank you for contributing!
