# Delta Spec: Framework Design — Strengthen Checks & Remediations

## MODIFIED Requirements

### Requirement: llm_eval handler files_to_include resolution

The `llm_eval` handler SHALL resolve the `files_to_include` config field by reading file contents and including them in the consultation request.

The handler SHALL resolve `$FOUND_FILE` entries by looking up `found_file` in `context.gathered_evidence`. Each resolved file path SHALL be read (up to 10KB per file, max 5 files) and included as a `file_contents` dict in the `consultation_request`. File paths that are not absolute SHALL be resolved relative to `context.local_path`. Files that cannot be read SHALL be silently skipped.

#### Scenario: files_to_include with $FOUND_FILE
- **WHEN** an `llm_eval` handler is invoked with `files_to_include = ["$FOUND_FILE"]`
- **AND** `context.gathered_evidence` contains `found_file` pointing to an existing file
- **THEN** the handler MUST read the file contents (up to 10KB)
- **AND** include them in `consultation_request.file_contents` keyed by relative path

#### Scenario: files_to_include with explicit paths
- **WHEN** an `llm_eval` handler is invoked with `files_to_include = ["SECURITY.md", "README.md"]`
- **AND** both files exist in `context.local_path`
- **THEN** the handler MUST read both file contents
- **AND** include them in `consultation_request.file_contents`

#### Scenario: files_to_include with unreadable file
- **WHEN** an `llm_eval` handler is invoked with `files_to_include` containing a path that cannot be read
- **THEN** the handler MUST silently skip the unreadable file
- **AND** still include any other readable files in `file_contents`

#### Scenario: files_to_include max limits
- **WHEN** an `llm_eval` handler is invoked with more than 5 entries in `files_to_include`
- **THEN** the handler MUST only process the first 5 entries
- **AND** each file MUST be truncated to 10,000 characters

### Requirement: FileCreateRemediation llm_enhance field

The `file_create` remediation handler SHALL support an optional `llm_enhance` string field. When present and the handler succeeds, the remediation executor SHALL propagate the enhancement prompt and file path to the remediation result details.

#### Scenario: file_create with llm_enhance on success
- **WHEN** a `file_create` handler succeeds (status PASS)
- **AND** the handler config includes an `llm_enhance` field
- **THEN** the remediation result details MUST include `llm_enhance` with the prompt and file path

#### Scenario: file_create with llm_enhance on failure
- **WHEN** a `file_create` handler fails (status FAIL or ERROR)
- **AND** the handler config includes an `llm_enhance` field
- **THEN** the `llm_enhance` field MUST NOT be propagated to the result

#### Scenario: file_create without llm_enhance
- **WHEN** a `file_create` handler succeeds
- **AND** the handler config does NOT include an `llm_enhance` field
- **THEN** the remediation result MUST NOT include any `llm_enhance` metadata

#### Scenario: llm_enhance in markdown output
- **WHEN** a remediation result contains `llm_enhance` metadata
- **THEN** `to_markdown()` MUST display an "AI Enhancement Available" section with the prompt and file path
