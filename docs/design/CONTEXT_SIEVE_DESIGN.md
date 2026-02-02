# Design: Context Sieve - Progressive Context Detection

## Overview

The **Context Sieve** is a progressive detection system for automatically discovering project context (maintainers, security contacts, governance model) from multiple sources with confidence scoring. It follows the "sieve" pattern: cheap/fast checks first, expensive checks last, stopping when confidence is sufficient.

## Problem Statement

Before the Context Sieve, the remediation system had several issues:

1. **No auto-detection**: Missing context immediately prompted users with generic messages
2. **Single source**: Only checked `.project.yaml` or GitHub API
3. **No confidence scoring**: All sources treated equally regardless of reliability
4. **Duplicated logic**: Each remediation action had its own prompt/detection code

## Solution: Progressive Detection Pipeline

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CONTEXT SIEVE PIPELINE                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Phase 1: DETERMINISTIC (High Confidence)                                    │
│  ├─ MAINTAINERS.md file parsing                                              │
│  ├─ CODEOWNERS file parsing                                                  │
│  ├─ SECURITY.md contact extraction                                           │
│  └─ GOVERNANCE.md model detection                                            │
│                     │                                                        │
│            confidence >= 0.9? ──────► DONE (use detected value)              │
│                     │ NO                                                     │
│                     ▼                                                        │
│  Phase 2: HEURISTIC (Medium Confidence)                                      │
│  ├─ package.json author/contributors                                         │
│  ├─ pyproject.toml authors                                                   │
│  ├─ Git commit history (top contributors)                                    │
│  └─ README.md author mentions                                                │
│                     │                                                        │
│            confidence >= 0.7? ──────► DONE (use detected value)              │
│                     │ NO                                                     │
│                     ▼                                                        │
│  Phase 3: API (Lower Confidence)                                             │
│  ├─ GitHub collaborators with admin/maintain access                          │
│  ├─ GitHub security advisories contact                                       │
│  └─ GitHub org membership patterns                                           │
│                     │                                                        │
│            confidence >= 0.5? ──────► DONE (use detected value)              │
│                     │ NO                                                     │
│                     ▼                                                        │
│  Phase 4: COMBINE SIGNALS                                                    │
│  ├─ Aggregate all signals from phases 1-3                                    │
│  ├─ Calculate combined confidence with agreement boost                       │
│  └─ Return best value with full provenance                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Architecture

### Module Structure

```
packages/darnit/src/darnit/context/
├── __init__.py          # Public exports
├── confidence.py        # Confidence scoring from multiple signals
└── sieve.py             # Progressive detection pipeline
```

### Key Components

#### 1. Signal Sources (`confidence.py`)

```python
class SignalSource(str, Enum):
    """Source of a context signal, ordered by reliability."""
    USER_CONFIRMED = "user_confirmed"     # User explicitly confirmed (weight: 1.0)
    EXPLICIT_FILE = "explicit_file"       # MAINTAINERS.md, CODEOWNERS (weight: 0.9)
    PROJECT_MANIFEST = "project_manifest" # package.json, pyproject.toml (weight: 0.8)
    GITHUB_API = "github_api"             # Collaborators API (weight: 0.7)
    GIT_HISTORY = "git_history"           # Top contributors (weight: 0.6)
    PATTERN_MATCH = "pattern_match"       # README mentions (weight: 0.5)
```

#### 2. Context Signal (`confidence.py`)

```python
@dataclass
class ContextSignal:
    """A single signal contributing to context detection."""
    source: SignalSource
    value: Any                    # The detected value
    raw_confidence: float         # Detection confidence (0.0-1.0)
    details: Optional[str] = None # How it was detected
```

#### 3. Confidence Calculation (`confidence.py`)

```python
def calculate_confidence(signals: List[ContextSignal]) -> CombinedConfidence:
    """Calculate combined confidence from multiple signals.

    Algorithm:
    1. Weight each signal by source reliability
    2. Calculate agreement factor (do signals agree?)
    3. Apply boost for agreement, penalty for conflict
    4. Return weighted combination with provenance
    """
```

#### 4. Context Sieve (`sieve.py`)

```python
class ContextSieve:
    """Progressive context detection using sieve pattern."""

    def detect(self, key: str, local_path: str,
               owner: Optional[str], repo: Optional[str]) -> ContextDetectionResult:
        """Run sieve pipeline for a context key.

        Phases:
        1. Deterministic: Check explicit files
        2. Heuristic: Check manifests, git history
        3. API: Check GitHub API (if owner/repo provided)
        4. Combine: Aggregate signals and return best result
        """
```

### Detection Result

```python
@dataclass
class ContextDetectionResult:
    """Result of context detection through the sieve."""
    key: str                              # Context key (e.g., "maintainers")
    value: Optional[Any] = None           # Detected value
    confidence: float = 0.0               # Combined confidence (0.0-1.0)
    signals: List[ContextSignal] = field(default_factory=list)
    needs_confirmation: bool = True       # Should user confirm?

    @property
    def is_usable(self) -> bool:
        """Value is usable (non-empty) regardless of confidence."""
        if self.value is None:
            return False
        if isinstance(self.value, (list, str)) and len(self.value) == 0:
            return False
        return True

    @property
    def is_high_confidence(self) -> bool:
        """Confidence is high enough to use without confirmation."""
        return self.confidence >= 0.9
```

## Supported Context Keys

