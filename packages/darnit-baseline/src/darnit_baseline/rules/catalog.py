"""OSPS Baseline rules catalog for SARIF generation.

This module contains metadata for all 62 OSPS controls from the
OpenSSF Baseline v2025.10.10 specification.

Each rule includes:
- Control ID and name
- Domain and maturity level
- Short and full descriptions
- Remediation help text
- Security severity score
- Tags for categorization
- Location hints for code linking
"""

from typing import Dict, Any, Optional


# Domain descriptions for tags
DOMAIN_INFO = {
    "AC": {
        "name": "Access Control",
        "tags": ["access-control", "authentication", "authorization"],
    },
    "BR": {
        "name": "Build and Release",
        "tags": ["build", "release", "ci-cd", "supply-chain"],
    },
    "DO": {
        "name": "Documentation",
        "tags": ["documentation"],
    },
    "GV": {
        "name": "Governance",
        "tags": ["governance", "maintainership"],
    },
    "LE": {
        "name": "Legal",
        "tags": ["legal", "licensing"],
    },
    "QA": {
        "name": "Quality Assurance",
        "tags": ["quality", "testing"],
    },
    "SA": {
        "name": "Security Assessment",
        "tags": ["security-analysis", "architecture"],
    },
    "VM": {
        "name": "Vulnerability Management",
        "tags": ["vulnerability", "security"],
    },
}


