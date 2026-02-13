## 1. Insert new Section 5: Custom Sieve Handlers

- [x] 1.1 Add section header and intro paragraph explaining that custom sieve handlers extend checking/remediation beyond built-in TOML pass types, with a source-file reference to `handler_registry.py`
- [x] 1.2 Document handler function signature `(config: dict[str, Any], context: HandlerContext) -> HandlerResult` with a minimal working example
- [x] 1.3 Document all `HandlerContext` fields in a table: local_path, owner, repo, default_branch, control_id, project_context, gathered_evidence, shared_cache, dependency_results — with type, purpose, and when populated
- [x] 1.4 Document `HandlerResult` construction: status semantics (PASS, FAIL, INCONCLUSIVE, ERROR), message, confidence, evidence dict, details dict — with examples for each status
- [x] 1.5 Document handler registration via `get_sieve_handler_registry()` and `registry.register(name, phase, handler_fn, description)` with phase affinity explanation
- [x] 1.6 Document plugin context: `set_plugin_context(self.name)` before registration, clearing after, and override behavior (plugin overrides core built-in of same name)
- [x] 1.7 Document TOML wiring: `[[passes]]` block with `handler = "my_handler"` and pass-through config fields, showing how TOML fields arrive in the `config` dict
- [x] 1.8 Document evidence propagation: how `HandlerResult.evidence` merges into `gathered_evidence` for subsequent handlers, with a two-pass TOML example (file_exists → custom checker reading `$FOUND_FILE`)

## 2. Remediation handler subsection

- [x] 2.1 Document remediation handler differences: all handlers in a phase execute (not stop-on-first-conclusive), same `HandlerResult` type with different semantics
- [x] 2.2 Document dry-run support convention: checking `config.get("dry_run")` and returning descriptive PASS without side effects
- [x] 2.3 Document `project_update` integration and `on_pass` auto-derivation pattern

## 3. Two-registry distinction callout

- [x] 3.1 Add a callout note distinguishing `SieveHandlerRegistry` (Layer 1/2, checking+remediation) from `HandlerRegistry` (Layer 3, MCP tools) — explain which `register_handlers()` uses which registry

## 4. End-to-end example

- [x] 4.1 Write complete `license_header` handler example: Python function with docstring, config parsing, file I/O, evidence production, error handling (~30 lines)
- [x] 4.2 Show registration call for the `license_header` handler with phase affinity
- [x] 4.3 Show TOML control definition referencing the handler with pass-through config
- [x] 4.4 Show expected audit output for both pass and fail cases

## 5. Legacy section update

- [x] 5.1 Renumber current section 5 ("Python Controls") to section 6 and add deprecation banner pointing to new section 5
- [x] 5.2 Renumber all subsequent sections (6→7, 7→8, 8→9, 9→10, 10→11)
- [x] 5.3 Update internal cross-references throughout the guide to use new section numbers

## 6. Validation

- [x] 6.1 Verify all 8 spec requirements are covered by reading through the new section against the spec scenarios
- [x] 6.2 Run `uv run python scripts/generate_docs.py` and commit any generated doc changes
