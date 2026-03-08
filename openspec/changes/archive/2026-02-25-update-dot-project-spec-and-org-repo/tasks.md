## 1. Security Contact Struct Support

- [x] 1.1 Add `SecurityContact` dataclass to `dot_project.py` with `email`, `advisory_url`, and `_extra` fields
- [x] 1.2 Update `SecurityConfig.contact` type to `SecurityContact | str | None`
- [x] 1.3 Add `_parse_security_contact()` method to `DotProjectReader` that dispatches on dict vs string
- [x] 1.4 Add `SecurityContactModel` Pydantic model to `config/schema.py` with `email` and `advisory_url`
- [x] 1.5 Update Pydantic `SecurityConfig.contact` type to `SecurityContactModel | EmailStr | str | None`
- [x] 1.6 Update `get_security_contact()` accessor to extract email from struct contact

## 2. Teams-Based Maintainers Support

- [x] 2.1 Add `MaintainerEntry` dataclass with handle, email, role, title, name fields
- [x] 2.2 Add `MaintainerTeam` dataclass with name and members list
- [x] 2.3 Add `maintainer_teams`, `maintainer_entries`, `maintainer_org`, `maintainer_project_id` fields to `ProjectConfig`
- [x] 2.4 Replace `_read_maintainers()` with `_read_maintainers_into()` that populates both flat and structured fields
- [x] 2.5 Add `_extract_maintainer_entries()` returning tuple of (handles, entries)
- [x] 2.6 Add `_parse_maintainer_entry()` and `_parse_maintainer_teams()` methods
- [x] 2.7 Implement handle deduplication across teams in flat maintainers list

## 3. Org-Level .project Repo Resolver

- [x] 3.1 Create `dot_project_org.py` module with `OrgProjectResolver` class
- [x] 3.2 Implement `_is_gh_available()` to check gh CLI auth status
- [x] 3.3 Implement `_repo_exists()` to check if `{owner}/.project` repo exists
- [x] 3.4 Implement `_fetch_file_content()` to fetch and base64-decode file content via gh API
- [x] 3.5 Implement `_fetch_org_project()` to fetch project.yaml and maintainers.yaml into temp dir and parse with `DotProjectReader`
- [x] 3.6 Add module-level `_org_cache` dict and `clear_cache()` function

## 4. Config Merge Logic

- [x] 4.1 Create `dot_project_merger.py` module with `merge_configs()` function
- [x] 4.2 Implement section-level override: local section wins entirely if present
- [x] 4.3 Implement scalar field override: local wins if non-empty
- [x] 4.4 Implement list field override with shallow copy to prevent mutation
- [x] 4.5 Implement dict field override with shallow copy
- [x] 4.6 Implement `_extra` merge: combine both, local keys win on conflict
- [x] 4.7 Add `_shallow_copy_config()` helper to prevent input mutation

## 5. Context Mapper and Pipeline Wiring

- [x] 5.1 Add `owner` parameter to `DotProjectMapper.__init__()`
- [x] 5.2 Integrate `OrgProjectResolver` and `merge_configs` into mapper's `config` property
- [x] 5.3 Update `_map_security()` to handle `SecurityContact` struct: emit `contact_email` and `advisory_url`
- [x] 5.4 Add context variable emission for `project.maintainer_org`, `project.maintainer_project_id`, `project.maintainer_teams`
- [x] 5.5 Update `inject_project_context()` to pass `context.owner` to the mapper
- [x] 5.6 Update `context/__init__.py` exports with new types and modules

## 6. Tests

- [x] 6.1 Add `TestSecurityContactStruct` tests: parse as string, parse as struct, struct extra fields, mapper struct contact, mapper string backward compat
- [x] 6.2 Add `TestMaintainersTeamsFormat` tests: teams format, string members, flat list compat, dict-with-handle compat, team context vars, handle deduplication
- [x] 6.3 Create `test_dot_project_org.py`: empty owner, gh unavailable, caching, repo not found, fetch+parse project.yaml, fetch maintainers.yaml, no project.yaml, missing CLI, unauthenticated, cache clearing
- [x] 6.4 Create `test_dot_project_merger.py`: org None, org defaults, local override scalars, section-level override, org section default, list override, dict override, extra merge, source path preservation, input mutation safety, governance section-level, maintainer metadata

## 7. Validation

- [x] 7.1 Run `uv run ruff check .` — all checks pass
- [x] 7.2 Run `uv run pytest tests/ --ignore=tests/integration/` — 1016 passed (1 pre-existing upstream hash failure)
- [x] 7.3 Run `uv run python scripts/validate_sync.py --verbose` — all validations pass
- [x] 7.4 Run `uv run python scripts/generate_docs.py` — no doc changes needed