# Complete OSPS rules catalog
OSPS_RULES: Dict[str, Dict[str, Any]] = {
    # ==========================================================================
    # Level 1 - Access Control (AC)
    # ==========================================================================
    "OSPS-AC-01.01": {
        "name": "MFARequired",
        "domain": "AC",
        "level": 1,
        "short": "MFA required for repository access",
        "full": "When a user attempts to read or modify a sensitive resource, the system MUST require the user to complete a multi-factor authentication process.",
        "help_md": """Enable MFA for all organization members with elevated permissions.

**Remediation:**
1. Go to Organization Settings → Security
2. Enable 'Require two-factor authentication for everyone'
3. Set a grace period for existing members to enable MFA

**References:**
- [GitHub MFA Documentation](https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa)
""",
        "security_severity": 9.0,
        "tags": ["mfa", "authentication"],
        "location_hint": ".github/settings.yml",
        "default_level": "error",
    },
    "OSPS-AC-02.01": {
        "name": "DefaultCollaboratorPermissions",
        "domain": "AC",
        "level": 1,
        "short": "Default collaborator permissions are minimal",
        "full": "When a new collaborator is added, the version control system MUST require manual permission assignment, or restrict the collaborator permissions to the lowest available privileges by default.",
        "help_md": """Configure repository to use minimal default permissions.

**Remediation:**
1. Go to Organization Settings → Member privileges
2. Set 'Base permissions' to 'No permission' or 'Read'
3. Use teams for permission management

**References:**
- [GitHub Repository Permissions](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/repository-roles-for-an-organization)
""",
        "security_severity": 7.0,
        "tags": ["permissions", "least-privilege"],
        "location_hint": ".github/settings.yml",
        "default_level": "warning",
    },
    "OSPS-AC-03.01": {
        "name": "PreventDirectCommits",
        "domain": "AC",
        "level": 1,
        "short": "Prevent direct commits to primary branch",
        "full": "When a direct commit is attempted on the project's primary branch, an enforcement mechanism MUST prevent the change from being applied.",
        "help_md": """Enable branch protection to require pull requests.

**Remediation:**
1. Go to Repository Settings → Branches
2. Add branch protection rule for main/master
3. Enable 'Require a pull request before merging'

**References:**
- [GitHub Branch Protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
""",
        "security_severity": 8.0,
        "tags": ["branch-protection", "code-review"],
        "location_hint": ".github/settings.yml",
        "default_level": "error",
    },
    "OSPS-AC-03.02": {
        "name": "PreventBranchDeletion",
        "domain": "AC",
        "level": 1,
        "short": "Prevent deletion of primary branch",
        "full": "When an attempt is made to delete the project's primary branch, the version control system MUST treat this as a sensitive activity and require explicit confirmation.",
        "help_md": """Protect primary branch from deletion.

**Remediation:**
1. Go to Repository Settings → Branches
2. Add branch protection rule for main/master
3. The rule automatically prevents branch deletion

**References:**
- [GitHub Branch Protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
""",
        "security_severity": 7.0,
        "tags": ["branch-protection"],
        "location_hint": ".github/settings.yml",
        "default_level": "error",
    },

    # ==========================================================================
    # Level 1 - Build and Release (BR)
    # ==========================================================================
    "OSPS-BR-01.01": {
        "name": "SanitizeCIInputs",
        "domain": "BR",
        "level": 1,
        "short": "CI/CD inputs are sanitized",
        "full": "When a CI/CD pipeline accepts an input parameter, that parameter MUST be sanitized and validated prior to use in the pipeline.",
        "help_md": """Sanitize all CI/CD input parameters to prevent injection attacks.

**Remediation:**
1. Review workflow files for input usage
2. Use intermediate environment variables instead of direct interpolation
3. Validate inputs before use in shell commands

**Example:**
```yaml
env:
  INPUT_VALUE: ${{ inputs.value }}
run: |
  # Validate before use
  if [[ "$INPUT_VALUE" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Valid input: $INPUT_VALUE"
  fi
```
""",
        "security_severity": 8.5,
        "tags": ["ci-cd", "injection", "security"],
        "location_hint": ".github/workflows",
        "default_level": "error",
    },
    "OSPS-BR-01.02": {
        "name": "SanitizeBranchNames",
        "domain": "BR",
        "level": 1,
        "short": "Branch names sanitized in CI/CD",
        "full": "When a CI/CD pipeline uses a branch name in its functionality, that name value MUST be sanitized and validated prior to use.",
        "help_md": """Sanitize branch names before use in CI/CD pipelines.

**Remediation:**
1. Avoid using `github.head_ref` directly in shell commands
2. Use intermediate environment variables
3. Validate branch names match expected patterns

**Example:**
```yaml
env:
  BRANCH: ${{ github.head_ref }}
run: |
  # Branch name is now safely quoted
  echo "Building branch: $BRANCH"
```
""",
        "security_severity": 8.0,
        "tags": ["ci-cd", "injection"],
        "location_hint": ".github/workflows",
        "default_level": "error",
    },
    "OSPS-BR-03.01": {
        "name": "EncryptedProjectChannels",
        "domain": "BR",
        "level": 1,
        "short": "Project channels use encryption",
        "full": "When the project lists a URI as an official project channel, that URI MUST be exclusively delivered using encrypted channels.",
        "help_md": """Ensure all project URIs use HTTPS.

**Remediation:**
1. Review README and documentation for HTTP links
2. Update all links to use HTTPS
3. Configure redirects from HTTP to HTTPS

**References:**
- All official channels should use TLS/HTTPS
""",
        "security_severity": 6.0,
        "tags": ["encryption", "https"],
        "location_hint": "README.md",
        "default_level": "warning",
    },
    "OSPS-BR-03.02": {
        "name": "EncryptedDistributionChannels",
        "domain": "BR",
        "level": 1,
        "short": "Distribution channels use encryption",
        "full": "When the project lists a URI as an official distribution channel, that URI MUST be exclusively delivered using encrypted channels.",
        "help_md": """Ensure all distribution URIs use HTTPS.

**Remediation:**
1. Review package registry URLs
2. Ensure download links use HTTPS
3. Document secure installation methods
""",
        "security_severity": 7.0,
        "tags": ["encryption", "https", "distribution"],
        "location_hint": "README.md",
        "default_level": "warning",
    },
    "OSPS-BR-07.01": {
        "name": "PreventSecretStorage",
        "domain": "BR",
        "level": 1,
        "short": "Prevent unencrypted secrets in VCS",
        "full": "The project MUST prevent the unintentional storage of unencrypted sensitive data, such as secrets and credentials, in the version control system.",
        "help_md": """Configure secret scanning and .gitignore to prevent secret leaks.

**Remediation:**
1. Enable GitHub Secret Scanning
2. Add sensitive file patterns to .gitignore
3. Use pre-commit hooks for secret detection
4. Review commit history for exposed secrets

**Example .gitignore:**
```
.env
*.pem
*.key
credentials.json
```
""",
        "security_severity": 9.0,
        "tags": ["secrets", "credentials"],
        "location_hint": ".gitignore",
        "default_level": "error",
    },

    # ==========================================================================
    # Level 1 - Documentation (DO)
    # ==========================================================================
    "OSPS-DO-01.01": {
        "name": "UserDocumentation",
        "domain": "DO",
        "level": 1,
        "short": "User documentation exists",
        "full": "When the project has made a release, the project documentation MUST include user guides for all basic functionality.",
        "help_md": """Create user documentation for basic functionality.

**Remediation:**
1. Create a README.md with usage instructions
2. Add installation guide
3. Include basic examples
4. Consider adding a docs/ directory for detailed documentation
""",
        "security_severity": 3.0,
        "tags": ["documentation", "user-guide"],
        "location_hint": "README.md",
        "default_level": "warning",
    },
    "OSPS-DO-02.01": {
        "name": "DefectReportingGuide",
        "domain": "DO",
        "level": 1,
        "short": "Defect reporting guide exists",
        "full": "When the project has made a release, the project documentation MUST include a guide for reporting defects.",
        "help_md": """Create a guide for reporting bugs and defects.

**Remediation:**
1. Create .github/ISSUE_TEMPLATE/bug_report.md
2. Include expected vs actual behavior fields
3. Add reproduction steps template
4. Link to issue tracker in README
""",
        "security_severity": 2.0,
        "tags": ["documentation", "issues"],
        "location_hint": ".github/ISSUE_TEMPLATE",
        "default_level": "note",
    },

    # ==========================================================================
    # Level 1 - Governance (GV)
    # ==========================================================================
    "OSPS-GV-02.01": {
        "name": "PublicDiscussionMechanism",
        "domain": "GV",
        "level": 1,
        "short": "Public discussion mechanism exists",
        "full": "While active, the project MUST have one or more mechanisms for public discussions about proposed changes and usage obstacles.",
        "help_md": """Enable public discussion channels.

**Remediation:**
1. Enable GitHub Discussions or Issues
2. Create a CONTRIBUTING.md with discussion guidelines
3. Consider adding a mailing list or chat channel
""",
        "security_severity": 2.0,
        "tags": ["governance", "community"],
        "location_hint": "CONTRIBUTING.md",
        "default_level": "note",
    },
    "OSPS-GV-03.01": {
        "name": "ContributionProcess",
        "domain": "GV",
        "level": 1,
        "short": "Contribution process documented",
        "full": "While active, the project documentation MUST include an explanation of the contribution process.",
        "help_md": """Document the contribution process.

**Remediation:**
1. Create CONTRIBUTING.md
2. Explain how to submit changes (PRs)
3. Describe the review process
4. Include coding standards if applicable
""",
        "security_severity": 2.0,
        "tags": ["governance", "contributing"],
        "location_hint": "CONTRIBUTING.md",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 1 - Legal (LE)
    # ==========================================================================
    "OSPS-LE-02.01": {
        "name": "OSIApprovedSourceLicense",
        "domain": "LE",
        "level": 1,
        "short": "Source code has OSI-approved license",
        "full": "While active, the license for the source code MUST meet the OSI Open Source Definition or the FSF Free Software Definition.",
        "help_md": """Use an OSI-approved open source license.

**Remediation:**
1. Choose an OSI-approved license (MIT, Apache-2.0, GPL, etc.)
2. Add LICENSE file to repository root
3. Include license header in source files if required

**References:**
- [OSI Approved Licenses](https://opensource.org/licenses)
""",
        "security_severity": 3.0,
        "tags": ["license", "osi"],
        "location_hint": "LICENSE",
        "default_level": "error",
    },
    "OSPS-LE-02.02": {
        "name": "OSIApprovedReleaseLicense",
        "domain": "LE",
        "level": 1,
        "short": "Released assets have OSI-approved license",
        "full": "While active, the license for the released software assets MUST meet the OSI Open Source Definition or the FSF Free Software Definition.",
        "help_md": """Include OSI-approved license with releases.

**Remediation:**
1. Include LICENSE file in release assets
2. Ensure license is compatible with dependencies
3. Document license in package metadata
""",
        "security_severity": 3.0,
        "tags": ["license", "osi", "release"],
        "location_hint": "LICENSE",
        "default_level": "error",
    },
    "OSPS-LE-03.01": {
        "name": "LicenseInRepository",
        "domain": "LE",
        "level": 1,
        "short": "License file in repository",
        "full": "While active, the license for the source code MUST be maintained in the repository's LICENSE file, COPYING file, or LICENSE/ directory.",
        "help_md": """Add license file to repository.

**Remediation:**
1. Create LICENSE or COPYING file in repository root
2. Use full license text, not abbreviation
3. GitHub will auto-detect standard licenses
""",
        "security_severity": 3.0,
        "tags": ["license"],
        "location_hint": "LICENSE",
        "default_level": "error",
    },
    "OSPS-LE-03.02": {
        "name": "LicenseWithReleases",
        "domain": "LE",
        "level": 1,
        "short": "License included with releases",
        "full": "While active, the license for released software assets MUST be included in the released source code, or in a LICENSE file alongside release assets.",
        "help_md": """Include license file in release artifacts.

**Remediation:**
1. Add LICENSE to release archive
2. Include license in package metadata
3. Automate license inclusion in release workflow
""",
        "security_severity": 3.0,
        "tags": ["license", "release"],
        "location_hint": "LICENSE",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 1 - Quality Assurance (QA)
    # ==========================================================================
    "OSPS-QA-01.01": {
        "name": "PublicRepository",
        "domain": "QA",
        "level": 1,
        "short": "Source code publicly readable",
        "full": "While active, the project's source code repository MUST be publicly readable at a static URL.",
        "help_md": """Ensure repository is publicly accessible.

**Remediation:**
1. Set repository visibility to Public
2. Ensure URL is stable and doesn't change
3. Consider using a well-known hosting platform (GitHub, GitLab)
""",
        "security_severity": 2.0,
        "tags": ["transparency", "public"],
        "location_hint": "",
        "default_level": "error",
    },
    "OSPS-QA-01.02": {
        "name": "PublicChangeHistory",
        "domain": "QA",
        "level": 1,
        "short": "Public change history",
        "full": "The version control system MUST contain a publicly readable record of all changes made, who made them, and when they were made.",
        "help_md": """Maintain public git history.

**Remediation:**
1. Use git for version control
2. Don't squash history excessively
3. Maintain author attribution in commits
""",
        "security_severity": 2.0,
        "tags": ["transparency", "history"],
        "location_hint": "",
        "default_level": "note",
    },
    "OSPS-QA-02.01": {
        "name": "DependencyList",
        "domain": "QA",
        "level": 1,
        "short": "Dependency list maintained",
        "full": "When the package management system supports it, the source code repository MUST contain a dependency list accounting for direct language dependencies.",
        "help_md": """Maintain dependency list in repository.

**Remediation:**
1. Use package.json (Node), requirements.txt (Python), go.mod (Go), etc.
2. Keep dependencies up to date
3. Consider using lockfiles for reproducibility
""",
        "security_severity": 4.0,
        "tags": ["dependencies", "sbom"],
        "location_hint": "package.json",
        "default_level": "warning",
    },
    "OSPS-QA-04.01": {
        "name": "SubprojectList",
        "domain": "QA",
        "level": 1,
        "short": "Subprojects documented",
        "full": "While active, the project documentation MUST contain a list of any codebases considered subprojects.",
        "help_md": """Document subprojects and dependencies.

**Remediation:**
1. List subprojects in README or documentation
2. For monorepos, document each package
3. Explain relationships between components
""",
        "security_severity": 2.0,
        "tags": ["documentation", "subprojects"],
        "location_hint": "README.md",
        "default_level": "note",
    },
    "OSPS-QA-05.01": {
        "name": "NoGeneratedExecutables",
        "domain": "QA",
        "level": 1,
        "short": "No generated executables in VCS",
        "full": "While active, the version control system MUST NOT contain generated executable artifacts.",
        "help_md": """Remove generated executables from repository.

**Remediation:**
1. Add build outputs to .gitignore
2. Remove existing binaries from git history
3. Use releases for distributing binaries
""",
        "security_severity": 5.0,
        "tags": ["binaries", "security"],
        "location_hint": ".gitignore",
        "default_level": "warning",
    },
    "OSPS-QA-05.02": {
        "name": "NoUnreviewableBinaries",
        "domain": "QA",
        "level": 1,
        "short": "No unreviewable binaries in VCS",
        "full": "While active, the version control system MUST NOT contain unreviewable binary artifacts.",
        "help_md": """Remove unreviewable binary files from repository.

**Remediation:**
1. Add binary patterns to .gitignore
2. Use Git LFS for necessary large files
3. Document any required binaries
""",
        "security_severity": 5.0,
        "tags": ["binaries", "review"],
        "location_hint": ".gitignore",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 1 - Vulnerability Management (VM)
    # ==========================================================================
    "OSPS-VM-02.01": {
        "name": "SecurityContacts",
        "domain": "VM",
        "level": 1,
        "short": "Security contacts documented",
        "full": "While active, the project documentation MUST contain security contacts.",
        "help_md": """Add security contacts to SECURITY.md.

**Remediation:**
1. Create SECURITY.md in repository root
2. Include email or contact method
3. Consider using GitHub Security Advisories
""",
        "security_severity": 6.0,
        "tags": ["security-policy", "contacts"],
        "location_hint": "SECURITY.md",
        "default_level": "error",
    },

    # ==========================================================================
    # Level 2 - Access Control (AC)
    # ==========================================================================
    "OSPS-AC-04.01": {
        "name": "CICDDefaultLowestPermissions",
        "domain": "AC",
        "level": 2,
        "short": "CI/CD defaults to lowest permissions",
        "full": "When a CI/CD task is executed with no permissions specified, the CI/CD system MUST default the task's permissions to the lowest permissions granted in the pipeline.",
        "help_md": """Configure workflows with explicit minimal permissions.

**Remediation:**
1. Add `permissions: {}` at workflow level for read-only default
2. Only grant specific permissions where needed
3. Use `permissions: read-all` for read-only jobs

**Example:**
```yaml
permissions:
  contents: read
  pull-requests: write
```
""",
        "security_severity": 7.0,
        "tags": ["ci-cd", "permissions", "least-privilege"],
        "location_hint": ".github/workflows",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 2 - Build and Release (BR)
    # ==========================================================================
    "OSPS-BR-02.01": {
        "name": "UniqueVersionIdentifiers",
        "domain": "BR",
        "level": 2,
        "short": "Releases have unique versions",
        "full": "When an official release is created, that release MUST be assigned a unique version identifier.",
        "help_md": """Use semantic versioning for releases.

**Remediation:**
1. Use semantic versioning (MAJOR.MINOR.PATCH)
2. Tag releases in git
3. Ensure no duplicate version numbers
""",
        "security_severity": 4.0,
        "tags": ["versioning", "release"],
        "location_hint": "",
        "default_level": "warning",
    },
    "OSPS-BR-04.01": {
        "name": "ReleaseChangelog",
        "domain": "BR",
        "level": 2,
        "short": "Releases contain changelog",
        "full": "When an official release is created, that release MUST contain a descriptive log of functional and security modifications.",
        "help_md": """Include changelog with releases.

**Remediation:**
1. Maintain CHANGELOG.md
2. Include release notes with GitHub releases
3. Document security fixes prominently
""",
        "security_severity": 3.0,
        "tags": ["changelog", "release"],
        "location_hint": "CHANGELOG.md",
        "default_level": "warning",
    },
    "OSPS-BR-05.01": {
        "name": "StandardizedDependencyTooling",
        "domain": "BR",
        "level": 2,
        "short": "Uses standardized dependency tooling",
        "full": "When a build and release pipeline ingests dependencies, it MUST use standardized tooling where available.",
        "help_md": """Use standard package managers and lockfiles.

**Remediation:**
1. Use npm/yarn (Node), pip/poetry (Python), etc.
2. Commit lockfiles to repository
3. Pin dependency versions
""",
        "security_severity": 5.0,
        "tags": ["dependencies", "tooling"],
        "location_hint": "package-lock.json",
        "default_level": "warning",
    },
    "OSPS-BR-06.01": {
        "name": "SignedReleasesOrManifest",
        "domain": "BR",
        "level": 2,
        "short": "Releases signed or have checksums",
        "full": "When an official release is created, that release MUST be signed or accounted for in a signed manifest including each asset's cryptographic hashes.",
        "help_md": """Sign releases or provide checksums.

**Remediation:**
1. Use Sigstore/cosign for signing
2. Generate SHA256 checksums for artifacts
3. Include checksums in release notes
4. Consider using GitHub artifact attestations
""",
        "security_severity": 7.0,
        "tags": ["signing", "integrity", "release"],
        "location_hint": "",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 2 - Documentation (DO)
    # ==========================================================================
    "OSPS-DO-06.01": {
        "name": "DependencyManagementDocs",
        "domain": "DO",
        "level": 2,
        "short": "Dependency management documented",
        "full": "When the project has made a release, the project documentation MUST include a description of how the project selects, obtains, and tracks its dependencies.",
        "help_md": """Document dependency management process.

**Remediation:**
1. Create DEPENDENCIES.md or add section to README
2. Explain how dependencies are selected
3. Document update/review process
""",
        "security_severity": 3.0,
        "tags": ["documentation", "dependencies"],
        "location_hint": "README.md",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 2 - Governance (GV)
    # ==========================================================================
    "OSPS-GV-01.01": {
        "name": "SensitiveAccessList",
        "domain": "GV",
        "level": 2,
        "short": "Members with sensitive access listed",
        "full": "While active, the project documentation MUST include a list of project members with access to sensitive resources.",
        "help_md": """Document members with elevated access.

**Remediation:**
1. Create MAINTAINERS.md or GOVERNANCE.md
2. List maintainers and their roles
3. Use CODEOWNERS for code review assignments
""",
        "security_severity": 5.0,
        "tags": ["governance", "access-control"],
        "location_hint": "MAINTAINERS.md",
        "default_level": "warning",
    },
    "OSPS-GV-01.02": {
        "name": "RolesAndResponsibilities",
        "domain": "GV",
        "level": 2,
        "short": "Roles and responsibilities documented",
        "full": "While active, the project documentation MUST include descriptions of the roles and responsibilities for members.",
        "help_md": """Document roles and responsibilities.

**Remediation:**
1. Add roles section to GOVERNANCE.md
2. Define maintainer vs committer vs contributor
3. Explain decision-making process
""",
        "security_severity": 3.0,
        "tags": ["governance", "roles"],
        "location_hint": "GOVERNANCE.md",
        "default_level": "warning",
    },
    "OSPS-GV-03.02": {
        "name": "ContributionRequirements",
        "domain": "GV",
        "level": 2,
        "short": "Contribution requirements documented",
        "full": "While active, the project documentation MUST include a guide for code contributors that includes requirements for acceptable contributions.",
        "help_md": """Document contribution requirements.

**Remediation:**
1. Expand CONTRIBUTING.md
2. Include code style requirements
3. Explain testing requirements
4. Document review process
""",
        "security_severity": 3.0,
        "tags": ["contributing", "requirements"],
        "location_hint": "CONTRIBUTING.md",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 2 - Legal (LE)
    # ==========================================================================
    "OSPS-LE-01.01": {
        "name": "DCOOrCLARequired",
        "domain": "LE",
        "level": 2,
        "short": "DCO or CLA required for contributions",
        "full": "While active, the version control system MUST require all code contributors to assert that they are legally authorized to make the associated contributions on every commit.",
        "help_md": """Implement DCO or CLA for contributions.

**Remediation:**
1. Add DCO requirement (Signed-off-by)
2. Or implement CLA bot
3. Document requirement in CONTRIBUTING.md

**DCO Sign-off:**
```
git commit -s -m "Your commit message"
```
""",
        "security_severity": 4.0,
        "tags": ["legal", "dco", "cla"],
        "location_hint": "CONTRIBUTING.md",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 2 - Quality Assurance (QA)
    # ==========================================================================
    "OSPS-QA-03.01": {
        "name": "StatusChecksMustPass",
        "domain": "QA",
        "level": 2,
        "short": "Status checks must pass before merge",
        "full": "When a commit is made to the primary branch, any automated status checks for commits MUST pass or be manually bypassed.",
        "help_md": """Configure required status checks.

**Remediation:**
1. Go to Repository Settings → Branches
2. Edit branch protection rule
3. Enable 'Require status checks to pass'
4. Select required checks
""",
        "security_severity": 6.0,
        "tags": ["branch-protection", "ci-cd"],
        "location_hint": ".github/settings.yml",
        "default_level": "warning",
    },
    "OSPS-QA-06.01": {
        "name": "AutomatedTestSuite",
        "domain": "QA",
        "level": 2,
        "short": "Automated tests run in CI",
        "full": "Prior to a commit being accepted, the project's CI/CD pipelines MUST run at least one automated test suite to ensure the changes meet expectations.",
        "help_md": """Add automated tests to CI pipeline.

**Remediation:**
1. Create test workflow in .github/workflows
2. Run tests on pull requests
3. Require tests to pass before merge
""",
        "security_severity": 5.0,
        "tags": ["testing", "ci-cd"],
        "location_hint": ".github/workflows",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 2 - Security Assessment (SA)
    # ==========================================================================
    "OSPS-SA-01.01": {
        "name": "DesignDocumentation",
        "domain": "SA",
        "level": 2,
        "short": "Design documentation exists",
        "full": "When the project has made a release, the project documentation MUST include design documentation demonstrating all actions and actors within the system.",
        "help_md": """Create architecture/design documentation.

**Remediation:**
1. Create docs/ARCHITECTURE.md
2. Document system components
3. Include data flow diagrams
4. Explain security boundaries
""",
        "security_severity": 4.0,
        "tags": ["architecture", "design"],
        "location_hint": "docs/ARCHITECTURE.md",
        "default_level": "warning",
    },
    "OSPS-SA-02.01": {
        "name": "ExternalInterfaceDocs",
        "domain": "SA",
        "level": 2,
        "short": "External interfaces documented",
        "full": "When the project has made a release, the project documentation MUST include descriptions of all external software interfaces.",
        "help_md": """Document external APIs and interfaces.

**Remediation:**
1. Create API documentation
2. Document all public endpoints
3. Include authentication requirements
4. Use OpenAPI/Swagger for REST APIs
""",
        "security_severity": 4.0,
        "tags": ["api", "documentation"],
        "location_hint": "docs/API.md",
        "default_level": "warning",
    },
    "OSPS-SA-03.01": {
        "name": "SecurityAssessment",
        "domain": "SA",
        "level": 2,
        "short": "Security assessment performed",
        "full": "When the project has made a release, the project MUST perform a security assessment to understand the most likely and impactful potential security problems.",
        "help_md": """Perform and document security assessment.

**Remediation:**
1. Conduct security review
2. Document findings in SECURITY.md
3. Create threat model
4. Track security issues
""",
        "security_severity": 6.0,
        "tags": ["security-assessment", "threat-model"],
        "location_hint": "SECURITY.md",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 2 - Vulnerability Management (VM)
    # ==========================================================================
    "OSPS-VM-01.01": {
        "name": "CVDPolicyWithTimeframe",
        "domain": "VM",
        "level": 2,
        "short": "CVD policy with timeframe",
        "full": "While active, the project documentation MUST include a policy for coordinated vulnerability disclosure with a clear timeframe for response.",
        "help_md": """Create CVD policy in SECURITY.md.

**Remediation:**
1. Add disclosure policy to SECURITY.md
2. Include response timeframe (e.g., 90 days)
3. Explain the disclosure process
""",
        "security_severity": 6.0,
        "tags": ["vulnerability-disclosure", "policy"],
        "location_hint": "SECURITY.md",
        "default_level": "warning",
    },
    "OSPS-VM-03.01": {
        "name": "PrivateVulnerabilityReporting",
        "domain": "VM",
        "level": 2,
        "short": "Private vulnerability reporting available",
        "full": "While active, the project documentation MUST provide a means for private vulnerability reporting directly to the security contacts.",
        "help_md": """Enable private vulnerability reporting.

**Remediation:**
1. Enable GitHub Private Vulnerability Reporting
2. Or provide security email in SECURITY.md
3. Consider using a PGP key for encrypted reports
""",
        "security_severity": 7.0,
        "tags": ["vulnerability-reporting", "security"],
        "location_hint": "SECURITY.md",
        "default_level": "warning",
    },
    "OSPS-VM-04.01": {
        "name": "PublicVulnerabilityData",
        "domain": "VM",
        "level": 2,
        "short": "Vulnerability data published publicly",
        "full": "While active, the project documentation MUST publicly publish data about discovered vulnerabilities.",
        "help_md": """Publish vulnerability information.

**Remediation:**
1. Enable GitHub Security Advisories
2. Publish CVEs for significant vulnerabilities
3. Include security fixes in changelogs
""",
        "security_severity": 5.0,
        "tags": ["vulnerability-disclosure", "cve"],
        "location_hint": "SECURITY.md",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 3 - Access Control (AC)
    # ==========================================================================
    "OSPS-AC-04.02": {
        "name": "MinimumCICDPrivileges",
        "domain": "AC",
        "level": 3,
        "short": "CI/CD uses minimum necessary privileges",
        "full": "When a job is assigned permissions in a CI/CD pipeline, the source code or configuration MUST only assign the minimum privileges necessary for the corresponding activity.",
        "help_md": """Minimize CI/CD job permissions.

**Remediation:**
1. Audit each job's actual permission needs
2. Remove unnecessary permissions
3. Use job-level instead of workflow-level permissions
4. Avoid using `write-all` or `admin` permissions
""",
        "security_severity": 6.0,
        "tags": ["ci-cd", "least-privilege"],
        "location_hint": ".github/workflows",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 3 - Build and Release (BR)
    # ==========================================================================
    "OSPS-BR-02.02": {
        "name": "AssetsAssociatedWithRelease",
        "domain": "BR",
        "level": 3,
        "short": "Assets clearly associated with release",
        "full": "When an official release is created, all assets within that release MUST be clearly associated with the release identifier or another unique identifier.",
        "help_md": """Ensure release assets are properly versioned.

**Remediation:**
1. Include version in asset filenames
2. Tag all release artifacts
3. Use consistent naming conventions
""",
        "security_severity": 3.0,
        "tags": ["release", "versioning"],
        "location_hint": "",
        "default_level": "note",
    },
    "OSPS-BR-07.02": {
        "name": "SecretsManagementPolicy",
        "domain": "BR",
        "level": 3,
        "short": "Secrets management policy defined",
        "full": "The project MUST define a policy for managing secrets and credentials used by the project, including guidelines for storing, accessing, and rotating them.",
        "help_md": """Document secrets management policy.

**Remediation:**
1. Create secrets management documentation
2. Define rotation schedules
3. Document access controls
4. Use secret management tools (Vault, AWS Secrets Manager)
""",
        "security_severity": 6.0,
        "tags": ["secrets", "policy"],
        "location_hint": "SECURITY.md",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 3 - Documentation (DO)
    # ==========================================================================
    "OSPS-DO-03.01": {
        "name": "ReleaseVerificationInstructions",
        "domain": "DO",
        "level": 3,
        "short": "Release verification instructions exist",
        "full": "When the project has made a release, the project documentation MUST contain instructions to verify the integrity and authenticity of the release assets.",
        "help_md": """Document how to verify releases.

**Remediation:**
1. Add verification section to README
2. Provide checksum verification commands
3. Document signature verification process
4. Include public keys or keyring locations
""",
        "security_severity": 5.0,
        "tags": ["verification", "integrity"],
        "location_hint": "README.md",
        "default_level": "warning",
    },
    "OSPS-DO-03.02": {
        "name": "AuthorVerificationInstructions",
        "domain": "DO",
        "level": 3,
        "short": "Author verification instructions exist",
        "full": "When the project has made a release, the project documentation MUST contain instructions to verify the expected identity of the person or process authoring the software release.",
        "help_md": """Document how to verify release author.

**Remediation:**
1. Document signing key ownership
2. Explain how to verify commit signatures
3. List authorized release managers
""",
        "security_severity": 5.0,
        "tags": ["verification", "identity"],
        "location_hint": "README.md",
        "default_level": "warning",
    },
    "OSPS-DO-04.01": {
        "name": "SupportScopeAndDuration",
        "domain": "DO",
        "level": 3,
        "short": "Support scope and duration documented",
        "full": "When the project has made a release, the project documentation MUST include a descriptive statement about the scope and duration of support for each release.",
        "help_md": """Document support policy.

**Remediation:**
1. Create SUPPORT.md
2. Define support windows for releases
3. Explain LTS vs regular release support
""",
        "security_severity": 3.0,
        "tags": ["support", "documentation"],
        "location_hint": "SUPPORT.md",
        "default_level": "note",
    },
    "OSPS-DO-05.01": {
        "name": "EndOfSecurityUpdatesNotice",
        "domain": "DO",
        "level": 3,
        "short": "End of security updates notice",
        "full": "When the project has made a release, the project documentation MUST provide a descriptive statement when releases or versions will no longer receive security updates.",
        "help_md": """Document end-of-life policy.

**Remediation:**
1. Add EOL section to SUPPORT.md
2. Announce deprecations in advance
3. Maintain list of supported versions
""",
        "security_severity": 4.0,
        "tags": ["eol", "support"],
        "location_hint": "SUPPORT.md",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 3 - Governance (GV)
    # ==========================================================================
    "OSPS-GV-04.01": {
        "name": "CollaboratorReviewPolicy",
        "domain": "GV",
        "level": 3,
        "short": "Collaborator review policy exists",
        "full": "While active, the project documentation MUST have a policy that code collaborators are reviewed prior to granting escalated permissions to sensitive resources.",
        "help_md": """Document collaborator vetting process.

**Remediation:**
1. Add vetting policy to GOVERNANCE.md
2. Define criteria for elevated access
3. Require sponsor/vouching for new maintainers
""",
        "security_severity": 5.0,
        "tags": ["governance", "access-control"],
        "location_hint": "GOVERNANCE.md",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 3 - Quality Assurance (QA)
    # ==========================================================================
    "OSPS-QA-02.02": {
        "name": "SBOMWithReleases",
        "domain": "QA",
        "level": 3,
        "short": "SBOM included with compiled releases",
        "full": "When the project has made a release, all compiled released software assets MUST be delivered with a software bill of materials.",
        "help_md": """Include SBOM with releases.

**Remediation:**
1. Generate SBOM during build (CycloneDX, SPDX)
2. Include SBOM in release assets
3. Automate SBOM generation in CI
""",
        "security_severity": 5.0,
        "tags": ["sbom", "supply-chain"],
        "location_hint": "",
        "default_level": "warning",
    },
    "OSPS-QA-04.02": {
        "name": "SubprojectSecurityRequirements",
        "domain": "QA",
        "level": 3,
        "short": "Subprojects have equivalent security",
        "full": "When the project has made a release comprising multiple source code repositories, all subprojects MUST enforce security requirements as strict or stricter than the primary codebase.",
        "help_md": """Ensure consistent security across subprojects.

**Remediation:**
1. Apply same security policies to all repos
2. Use shared CI/CD configurations
3. Audit subproject security regularly
""",
        "security_severity": 5.0,
        "tags": ["subprojects", "security"],
        "location_hint": "",
        "default_level": "warning",
    },
    "OSPS-QA-06.02": {
        "name": "TestDocumentation",
        "domain": "QA",
        "level": 3,
        "short": "Test instructions documented",
        "full": "While active, project's documentation MUST clearly document when and how tests are run.",
        "help_md": """Document testing process.

**Remediation:**
1. Add testing section to README or CONTRIBUTING
2. Explain how to run tests locally
3. Document CI test execution
""",
        "security_severity": 2.0,
        "tags": ["testing", "documentation"],
        "location_hint": "CONTRIBUTING.md",
        "default_level": "note",
    },
    "OSPS-QA-06.03": {
        "name": "TestPolicyForChanges",
        "domain": "QA",
        "level": 3,
        "short": "Test policy for changes",
        "full": "While active, the project's documentation MUST include a policy that all major changes to the software should add or update tests of the functionality.",
        "help_md": """Document test requirements for contributions.

**Remediation:**
1. Add testing policy to CONTRIBUTING.md
2. Require tests for new features
3. Enforce coverage thresholds
""",
        "security_severity": 3.0,
        "tags": ["testing", "policy"],
        "location_hint": "CONTRIBUTING.md",
        "default_level": "note",
    },
    "OSPS-QA-07.01": {
        "name": "NonAuthorApprovalRequired",
        "domain": "QA",
        "level": 3,
        "short": "Non-author approval required",
        "full": "When a commit is made to the primary branch, the project's version control system MUST require at least one non-author human approval of the changes before merging.",
        "help_md": """Require code review approval.

**Remediation:**
1. Configure branch protection
2. Require at least 1 approval
3. Enable 'Dismiss stale reviews'
4. Consider requiring CODEOWNERS approval
""",
        "security_severity": 7.0,
        "tags": ["code-review", "branch-protection"],
        "location_hint": ".github/settings.yml",
        "default_level": "error",
    },

    # ==========================================================================
    # Level 3 - Security Assessment (SA)
    # ==========================================================================
    "OSPS-SA-03.02": {
        "name": "ThreatModeling",
        "domain": "SA",
        "level": 3,
        "short": "Threat modeling performed",
        "full": "When the project has made a release, the project MUST perform a threat modeling and attack surface analysis to understand and protect against attacks on critical code paths.",
        "help_md": """Perform and document threat modeling.

**Remediation:**
1. Create threat model using STRIDE or similar
2. Document attack surfaces
3. Identify and mitigate threats
4. Store in docs/THREAT_MODEL.md
""",
        "security_severity": 6.0,
        "tags": ["threat-model", "security-assessment"],
        "location_hint": "docs/THREAT_MODEL.md",
        "default_level": "warning",
    },

    # ==========================================================================
    # Level 3 - Vulnerability Management (VM)
    # ==========================================================================
    "OSPS-VM-04.02": {
        "name": "VEXDocumentsOrPolicy",
        "domain": "VM",
        "level": 3,
        "short": "VEX documents or policy exists",
        "full": "While active, any vulnerabilities in the software components not affecting the project MUST be accounted for in a VEX document, augmenting the vulnerability report with non-exploitability details.",
        "help_md": """Create VEX documents for non-applicable vulnerabilities.

**Remediation:**
1. Create VEX policy in SECURITY.md
2. Generate VEX documents for dependencies
3. Explain why CVEs are not applicable
""",
        "security_severity": 4.0,
        "tags": ["vex", "vulnerability"],
        "location_hint": "SECURITY.md",
        "default_level": "warning",
    },
    "OSPS-VM-05.01": {
        "name": "SCARemediationThreshold",
        "domain": "VM",
        "level": 3,
        "short": "SCA remediation threshold defined",
        "full": "While active, the project documentation MUST include a policy that defines a threshold for remediation of SCA findings related to vulnerabilities and licenses.",
        "help_md": """Define SCA remediation policy.

**Remediation:**
1. Document severity thresholds for remediation
2. Define timeframes for fixing issues
3. Add to SECURITY.md
""",
        "security_severity": 5.0,
        "tags": ["sca", "policy"],
        "location_hint": "SECURITY.md",
        "default_level": "warning",
    },
    "OSPS-VM-05.02": {
        "name": "SCAViolationsBeforeRelease",
        "domain": "VM",
        "level": 3,
        "short": "SCA violations addressed before release",
        "full": "While active, the project documentation MUST include a policy to address SCA violations prior to any release.",
        "help_md": """Require SCA checks before release.

**Remediation:**
1. Add dependency-review-action to PR workflow
2. Block PRs with high severity vulnerabilities
3. Document release gating criteria
""",
        "security_severity": 6.0,
        "tags": ["sca", "release", "policy"],
        "location_hint": ".github/workflows",
        "default_level": "warning",
    },
    "OSPS-VM-05.03": {
        "name": "AutomatedDependencyScanning",
        "domain": "VM",
        "level": 3,
        "short": "Automated dependency scanning enabled",
        "full": "While active, all changes to the project's codebase MUST be automatically evaluated against a documented policy for malicious dependencies and known vulnerabilities, then blocked in the event of violations.",
        "help_md": """Enable automated dependency scanning.

**Remediation:**
1. Enable Dependabot alerts
2. Add dependency-review-action to PR workflow
3. Configure to block on high severity
""",
        "security_severity": 8.0,
        "tags": ["sca", "automation", "dependabot"],
        "location_hint": ".github/dependabot.yml",
        "default_level": "error",
    },
    "OSPS-VM-06.01": {
        "name": "SASTRemediationThreshold",
        "domain": "VM",
        "level": 3,
        "short": "SAST remediation threshold defined",
        "full": "While active, the project documentation MUST include a policy that defines a threshold for remediation of SAST findings.",
        "help_md": """Define SAST remediation policy.

**Remediation:**
1. Document severity thresholds
2. Define remediation timeframes
3. Add to SECURITY.md
""",
        "security_severity": 5.0,
        "tags": ["sast", "policy"],
        "location_hint": "SECURITY.md",
        "default_level": "warning",
    },
    "OSPS-VM-06.02": {
        "name": "AutomatedSASTInCI",
        "domain": "VM",
        "level": 3,
        "short": "Automated SAST in CI",
        "full": "While active, all changes to the project's codebase MUST be automatically evaluated against a documented policy for security weaknesses and blocked in the event of violations.",
        "help_md": """Enable automated SAST in CI.

**Remediation:**
1. Enable CodeQL or similar SAST
2. Configure code scanning workflow
3. Block PRs on high severity findings
""",
        "security_severity": 7.0,
        "tags": ["sast", "automation", "codeql"],
        "location_hint": ".github/workflows",
        "default_level": "warning",
    },
}


def get_rule(control_id: str) -> Optional[Dict[str, Any]]:
    """Get rule metadata for a control ID.

    Args:
        control_id: OSPS control ID (e.g., 'OSPS-AC-01.01')

    Returns:
        Rule metadata dictionary or None if not found
    """
    return OSPS_RULES.get(control_id)


def get_all_rules() -> Dict[str, Dict[str, Any]]:
    """Get all rule definitions.

    Returns:
        Complete rules catalog
    """
    return OSPS_RULES


def get_rules_by_level(level: int) -> Dict[str, Dict[str, Any]]:
    """Get rules filtered by maturity level.

    Args:
        level: Maturity level (1, 2, or 3)

    Returns:
        Rules for the specified level
    """
    return {
        control_id: rule
        for control_id, rule in OSPS_RULES.items()
        if rule["level"] == level
    }


def get_rules_by_domain(domain: str) -> Dict[str, Dict[str, Any]]:
    """Get rules filtered by domain.

    Args:
        domain: Domain code (AC, BR, DO, GV, LE, QA, SA, VM)

    Returns:
        Rules for the specified domain
    """
    return {
        control_id: rule
        for control_id, rule in OSPS_RULES.items()
        if rule["domain"] == domain
    }


def get_domain_info(domain: str) -> Optional[Dict[str, Any]]:
    """Get domain information.

    Args:
        domain: Domain code (AC, BR, DO, GV, LE, QA, SA, VM)

    Returns:
        Domain info dictionary or None
    """
    return DOMAIN_INFO.get(domain)


__all__ = [
    "OSPS_RULES",
    "DOMAIN_INFO",
    "get_rule",
    "get_all_rules",
    "get_rules_by_level",
    "get_rules_by_domain",
    "get_domain_info",
]
