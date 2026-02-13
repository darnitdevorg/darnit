## MODIFIED Requirements

### Requirement: Implementation Protocol

```python
from darnit.core.plugin import ComplianceImplementation, ControlSpec

class MyImplementation:
    @property
    def name(self) -> str:
        return "my-framework"

    @property
    def display_name(self) -> str:
        return "My Framework"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def spec_version(self) -> str:
        return "MySpec v1.0"

    def get_all_controls(self) -> list[ControlSpec]:
        # Return control definitions
        ...

    def get_framework_config_path(self) -> Path | None:
        # Return path to TOML config
        return Path(__file__).parent / "my-framework.toml"

    def register_controls(self) -> None:
        # No-op. Control definitions MUST come from TOML.
        # This method exists for protocol compatibility only.
        pass

    def register_handlers(self) -> None:
        # Register custom sieve/remediation handlers
        ...
```

The `register_controls()` method SHALL be a no-op. Implementations MUST NOT use this method to register `ControlSpec` objects with `passes` fields populated. All control definitions MUST originate from TOML configuration files and be loaded via the framework's TOML control loader. The only supported extension point for custom checking logic is `register_handlers()`, which registers named handler functions callable from TOML pass definitions.

#### Scenario: Implementation calls register_controls
- **WHEN** the audit pipeline calls `impl.register_controls()`
- **THEN** no `ControlSpec` objects SHALL be registered in the global registry
- **AND** no side-effect imports of control definition modules SHALL occur

#### Scenario: Plugin extends checking with custom handler
- **WHEN** a plugin needs custom checking logic beyond built-in pass types
- **THEN** it SHALL register a named handler via `register_handlers()`
- **AND** the TOML control definition SHALL reference the handler by name in its `passes` configuration

### Requirement: No hardcoded OSPS control IDs in framework

The `packages/darnit/src/darnit/` source tree SHALL NOT contain hardcoded control definitions registered at module import time. The framework's `sieve/registry.py` module SHALL only provide the `ControlRegistry` class and `register_control()` function — it SHALL NOT call `register_control()` at module scope with hardcoded `ControlSpec` instances.

#### Scenario: Framework registry module is imported
- **WHEN** `darnit.sieve.registry` is imported
- **THEN** zero `register_control()` calls SHALL execute as module-level side effects
- **AND** the global registry SHALL contain zero controls until TOML loading occurs

#### Scenario: Searching framework source for control IDs
- **WHEN** the `packages/darnit/src/darnit/` source tree is searched for patterns like `OSPS-AC-03.01`
- **THEN** no hardcoded OSPS control ID patterns SHALL exist in executable code
- **AND** no `ControlSpec(control_id=...)` constructor calls SHALL exist outside of test files

## REMOVED Requirements

### Requirement: Legacy pass re-exports from sieve package

The `darnit.sieve` package previously re-exported pass class constructors (`DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`) for convenience. These re-exports SHALL be removed from `sieve/__init__.py`. The pass dataclass definitions in `sieve/passes.py` remain available via direct import.

**Reason**: The re-exports existed to support hardcoded Python control definitions that constructed `ControlSpec(passes=[DeterministicPass(...)])` at import time. With TOML as the sole control definition path, these convenience re-exports have no consumers.

**Migration**: Import directly from `darnit.sieve.passes` if needed (e.g., `from darnit.sieve.passes import DeterministicPass`). However, new code SHOULD NOT construct pass instances directly — define passes in TOML instead.