| Key | Deterministic Sources | Heuristic Sources | API Sources |
|-----|----------------------|-------------------|-------------|
| `maintainers` | MAINTAINERS.md, CODEOWNERS | package.json authors, pyproject.toml authors, git top contributors | GitHub collaborators (admin/maintain) |
| `security_contact` | SECURITY.md email extraction | README security section | GitHub security policy |
| `governance_model` | GOVERNANCE.md keywords | README governance section | - |

## Confidence Scoring

### Source Weights

| Source | Weight | Rationale |
|--------|--------|-----------|
| `USER_CONFIRMED` | 1.0 | User explicitly confirmed, always trusted |
| `EXPLICIT_FILE` | 0.9 | Dedicated files (MAINTAINERS.md) are authoritative |
| `PROJECT_MANIFEST` | 0.8 | Package files are usually accurate |
| `GITHUB_API` | 0.7 | API data may include inactive contributors |
| `GIT_HISTORY` | 0.6 | Commit count doesn't equal maintainership |
| `PATTERN_MATCH` | 0.5 | Heuristic matching, may have false positives |

### Agreement Calculation

```python
def _calculate_agreement(signals: List[ContextSignal]) -> float:
    """Calculate how much signals agree with each other.

    Returns:
        1.0: All signals agree (same values)
        0.5: Partial overlap
        0.0: Complete disagreement
    """
```

### Confidence Formula

```
final_confidence = weighted_avg * agreement_factor * boost
```

Where:
- `weighted_avg`: Average of (signal_confidence × source_weight)
- `agreement_factor`: How much signals agree (0.0-1.0)
- `boost`: 1.2 if multiple signals agree, 1.0 otherwise

## Integration Points

### 1. Context Validator Integration

The context validator uses the sieve when context is missing:

```python
# packages/darnit/src/darnit/remediation/context_validator.py

def check_context_requirements(
    requirements: List[ContextRequirement],
    local_path: str,
    owner: Optional[str] = None,  # Enables API detection
    repo: Optional[str] = None,   # Enables API detection
) -> ContextCheckResult:
    """Check context requirements with sieve auto-detection."""

    for req in requirements:
        # First check storage
        context_value = get_context_value(local_path, req.key, "governance")

        # If missing, try sieve auto-detection
        if context_value is None:
            detected = _try_sieve_detection(req.key, local_path, owner, repo)
            if detected:
                result.auto_detected[req.key] = detected.value
```

### 2. Orchestrator Integration

The orchestrator passes owner/repo to enable API detection:

```python
# packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py

check_result = check_context_requirements(
    requirements=context_requirements,
    local_path=local_path,
    framework=framework,
    owner=owner,  # Pass for sieve auto-detection
    repo=repo,    # Pass for sieve auto-detection
)
```

### 3. Remediation Actions

Actions trust the orchestrator has validated context:

```python
# packages/darnit-baseline/src/darnit_baseline/remediation/actions.py

def create_codeowners(
    local_path: str,
    maintainers: Optional[List[str]] = None,  # Pre-validated by orchestrator
    ...
) -> str:
    # No duplicate detection logic - orchestrator handles it
    if not maintainers:
        return "Error: maintainers required"

    # Use validated maintainers directly
    content = f"* {' '.join(maintainers)}"
```

## User-Facing Behavior

### Before Context Sieve

```
❌ Missing context: maintainers
Please run: confirm_project_context(maintainers=["@user1", "@user2"])
```

### After Context Sieve

```
🔍 Auto-detected maintainers (confidence: 85%):
   - @alice (from CODEOWNERS)
   - @bob (from package.json author)

Confidence below 90% threshold. Please confirm or correct:
   confirm_project_context(maintainers=["@alice", "@bob"])
```

## Configuration

### Confidence Thresholds

Thresholds are configured per context requirement in TOML:

```toml
[controls."OSPS-GV-01.01".remediation]
requires_context = [
    { key = "maintainers", required = true, confidence_threshold = 0.9, prompt_if_auto_detected = true }
]
```

| Threshold | Behavior |
|-----------|----------|
| `confidence >= 0.9` | Use automatically without prompting |
| `confidence >= threshold` | Use but may prompt if `prompt_if_auto_detected = true` |
| `confidence < threshold` | Always prompt for confirmation |

## Testing

```bash
# Run context sieve tests
uv run pytest tests/darnit/context/test_context_sieve.py -v

# Test confidence scoring
uv run pytest tests/darnit/context/test_context_sieve.py::TestConfidenceScoring -v

# Test integration with validator
uv run pytest tests/darnit/context/test_context_sieve.py::TestIntegrationWithValidator -v
```

## Future Enhancements

1. **LLM Phase**: Add LLM consultation for ambiguous cases (Phase 3.5)
2. **Caching**: Cache detection results with TTL for performance
3. **More Context Keys**: Add `ci_provider`, `license_type`, `release_cadence`
4. **Custom Sources**: Allow plugins to register additional signal sources
5. **Learning**: Track which auto-detected values users confirm vs. correct

## Related Documentation

- [CONTEXT_PROMPTS.md](./CONTEXT_PROMPTS.md) - Context prompt system design
- [DECISION_FLOWS.md](../DECISION_FLOWS.md) - Decision flow diagrams
- [ARCHITECTURE.md](../../ARCHITECTURE.md) - Overall architecture

---

*Last updated: 2025-02-02 | Context Sieve v1.0*
