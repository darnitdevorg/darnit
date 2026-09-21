# Contract: Hermeticity Scan Coverage (RE-02.01)

**Feature**: 038 (#430, #432) | **Package**: `darnit-reproducibility` | **Status**: proposed

## Problem

`repro_hermetic_build` is careful about its PASS -- it requires a verified Witness attestation with a clean network log, a Nix flake build, or Bazel with a blocking flag, and explicitly rejects a mere mention of `witness run` in CI text. The defect is coverage, not credulity.

`_SUSPICIOUS_PATTERNS` holds seven entries and omits the Go, Rust, and Ruby installers (#430). Nothing detects compiler flags that make output depend on the build host (#432).

## Contract

### C-1: Installer coverage

`go install`, `go get`, `cargo install`, and `gem install` are live network fetches and MUST be reported as violations, on the same footing as `pip install` and `npm install`.

### C-2: A pinned fetch is still a fetch

`go install example.com/tool@v1.2.3` fetches at build time and remains a violation. The control's subject is hermeticity, not determinism. The message MUST name the pinned version when one is present, so an operator can see that their fetch is pinned without the tool pretending it did not happen.

### C-3: Compiler flags are reported separately

Non-deterministic compiler flags MUST NOT be reported through the network-fetch message. `_ScanKind` gains a `nondeterminism` member and the handler reports the two findings under distinct messages. Reporting `-march=native` as a "possible live network fetch" is a false statement about what was found.

Initial set: `-ffast-math`, `-march=native`, `-mtune=native`.

`-O3` is excluded. At a fixed toolchain it is deterministic; the non-determinism #432 describes comes from the unpinned toolchain, and flagging `-O3` would fire on a large share of legitimate builds.

### C-4: Detection goes through the existing scanner

All new patterns MUST be matched via `_scan_line`, which strips comments before matching and checks `_SAFE_PATTERNS` first. A second scanning path that skips the comment strip would report a flag mentioned in a Makefile comment as a finding (FR-015).

### C-5: The Nix gate is unchanged in form, changed in input

`_detect_strong_hermeticity_signal` continues to require `dependency_results.get("RE-01.02") == "PASS"`. No expression changes. Because RE-01.02 now returns WARN for an unpinned container declaration, repositories with a flake and a floating Dockerfile lose the Nix signal.

The RE-02.01 result MUST distinguish "the Nix signal was withheld because RE-01.02 did not pass" from "no flake was found." Without that, an operator sees a PASS disappear with no way to learn why.

## Test obligations

| ID | Assertion |
|---|---|
| HS-1 | `go install`, `go get`, `cargo install`, `gem install` each produce a violation naming the command and file. |
| HS-2 | `go install pkg@v1.2.3` is a violation whose message names the pinned version. |
| HS-3 | `-ffast-math`, `-march=native`, `-mtune=native` each produce a finding naming the flag and file. |
| HS-4 | The compiler-flag finding does not use the network-fetch message. |
| HS-5 | `-O3` alone produces no finding. |
| HS-6 | A flag or installer inside a comment produces no finding. |
| HS-7 | A flake plus `nix build` in CI plus a PASSing RE-01.02 still yields the Nix signal (unchanged). |
| HS-8 | A flake plus `nix build` plus a WARNing RE-01.02 yields no Nix signal, and the message attributes the withholding to RE-01.02 rather than to a missing flake (SC-010). |
| HS-9 | Existing PASS conditions -- verified Witness attestation, Bazel with a blocking flag -- are unchanged. |
