## ADDED Requirements

### Requirement: Audit cache module location and API
The framework SHALL provide an `audit_cache` module at `darnit.core.audit_cache` with three public functions: `write_audit_cache()`, `read_audit_cache()`, and `invalidate_audit_cache()`.

#### Scenario: Writing audit results to cache
- **WHEN** `write_audit_cache(local_path, results, summary, level, framework)` is called
- **THEN** it SHALL write a JSON file to `<local_path>/.darnit/audit-cache.json`
- **AND** it SHALL create the `.darnit/` directory if it does not exist
- **AND** the JSON SHALL contain a metadata envelope with `version`, `timestamp`, `commit`, `level`, `framework`, `results`, and `summary` fields

#### Scenario: Reading valid cache
- **WHEN** `read_audit_cache(local_path)` is called
- **AND** a cache file exists at `<local_path>/.darnit/audit-cache.json`
- **AND** the cache `commit` field matches the current `HEAD` commit
- **AND** the cache `commit_dirty` field matches the current working tree dirty state
- **THEN** it SHALL return the parsed cache dict containing `results` and `summary`

#### Scenario: Reading stale or missing cache
- **WHEN** `read_audit_cache(local_path)` is called
- **AND** no cache file exists, or the file is corrupt, or the `commit` field does not match current `HEAD`, or the dirty state has changed
- **THEN** it SHALL return `None`

#### Scenario: Invalidating cache
- **WHEN** `invalidate_audit_cache(local_path)` is called
- **THEN** it SHALL delete `<local_path>/.darnit/audit-cache.json` if it exists
- **AND** it SHALL NOT raise an error if the file does not exist

### Requirement: Cache staleness uses git commit hash
The cache SHALL use the current `HEAD` commit hash as its primary staleness key. The cache SHALL also track whether the working tree was dirty (uncommitted changes) at write time.

#### Scenario: Commit changes between audit and remediate
- **WHEN** an audit writes cache with commit `abc123`
- **AND** a new commit is made before remediate runs
- **THEN** `read_audit_cache()` SHALL return `None` (cache miss)
- **AND** the remediation tool SHALL fall back to running a fresh audit

#### Scenario: Working tree becomes dirty after clean audit
- **WHEN** an audit writes cache with `commit_dirty = false`
- **AND** the working tree has uncommitted changes when remediate reads the cache
- **THEN** `read_audit_cache()` SHALL return `None` (cache miss)

#### Scenario: Non-git repository
- **WHEN** `write_audit_cache()` is called in a directory that is not a git repository
- **THEN** it SHALL write the cache with `commit` set to `null`
- **AND** `read_audit_cache()` SHALL treat a `null` commit cache as always stale (return `None`)

### Requirement: Atomic cache writes
The cache module SHALL write the JSON file atomically to prevent corruption from concurrent access or interrupted writes.

#### Scenario: Concurrent write safety
- **WHEN** `write_audit_cache()` is called
- **THEN** it SHALL write to a temporary file in the same directory
- **AND** it SHALL rename the temporary file to `audit-cache.json` (atomic on POSIX)

#### Scenario: Corrupt cache file
- **WHEN** `read_audit_cache()` encounters a file that is not valid JSON
- **THEN** it SHALL return `None` (treat as cache miss)
- **AND** it SHALL log a debug-level message about the corrupt cache

### Requirement: Cache envelope schema
The cache JSON file SHALL conform to a versioned envelope schema to support future changes.

#### Scenario: Cache envelope structure
- **WHEN** `write_audit_cache()` writes the cache
- **THEN** the JSON SHALL contain these top-level fields:
  - `version` (integer): Schema version, currently `1`
  - `timestamp` (string): ISO 8601 UTC timestamp of when the audit ran
  - `commit` (string or null): Git HEAD commit hash at audit time
  - `commit_dirty` (boolean): Whether the working tree had uncommitted changes
  - `level` (integer): Maximum audit level that was evaluated
  - `framework` (string): Framework name (e.g., `"openssf-baseline"`)
  - `results` (array): The raw results list from `run_sieve_audit()`
  - `summary` (dict): Status count summary from `run_sieve_audit()`

#### Scenario: Unknown cache version
- **WHEN** `read_audit_cache()` reads a cache file with `version` greater than the supported version
- **THEN** it SHALL return `None` (treat as cache miss)
