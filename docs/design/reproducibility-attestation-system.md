# Reproducibility Attestation System for Computational Research

## Executive Summary

This document describes a system design for **darnit-reproducibility**, an extension to the darnit compliance framework that enables automated reproducibility verification and attestation for computational research software. The system addresses a critical gap in scientific computing: the inability to reliably rebuild and re-execute research software (e.g., protein folding simulations, molecular dynamics, genomics pipelines) in deterministic ways.

The system operates in two primary flows:

1. **Reproducibility Analysis & Environment Generation**: Ingests build provenance data from CNCF Witness (including future eBPF-based tracing) to analyze execution environments and generate reproducible environment definitions (containers, HPC configurations, Nix derivations)
2. **Re-execution & Attestation Storage**: Executes reproducible builds, generates cryptographically-signed reproducibility attestations, and stores them in OpenSSF GUAC for queryable provenance

---

## How It Works: End-to-End Workflow

This section explains the complete workflow in plain language, walking through how a researcher would use this system and how the components interact to achieve reproducible computational research.

### The Core Insight

The fundamental challenge in computational research reproducibility is that researchers don't know what they don't know. When a scientist runs a protein folding simulation on their university's HPC cluster, they might carefully document their Python version and the input data—but they often miss the dozens of implicit dependencies: the specific version of CUDA, the OpenBLAS library linked at compile time, the exact compiler flags, or even environment variables that subtly affect numerical precision.

Our system solves this by inverting the problem: instead of asking researchers to document everything (which they inevitably get wrong), we **observe everything automatically** during execution, then **analyze** what we observed to understand reproducibility requirements, and finally **generate** the artifacts needed to reproduce the computation elsewhere.

### Phase 1: Capturing Execution with Witness

When a researcher runs their computational workflow, they wrap it with CNCF Witness:

```bash
witness run \
    --step protein-fold \
    --attestations environment git product command_run \
    -- python run_simulation.py --input data.pdb
```

Witness acts as an observability layer around the build/execution. With its current attestors, it captures:

- **Environment**: Operating system, hostname, environment variables (PATH, LD_LIBRARY_PATH, CUDA paths)
- **Git state**: Exact commit hash, branch, remotes, tags
- **Command**: What was run, exit code, stdout/stderr hashes
- **Products**: Output files with their cryptographic digests

With the **future eBPF-based attestors** (currently in development), Witness will also capture:

- **Every process executed**: gcc invocations, nvcc calls, Python subprocess spawns
- **Every file read**: Header files, shared libraries, configuration files—with their digests
- **Every file written**: Intermediate build artifacts, output files
- **Network connections**: Package downloads during build, external API calls
- **Shared library loads**: The actual .so files loaded at runtime

This eBPF-based tracing is transformative because it captures the **actual execution** rather than what the build system *says* should happen. A Makefile might specify `gcc`, but eBPF tracing reveals that `/usr/bin/gcc-11` was actually invoked with specific flags, and that it read 47 header files from specific paths.

### Phase 2: Analyzing Provenance with Darnit

Once we have a Witness attestation bundle, Darnit's provenance analyzer processes it to understand what's actually required for reproducibility:

**Step 2.1: Building the Dependency Graph**

Darnit parses the Witness bundle and constructs a complete dependency graph. From the eBPF file access traces, it identifies:

- System packages accessed (by matching file paths to package managers)
- Python packages used (by analyzing imports and site-packages paths)
- Shared libraries loaded (from LD_LIBRARY_PATH and dlopen calls)
- Compilers and their versions (from execve traces)
- Hardware requirements (from CUDA library loads, MPI calls, GPU device access)

For example, if the eBPF trace shows:
- Read `/usr/local/cuda-12.0/include/cuda_runtime.h`
- Loaded `/usr/lib/x86_64-linux-gnu/libcudart.so.12`
- Executed `/usr/local/cuda-12.0/bin/nvcc --gpu-architecture=sm_80`

Darnit infers: "This computation requires CUDA 12.0, targets the Ampere GPU architecture (sm_80), and needs the CUDA runtime library."

**Step 2.2: Identifying Gaps with LLM Assistance**

Not everything can be deterministically inferred. When Darnit encounters ambiguity—perhaps a configuration file that could come from multiple packages, or a library that might have been statically compiled—it escalates to an LLM consultation.

Using darnit's sieve pipeline, the system presents the LLM with:
- The file in question
- Surrounding context from the provenance graph
- Possible interpretations

The LLM responds with its best inference and a confidence score. If confidence is too low, the system flags it for manual review.

**Step 2.3: Recommending Target Environments**

Based on the analysis, Darnit recommends the best environment type:

| Detected Requirements | Recommendation |
|----------------------|----------------|
| Standard Python + pip packages | **Container** (Docker/Singularity) |
| GPU + CUDA + single-node | **Container** with nvidia-container-toolkit |
| MPI + multi-node | **HPC job script** (Slurm/PBS) |
| Complex native dependencies | **Nix** for maximum reproducibility |
| Mixed MPI + GPU | **HPC** with Spack environment |

The recommendation includes a confidence score and explains the reasoning: "Recommending Singularity container (confidence: 0.87) because: requires CUDA 12.0 (detected), single-node execution (no MPI detected), common in HPC environments where Docker is unavailable."

### Phase 3: Generating Reproducible Environments

Based on the provenance analysis, Darnit generates the artifacts needed to reproduce the computation:

**For Containers (Docker/Singularity)**:

Darnit renders a Dockerfile that:
1. Starts from an appropriate base image (detected from CUDA version, OS, etc.)
2. Installs system packages identified in the dependency graph
3. Installs Python packages with pinned versions from the provenance
4. Sets environment variables captured by Witness
5. Copies source code and builds with the exact flags observed
6. Includes reproducibility settings (SOURCE_DATE_EPOCH, etc.)

For HPC environments, it also generates a parallel Singularity definition file, since many clusters don't allow Docker.

**For HPC Clusters (Slurm/PBS)**:

Darnit generates:
1. A job script with correct resource requests (GPUs, memory, nodes)
2. Module load commands mapped from the detected dependencies
3. Environment variable exports
4. A Spack environment file for dependency management

**For Nix**:

Darnit generates a `flake.nix` that pins the exact nixpkgs revision and declares all dependencies. This provides the strongest reproducibility guarantees—running `nix build` will produce identical results regardless of the host system.

### Phase 4: Verification Through Re-execution

This is where Darnit goes beyond just "generating a Dockerfile." The system actually **verifies** reproducibility by re-executing the computation and comparing results.

**Step 4.1: Execution with Tracing**

Darnit builds the generated environment and runs the computation inside it, again with Witness tracing enabled:

```bash
# Darnit orchestrates this internally
witness run \
    --step reproducibility-verification \
    --attestations environment git product command_run \
    -- docker run repro-build:latest python run_simulation.py
```

This produces a second Witness attestation bundle capturing what happened during the reproduction attempt.

**Step 4.2: Comparison and Verdict**

Darnit compares the original and reproduction attestation bundles:

**Bit-for-bit comparison**: Do the output file digests match exactly?
- If yes: The build is **fully reproducible**
- If no: Continue to semantic comparison

**Semantic comparison**: Are the outputs functionally equivalent?
- For scientific computations, Darnit can apply domain-specific comparisons
- Floating-point results might differ in the last few ULPs due to instruction ordering
- Trajectory files might have different timestamps but identical physics
- Machine learning models might have identical accuracy despite different weight values

**Discrepancy Analysis**: When outputs don't match, Darnit analyzes why:
- Compare environment attestations: Did a dependency version drift?
- Compare file access traces: Were different headers/libraries used?
- Flag numerical precision issues vs. actual logic differences

This analysis produces a **reproducibility verdict**:
- ✅ **Fully Reproducible**: Bit-for-bit identical outputs
- ✅ **Semantically Reproducible**: Outputs differ but are functionally equivalent
- ⚠️ **Partially Reproducible**: Some outputs match, others don't (with explanation)
- ❌ **Not Reproducible**: Significant differences (with root cause analysis)

### Phase 5: Remediation When Things Don't Match

When Darnit detects that a reproduction attempt failed or produced different results, it triggers a **remediation flow**:

**Step 5.1: Root Cause Identification**

Darnit's analyzer compares the two provenance graphs to identify discrepancies:

```text
Original environment:
  - Python 3.10.12
  - numpy 1.24.3 (linked against OpenBLAS 0.3.21)
  - CUDA 12.0, driver 525.85

Reproduction environment:
  - Python 3.10.12 ✓
  - numpy 1.24.3 ✓ (but linked against OpenBLAS 0.3.23!) ← DISCREPANCY
  - CUDA 12.0 ✓, driver 530.30 ← DISCREPANCY
```

**Step 5.2: Suggesting Fixes**

Based on the identified discrepancies, Darnit suggests remediation:

1. **Stricter pinning**: "Pin OpenBLAS to 0.3.21 in the Dockerfile"
2. **Environment isolation**: "Use a container that bundles the exact CUDA driver"
3. **Numerical tolerance**: "If results differ only in floating-point precision, consider adding tolerance to comparisons"

**Step 5.3: Iterative Refinement**

Darnit can automatically apply suggested fixes and re-run verification:

```text
Iteration 1: Reproduction failed (OpenBLAS version mismatch)
  → Applied fix: Pinned libopenblas-dev=0.3.21
Iteration 2: Reproduction failed (CUDA driver mismatch)
  → Applied fix: Using nvidia/cuda:12.0.0-base-ubuntu22.04 base image
Iteration 3: Reproduction succeeded (bit-for-bit match)
  → Generated final attestation
```

This iterative approach means researchers don't have to manually debug reproducibility failures—the system identifies and fixes issues automatically.

### Phase 6: Publishing Attestations to GUAC

Once reproducibility is verified, Darnit publishes the attestation to OpenSSF GUAC:

**Step 6.1: Creating the Attestation**

Darnit generates an in-toto attestation with a custom reproducibility predicate:

```json
{
  "_type": "https://in-toto.io/Statement/v1",
  "subject": [{"name": "protein_sim", "digest": {"sha256": "abc123..."}}],
  "predicateType": "https://darnit.dev/attestations/reproducibility/v1",
  "predicate": {
    "original": {"witness_bundle": "...", "timestamp": "2024-01-15T10:30:00Z"},
    "reproduction": {"witness_bundle": "...", "timestamp": "2024-01-20T14:45:00Z"},
    "verdict": {
      "reproducible": true,
      "level": "bit_for_bit",
      "confidence": 0.99
    },
    "environment_comparison": {...},
    "artifact_comparison": {...}
  }
}
```

**Step 6.2: Signing with Sigstore**

The attestation is cryptographically signed using Sigstore's keyless signing:
- Researcher authenticates via their institution's OIDC provider
- Sigstore issues a short-lived certificate
- The attestation is signed and the signature is logged in Rekor (transparency log)

This creates a **non-repudiable, publicly-verifiable claim** that this researcher verified reproducibility at this time.

**Step 6.3: Publishing to GUAC**

Darnit pushes the signed attestation to GUAC via its GraphQL API:

```graphql
mutation {
  ingestHasMetadata(
    subject: {artifact: {algorithm: "sha256", digest: "abc123..."}},
    hasMetadata: {
      key: "https://darnit.dev/attestations/reproducibility/v1",
      value: "{...attestation JSON...}",
      origin: "darnit-reproducibility",
      collector: "darnit"
    }
  )
}
```

Now the attestation is part of the GUAC graph, linked to the artifact it describes.

### Phase 7: Querying Reproducibility History

Once attestations are in GUAC, anyone can query them:

**"Has this software artifact ever been independently reproduced?"**

```graphql
query {
  HasMetadata(hasMetadataSpec: {
    subject: {artifact: {digest: "abc123..."}},
    key: "https://darnit.dev/attestations/reproducibility/v1"
  }) {
    id
    value  # Contains the full attestation
    timestamp
    origin  # Who verified it
  }
}
```

**"Show me all reproducibility verifications for this research group's outputs"**

**"What percentage of artifacts from this lab have been independently verified?"**

This transforms reproducibility from a binary "trust the paper" to a **queryable, cryptographically-verified property** of research software.

### The Feedback Loop

The system creates a virtuous cycle:

1. **Initial runs** are traced with Witness, capturing complete provenance
2. **Analysis** identifies what's needed for reproducibility
3. **Generation** creates environment definitions automatically
4. **Verification** attempts reproduction and identifies failures
5. **Remediation** fixes issues automatically or flags for human review
6. **Attestation** creates cryptographic proof of reproducibility
7. **Publication** makes the proof queryable in GUAC
8. **Future verifications** can build on existing attestations

Over time, this creates a **reproducibility knowledge graph** where:
- Software artifacts are linked to their build provenance
- Reproducibility attempts are recorded with their verdicts
- Common failure modes are identified across the research community
- Best practices emerge from successful reproduction patterns

### Example: A Day in the Life

**Dr. Chen publishes a protein folding paper:**

1. Her simulation already runs with Witness tracing (standard practice in her lab)
2. Before submission, she runs `darnit verify-reproducibility`
3. Darnit analyzes the provenance, generates a Singularity container, and verifies reproduction
4. Two iterations needed: fixed a floating numpy version and an unset random seed
5. The reproducibility attestation is signed and published to GUAC
6. Her paper includes a GUAC URI that reviewers can query

**Dr. Park wants to build on her work:**

1. He queries GUAC for her artifact's reproducibility attestations
2. Sees it was independently verified by three labs with bit-for-bit matches
3. Downloads the Singularity definition from the attestation
4. Runs it on his cluster—works first time
5. Makes modifications, runs Darnit to verify his version is also reproducible
6. Publishes his own attestation referencing hers

**Journal reviewer checks the submission:**

1. Queries GUAC for the artifact digest mentioned in the paper
2. Sees the full provenance chain: who built it, when, with what dependencies
3. Sees independent verification from multiple institutions
4. Can verify the signatures are valid and logged in Rekor
5. Has much higher confidence in the computational results

---

## Problem Statement

### The Reproducibility Crisis in Computational Science

Computational research software—protein folding simulations (AlphaFold, OpenMM), molecular dynamics (GROMACS, LAMMPS), genomics pipelines (BWA, GATK)—suffers from severe reproducibility challenges:

1. **Environment Opacity**: Researchers run computations without capturing complete environment state (system libraries, compiler versions, hardware configurations)
2. **Build Non-Determinism**: Software builds vary based on undocumented dependencies, floating version pins, and implicit system state
3. **Execution Variance**: Results differ across HPC clusters, cloud environments, and local machines due to numerical precision, threading, and hardware differences
4. **Verification Gap**: No standardized way to attest that a computational result was produced by a specific version of software in a known environment

### Current State

| Challenge | Current Approach | Gap |
|-----------|------------------|-----|
| Environment capture | Manual documentation, Dockerfiles | Incomplete, post-hoc, not verified |
| Build provenance | CI logs, makefiles | No cryptographic binding, lossy |
| Execution verification | "Works on my machine" | No attestation, not queryable |
| Result provenance | Paper citations | No machine-readable chain |

---

## System Architecture

### High-Level Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DARNIT-REPRODUCIBILITY                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     FLOW 1: ANALYSIS & GENERATION                    │   │
│  │                                                                       │   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐   │   │
│  │  │   WITNESS    │───▶│  PROVENANCE  │───▶│  ENVIRONMENT         │   │   │
│  │  │   INGESTOR   │    │  ANALYZER    │    │  GENERATOR           │   │   │
│  │  │              │    │              │    │                      │   │   │
│  │  │ • eBPF traces│    │ • Dependency │    │ • Dockerfile         │   │   │
│  │  │ • Attestors  │    │   graph      │    │ • Singularity.def    │   │   │
│  │  │ • Products   │    │ • Syscall    │    │ • Nix derivation     │   │   │
│  │  │ • Git state  │    │   analysis   │    │ • Spack spec         │   │   │
│  │  │              │    │ • LLM-assist │    │ • Slurm/PBS config   │   │   │
│  │  └──────────────┘    └──────────────┘    └──────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     FLOW 2: EXECUTION & ATTESTATION                  │   │
│  │                                                                       │   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐   │   │
│  │  │  EXECUTION   │───▶│ ATTESTATION  │───▶│      GUAC            │   │   │
│  │  │  ENGINE      │    │ GENERATOR    │    │      PUBLISHER       │   │   │
│  │  │              │    │              │    │                      │   │   │
│  │  │ • Container  │    │ • in-toto    │    │ • GraphQL ingest     │   │   │
│  │  │   runtime    │    │   statements │    │ • Artifact linking   │   │   │
│  │  │ • HPC submit │    │ • Sigstore   │    │ • Provenance chain   │   │   │
│  │  │ • Local exec │    │   signing    │    │ • Query interface    │   │   │
│  │  │ • Witness    │    │ • Repro      │    │                      │   │   │
│  │  │   tracing    │    │   predicate  │    │                      │   │   │
│  │  └──────────────┘    └──────────────┘    └──────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     SHARED INFRASTRUCTURE                            │   │
│  │                                                                       │   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐   │   │
│  │  │    SIEVE     │    │   CONFIG     │    │      MCP             │   │   │
│  │  │   PIPELINE   │    │   SYSTEM     │    │      SERVER          │   │   │
│  │  │              │    │              │    │                      │   │   │
│  │  │ • Determin.  │    │ • .project/  │    │ • analyze_repro      │   │   │
│  │  │ • Pattern    │    │ • repro.yaml │    │ • generate_env       │   │   │
│  │  │ • LLM        │    │ • witness    │    │ • execute_repro      │   │   │
│  │  │ • Manual     │    │   config     │    │ • store_attestation  │   │   │
│  │  └──────────────┘    └──────────────┘    └──────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL SYSTEMS                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │  CNCF WITNESS    │  │  OpenSSF GUAC    │  │  EXECUTION TARGETS       │  │
│  │                  │  │                  │  │                          │  │
│  │ • Build traces   │  │ • Graph DB       │  │ • Docker/Podman          │  │
│  │ • eBPF provenance│  │ • GraphQL API    │  │ • Singularity/Apptainer  │  │
│  │ • Attestation    │  │ • Artifact nodes │  │ • Slurm/PBS/LSF          │  │
│  │   bundles        │  │ • Query engine   │  │ • AWS Batch/GCP Batch    │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Flow 1: Reproducibility Analysis & Environment Generation

### 1.1 Witness Ingestor

The Witness Ingestor pulls build provenance data from CNCF Witness attestation bundles.

#### Data Sources

```yaml
witness_attestation_bundle:
  # Standard Witness attestors (available now)
  environment:
    os: "linux"
    hostname: "build-node-42"
    username: "researcher"
    variables:
      PATH: "/usr/local/cuda/bin:..."
      LD_LIBRARY_PATH: "/usr/local/cuda/lib64"
      CUDA_VISIBLE_DEVICES: "0,1"

  git:
    commit_hash: "abc123..."
    branch: "main"
    remotes:
      origin: "https://github.com/lab/protein-sim"
    tags: ["v2.1.0"]

  command_run:
    cmd: ["make", "-j8", "build"]
    exit_code: 0
    stdout_hash: "sha256:..."
    stderr_hash: "sha256:..."

  product:
    artifacts:
      - name: "protein_sim"
        digest: "sha256:..."
        mime_type: "application/x-executable"
      - name: "libsim.so"
        digest: "sha256:..."

  # Future eBPF-based attestors (in development)
  process_trace:
    execve_calls:
      - binary: "/usr/bin/gcc"
        args: ["-O3", "-march=native", "main.c"]
        timestamp: "2024-01-15T10:30:00Z"
      - binary: "/usr/bin/nvcc"
        args: ["--gpu-architecture=sm_80", "kernel.cu"]
        timestamp: "2024-01-15T10:30:05Z"

    file_access:
      reads:
        - path: "/usr/include/cuda.h"
          digest: "sha256:..."
        - path: "/usr/local/cuda-12.0/include/cuda_runtime.h"
          digest: "sha256:..."
      writes:
        - path: "./build/main.o"
          digest: "sha256:..."

    network_connections:
      - remote: "pypi.org:443"
        bytes_transferred: 1048576
      - remote: "conda.anaconda.org:443"
        bytes_transferred: 2097152

    shared_libraries:
      - path: "/usr/lib/libcudart.so.12.0"
        digest: "sha256:..."
      - path: "/usr/lib/libopenblas.so.0"
        digest: "sha256:..."
```

#### Ingestor Implementation

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/ingest/witness.py

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from pathlib import Path
import json

@dataclass
class WitnessBundle:
    """Parsed Witness attestation bundle."""
    attestation_type: str  # "https://witness.dev/attestations/..."
    subject: List[Dict[str, Any]]
    predicate: Dict[str, Any]

    # Extracted attestor data
    environment: Optional["EnvironmentAttestation"] = None
    git: Optional["GitAttestation"] = None
    command_run: Optional["CommandRunAttestation"] = None
    products: Optional[List["ProductAttestation"]] = None
    process_trace: Optional["ProcessTraceAttestation"] = None  # Future eBPF data

@dataclass
class ProcessTraceAttestation:
    """eBPF-captured process execution trace (future Witness capability)."""
    execve_calls: List["ExecveCall"]
    file_access: "FileAccessLog"
    network_connections: List["NetworkConnection"]
    shared_libraries: List["SharedLibrary"]

class WitnessIngestor:
    """Ingests Witness attestation bundles for reproducibility analysis."""

    def __init__(self, config: "ReproducibilityConfig"):
        self.config = config

    async def ingest_bundle(self, bundle_path: Path) -> WitnessBundle:
        """Parse and validate a Witness attestation bundle."""
        raw = json.loads(bundle_path.read_text())
        return self._parse_bundle(raw)

    async def ingest_from_archivista(
        self,
        artifact_digest: str,
        archivista_url: str = "https://archivista.example.com"
    ) -> WitnessBundle:
        """Fetch attestation from Witness Archivista server."""
        # Query Archivista GraphQL API for attestations about artifact
        pass

    async def ingest_from_guac(
        self,
        artifact_digest: str,
        guac_url: str
    ) -> List[WitnessBundle]:
        """Fetch existing attestations from GUAC for an artifact."""
        # Query GUAC GraphQL for HasSLSA and related attestations
        pass
```

### 1.2 Provenance Analyzer

The Provenance Analyzer processes Witness data to understand the complete dependency and execution environment.

#### Analysis Pipeline

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/analysis/provenance.py

from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional
from enum import Enum

class DependencyType(Enum):
    SYSTEM_PACKAGE = "system_package"      # apt, yum, etc.
    PYTHON_PACKAGE = "python_package"      # pip, conda
    SHARED_LIBRARY = "shared_library"      # .so files
    HEADER_FILE = "header_file"            # .h files
    COMPILER = "compiler"                  # gcc, nvcc, etc.
    RUNTIME = "runtime"                    # cuda, mpi, etc.
    DATA_FILE = "data_file"                # input data

class EnvironmentType(Enum):
    CONTAINER = "container"                # Docker, Singularity
    HPC_CLUSTER = "hpc_cluster"            # Slurm, PBS, LSF
    CLOUD_BATCH = "cloud_batch"            # AWS Batch, GCP Batch
    LOCAL = "local"                        # Local machine
    NIX = "nix"                            # Nix/NixOS

@dataclass
class DependencyNode:
    """A dependency in the provenance graph."""
    name: str
    version: Optional[str]
    digest: Optional[str]
    dep_type: DependencyType
    source: str  # Where this was detected (file_access, execve, etc.)
    children: List["DependencyNode"] = field(default_factory=list)

@dataclass
class ProvenanceGraph:
    """Complete provenance graph for a build."""
    root_artifact: str
    dependencies: List[DependencyNode]
    compilers: List[DependencyNode]
    runtimes: List[DependencyNode]
    environment_vars: Dict[str, str]
    hardware_requirements: "HardwareRequirements"

@dataclass
class HardwareRequirements:
    """Detected hardware requirements."""
    gpu_required: bool = False
    gpu_type: Optional[str] = None  # "nvidia", "amd", "intel"
    gpu_arch: Optional[str] = None  # "sm_80", "gfx90a"
    min_memory_gb: Optional[float] = None
    mpi_required: bool = False
    mpi_implementation: Optional[str] = None  # "openmpi", "mpich", "intel-mpi"

@dataclass
class EnvironmentRecommendation:
    """Recommended environment type with confidence."""
    env_type: EnvironmentType
    confidence: float
    reasoning: str
    blockers: List[str]  # Why other types won't work

class ProvenanceAnalyzer:
    """Analyzes Witness provenance to understand reproducibility requirements."""

    def __init__(self, config: "ReproducibilityConfig"):
        self.config = config
        self.sieve = SieveOrchestrator()  # Reuse darnit's verification pipeline

    async def analyze(self, bundle: WitnessBundle) -> ProvenanceGraph:
        """Build complete provenance graph from Witness bundle."""
        graph = ProvenanceGraph(
            root_artifact=bundle.subject[0]["digest"]["sha256"],
            dependencies=[],
            compilers=[],
            runtimes=[],
            environment_vars={},
            hardware_requirements=HardwareRequirements()
        )

        # Phase 1: Deterministic extraction from attestor data
        await self._extract_from_environment(bundle.environment, graph)
        await self._extract_from_products(bundle.products, graph)

        # Phase 2: Pattern-based analysis of process traces
        if bundle.process_trace:
            await self._analyze_process_trace(bundle.process_trace, graph)

        # Phase 3: LLM-assisted gap filling
        gaps = self._identify_gaps(graph)
        if gaps:
            await self._llm_fill_gaps(gaps, graph, bundle)

        return graph

    async def recommend_environment(
        self,
        graph: ProvenanceGraph
    ) -> List[EnvironmentRecommendation]:
        """Recommend target environment types based on provenance analysis."""
        recommendations = []

        # Score each environment type
        for env_type in EnvironmentType:
            score, reasoning, blockers = await self._score_environment(
                env_type, graph
            )
            if score > 0.3:  # Minimum viability threshold
                recommendations.append(EnvironmentRecommendation(
                    env_type=env_type,
                    confidence=score,
                    reasoning=reasoning,
                    blockers=blockers
                ))

        return sorted(recommendations, key=lambda r: r.confidence, reverse=True)

    async def _score_environment(
        self,
        env_type: EnvironmentType,
        graph: ProvenanceGraph
    ) -> tuple[float, str, List[str]]:
        """Score viability of an environment type for this provenance."""
        blockers = []
        score = 1.0
        reasoning_parts = []

        if env_type == EnvironmentType.CONTAINER:
            # Containers work well for most cases
            if graph.hardware_requirements.gpu_required:
                # GPU containers are possible but need nvidia-container-toolkit
                score *= 0.9
                reasoning_parts.append("GPU support requires nvidia-container-toolkit")
            if graph.hardware_requirements.mpi_required:
                # MPI in containers is tricky
                score *= 0.7
                reasoning_parts.append("MPI requires careful network configuration")

        elif env_type == EnvironmentType.HPC_CLUSTER:
            # HPC clusters are best for MPI and specialized hardware
            if graph.hardware_requirements.mpi_required:
                score *= 1.1  # Bonus for MPI
                reasoning_parts.append("Native MPI support")
            if not graph.hardware_requirements.gpu_required:
                score *= 0.8  # Slight penalty for not needing HPC features

        elif env_type == EnvironmentType.NIX:
            # Nix provides best reproducibility but has learning curve
            score = 0.95  # High base score for reproducibility
            reasoning_parts.append("Best-in-class reproducibility guarantees")
            # Check if all deps are in nixpkgs
            # (would need LLM or database lookup)

        return (
            min(score, 1.0),
            "; ".join(reasoning_parts) if reasoning_parts else "Standard configuration",
            blockers
        )
```

### 1.3 Environment Generator

Generates environment definitions based on the provenance analysis.

#### Generator Interface

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/generate/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

@dataclass
class GeneratedEnvironment:
    """Generated environment definition."""
    env_type: EnvironmentType
    primary_file: str           # Main definition file content
    primary_filename: str       # e.g., "Dockerfile", "default.nix"
    auxiliary_files: Dict[str, str]  # Additional files needed
    build_instructions: str     # Human-readable build steps
    verification_steps: List[str]  # Steps to verify the environment
    confidence: float           # How confident we are in this generation

class EnvironmentGenerator(ABC):
    """Base class for environment generators."""

    @abstractmethod
    async def generate(
        self,
        graph: ProvenanceGraph,
        project_config: "ProjectConfig"
    ) -> GeneratedEnvironment:
        """Generate environment definition from provenance graph."""
        pass

    @abstractmethod
    def can_generate(self, graph: ProvenanceGraph) -> tuple[bool, str]:
        """Check if this generator can handle the given provenance."""
        pass
```

#### Container Generator (Docker/Singularity)

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/generate/container.py

class ContainerGenerator(EnvironmentGenerator):
    """Generates Dockerfile or Singularity definition files."""

    async def generate(
        self,
        graph: ProvenanceGraph,
        project_config: "ProjectConfig"
    ) -> GeneratedEnvironment:
        # Determine base image
        base_image = await self._select_base_image(graph)

        # Generate package installation commands
        system_deps = self._generate_system_deps(graph)
        python_deps = self._generate_python_deps(graph)

        # Generate Dockerfile
        dockerfile = self._render_dockerfile(
            base_image=base_image,
            system_deps=system_deps,
            python_deps=python_deps,
            env_vars=graph.environment_vars,
            hardware=graph.hardware_requirements
        )

        # Also generate Singularity definition for HPC compatibility
        singularity_def = self._render_singularity_def(
            base_image=base_image,
            system_deps=system_deps,
            python_deps=python_deps,
            env_vars=graph.environment_vars,
            hardware=graph.hardware_requirements
        )

        return GeneratedEnvironment(
            env_type=EnvironmentType.CONTAINER,
            primary_file=dockerfile,
            primary_filename="Dockerfile.reproducible",
            auxiliary_files={
                "Singularity.def": singularity_def,
                "requirements.txt": self._generate_requirements_txt(graph),
                ".dockerignore": self._generate_dockerignore(),
            },
            build_instructions=self._generate_build_instructions(base_image),
            verification_steps=self._generate_verification_steps(graph),
            confidence=self._calculate_confidence(graph)
        )

    def _render_dockerfile(
        self,
        base_image: str,
        system_deps: List[str],
        python_deps: List[str],
        env_vars: Dict[str, str],
        hardware: HardwareRequirements
    ) -> str:
        lines = [
            f"# Auto-generated by darnit-reproducibility",
            f"# Provenance: {self._provenance_comment()}",
            f"FROM {base_image}",
            "",
        ]

        # Environment variables for reproducibility
        lines.extend([
            "# Reproducibility settings",
            "ENV PYTHONDONTWRITEBYTECODE=1",
            "ENV PYTHONUNBUFFERED=1",
            "ENV SOURCE_DATE_EPOCH=0",
            "",
        ])

        # Captured environment variables
        for key, value in env_vars.items():
            if self._should_include_env_var(key):
                lines.append(f"ENV {key}={value}")
        lines.append("")

        # System dependencies
        if system_deps:
            lines.extend([
                "# System dependencies (from provenance analysis)",
                "RUN apt-get update && apt-get install -y \\",
                *[f"    {dep} \\" for dep in system_deps[:-1]],
                f"    {system_deps[-1]} \\",
                "    && rm -rf /var/lib/apt/lists/*",
                "",
            ])

        # GPU support
        if hardware.gpu_required:
            lines.extend(self._generate_gpu_setup(hardware))

        # Python dependencies
        if python_deps:
            lines.extend([
                "# Python dependencies (pinned versions from provenance)",
                "COPY requirements.txt /tmp/requirements.txt",
                "RUN pip install --no-cache-dir -r /tmp/requirements.txt",
                "",
            ])

        # Copy source and build
        lines.extend([
            "# Application source",
            "WORKDIR /app",
            "COPY . .",
            "",
            "# Build command (from provenance)",
            f"RUN {self._build_command}",
            "",
        ])

        return "\n".join(lines)
```

#### HPC Generator (Slurm/PBS)

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/generate/hpc.py

class HPCGenerator(EnvironmentGenerator):
    """Generates HPC job scripts and environment modules."""

    async def generate(
        self,
        graph: ProvenanceGraph,
        project_config: "ProjectConfig"
    ) -> GeneratedEnvironment:
        # Detect HPC scheduler from config or provenance
        scheduler = self._detect_scheduler(project_config)

        # Map dependencies to environment modules
        modules = await self._map_to_modules(graph)

        # Generate job script
        if scheduler == "slurm":
            job_script = self._render_slurm_script(graph, modules)
            filename = "run_reproducible.slurm"
        elif scheduler == "pbs":
            job_script = self._render_pbs_script(graph, modules)
            filename = "run_reproducible.pbs"
        else:
            job_script = self._render_generic_script(graph, modules)
            filename = "run_reproducible.sh"

        # Generate Spack environment for dependency management
        spack_yaml = self._generate_spack_env(graph)

        return GeneratedEnvironment(
            env_type=EnvironmentType.HPC_CLUSTER,
            primary_file=job_script,
            primary_filename=filename,
            auxiliary_files={
                "spack.yaml": spack_yaml,
                "modules.txt": "\n".join(modules),
                "environment.sh": self._generate_env_script(graph),
            },
            build_instructions=self._generate_hpc_instructions(scheduler),
            verification_steps=self._generate_hpc_verification(graph),
            confidence=self._calculate_confidence(graph)
        )

    def _render_slurm_script(
        self,
        graph: ProvenanceGraph,
        modules: List[str]
    ) -> str:
        hw = graph.hardware_requirements

        lines = [
            "#!/bin/bash",
            "#SBATCH --job-name=reproducible_run",
            f"#SBATCH --output=repro_%j.out",
            f"#SBATCH --error=repro_%j.err",
        ]

        # Resource requirements from provenance
        if hw.gpu_required:
            lines.append(f"#SBATCH --gres=gpu:1")
            if hw.gpu_type:
                lines.append(f"#SBATCH --constraint={hw.gpu_type}")

        if hw.mpi_required:
            lines.append("#SBATCH --ntasks=4")  # Default, should be parameterized
            lines.append("#SBATCH --cpus-per-task=1")

        if hw.min_memory_gb:
            lines.append(f"#SBATCH --mem={int(hw.min_memory_gb)}G")

        lines.extend([
            "",
            "# Load required modules",
            *[f"module load {mod}" for mod in modules],
            "",
            "# Set reproducibility environment",
            *[f"export {k}={v}" for k, v in graph.environment_vars.items()],
            "",
            "# Run the computation",
            f"{self._run_command(graph)}",
        ])

        return "\n".join(lines)
```

#### Nix Generator

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/generate/nix.py

class NixGenerator(EnvironmentGenerator):
    """Generates Nix derivations for maximum reproducibility."""

    async def generate(
        self,
        graph: ProvenanceGraph,
        project_config: "ProjectConfig"
    ) -> GeneratedEnvironment:
        # Map dependencies to nixpkgs
        nix_deps = await self._map_to_nixpkgs(graph)

        # Generate flake.nix
        flake = self._render_flake(graph, nix_deps)

        # Generate default.nix for non-flake users
        default_nix = self._render_default_nix(graph, nix_deps)

        return GeneratedEnvironment(
            env_type=EnvironmentType.NIX,
            primary_file=flake,
            primary_filename="flake.nix",
            auxiliary_files={
                "default.nix": default_nix,
                "shell.nix": self._render_shell_nix(graph, nix_deps),
            },
            build_instructions=self._generate_nix_instructions(),
            verification_steps=self._generate_nix_verification(graph),
            confidence=self._calculate_confidence(graph)
        )

    def _render_flake(
        self,
        graph: ProvenanceGraph,
        nix_deps: List["NixPackage"]
    ) -> str:
        return f'''{{
  description = "Reproducible environment generated by darnit-reproducibility";

  inputs = {{
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
    flake-utils.url = "github:numtide/flake-utils";
  }};

  outputs = {{ self, nixpkgs, flake-utils }}:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {{ inherit system; }};
      in {{
        devShells.default = pkgs.mkShell {{
          buildInputs = with pkgs; [
            {self._format_nix_deps(nix_deps)}
          ];

          shellHook = \'\'
            {self._format_env_vars(graph.environment_vars)}
          \'\';
        }};

        packages.default = pkgs.stdenv.mkDerivation {{
          pname = "{graph.root_artifact}";
          version = "reproducible";

          src = ./.;

          buildInputs = with pkgs; [
            {self._format_nix_deps(nix_deps)}
          ];

          buildPhase = \'\'
            {self._build_command}
          \'\';

          installPhase = \'\'
            mkdir -p $out/bin
            cp result $out/bin/
          \'\';
        }};
      }}
    );
}}'''
```

---

## Flow 2: Re-execution & Attestation Generation

### 2.1 Execution Engine

Executes builds in generated environments with Witness tracing.

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/execute/engine.py

from dataclasses import dataclass
from typing import Optional, List
from enum import Enum
import asyncio
import subprocess

class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"

@dataclass
class ExecutionResult:
    """Result of a reproducible execution."""
    status: ExecutionStatus
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    artifacts_produced: List["ArtifactDigest"]
    witness_bundle: Optional["WitnessBundle"]
    environment_digest: str  # Hash of the execution environment

@dataclass
class ArtifactDigest:
    """Digest of a produced artifact."""
    name: str
    path: str
    sha256: str
    size_bytes: int

class ExecutionEngine:
    """Executes reproducible builds with Witness tracing."""

    def __init__(self, config: "ReproducibilityConfig"):
        self.config = config

    async def execute(
        self,
        environment: GeneratedEnvironment,
        command: str,
        working_dir: Path,
        timeout_seconds: int = 3600
    ) -> ExecutionResult:
        """Execute command in reproducible environment with Witness tracing."""

        if environment.env_type == EnvironmentType.CONTAINER:
            return await self._execute_container(
                environment, command, working_dir, timeout_seconds
            )
        elif environment.env_type == EnvironmentType.HPC_CLUSTER:
            return await self._execute_hpc(
                environment, command, working_dir, timeout_seconds
            )
        elif environment.env_type == EnvironmentType.NIX:
            return await self._execute_nix(
                environment, command, working_dir, timeout_seconds
            )
        else:
            return await self._execute_local(
                environment, command, working_dir, timeout_seconds
            )

    async def _execute_container(
        self,
        environment: GeneratedEnvironment,
        command: str,
        working_dir: Path,
        timeout_seconds: int
    ) -> ExecutionResult:
        """Execute in container with Witness tracing."""

        # Build the container first
        build_cmd = [
            "docker", "build",
            "-f", str(working_dir / environment.primary_filename),
            "-t", "repro-build:latest",
            str(working_dir)
        ]

        build_result = await self._run_subprocess(build_cmd)
        if build_result.returncode != 0:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                exit_code=build_result.returncode,
                stdout=build_result.stdout,
                stderr=build_result.stderr,
                duration_seconds=0,
                artifacts_produced=[],
                witness_bundle=None,
                environment_digest=""
            )

        # Run with Witness tracing
        run_cmd = [
            "witness", "run",
            "--step", "reproducible-execution",
            "--attestations", "environment", "git", "product",
            "--",
            "docker", "run",
            "--rm",
            "-v", f"{working_dir}:/workspace",
            "-w", "/workspace",
            "repro-build:latest",
            command
        ]

        start_time = asyncio.get_event_loop().time()
        result = await self._run_subprocess(run_cmd, timeout=timeout_seconds)
        duration = asyncio.get_event_loop().time() - start_time

        # Parse Witness output for attestation bundle
        witness_bundle = await self._parse_witness_output(result)

        # Collect artifact digests
        artifacts = await self._collect_artifacts(working_dir)

        return ExecutionResult(
            status=ExecutionStatus.SUCCESS if result.returncode == 0 else ExecutionStatus.FAILED,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            artifacts_produced=artifacts,
            witness_bundle=witness_bundle,
            environment_digest=await self._hash_environment(environment)
        )
```

### 2.2 Attestation Generator

Generates reproducibility attestations in in-toto format.

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/attestation/reproducibility.py

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
import json

@dataclass
class ReproducibilityPredicate:
    """in-toto predicate for reproducibility attestations."""

    # Predicate type
    predicate_type: str = "https://darnit.dev/attestations/reproducibility/v1"

    # Original execution being reproduced
    original: Dict[str, Any] = field(default_factory=dict)

    # Reproduction execution
    reproduction: Dict[str, Any] = field(default_factory=dict)

    # Environment comparison
    environment_comparison: Dict[str, Any] = field(default_factory=dict)

    # Artifact comparison
    artifact_comparison: Dict[str, Any] = field(default_factory=dict)

    # Reproducibility verdict
    verdict: Dict[str, Any] = field(default_factory=dict)

class ReproducibilityAttestationGenerator:
    """Generates reproducibility attestations."""

    def __init__(self, config: "ReproducibilityConfig"):
        self.config = config

    def generate_attestation(
        self,
        original_bundle: WitnessBundle,
        execution_result: ExecutionResult,
        environment: GeneratedEnvironment,
        provenance_graph: ProvenanceGraph
    ) -> Dict[str, Any]:
        """Generate in-toto reproducibility attestation."""

        # Build predicate
        predicate = ReproducibilityPredicate(
            original=self._format_original(original_bundle),
            reproduction=self._format_reproduction(execution_result),
            environment_comparison=self._compare_environments(
                original_bundle, execution_result, environment
            ),
            artifact_comparison=self._compare_artifacts(
                original_bundle.products, execution_result.artifacts_produced
            ),
            verdict=self._determine_verdict(
                original_bundle, execution_result
            )
        )

        # Build in-toto statement
        statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "subject": [
                {
                    "name": artifact.name,
                    "digest": {"sha256": artifact.sha256}
                }
                for artifact in execution_result.artifacts_produced
            ],
            "predicateType": predicate.predicate_type,
            "predicate": {
                "assessor": {
                    "name": "darnit-reproducibility",
                    "version": self.config.version,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                },
                "original": predicate.original,
                "reproduction": predicate.reproduction,
                "environment_comparison": predicate.environment_comparison,
                "artifact_comparison": predicate.artifact_comparison,
                "verdict": predicate.verdict
            }
        }

        return statement

    def _compare_environments(
        self,
        original: WitnessBundle,
        result: ExecutionResult,
        environment: GeneratedEnvironment
    ) -> Dict[str, Any]:
        """Compare original and reproduction environments."""
        return {
            "environment_type": {
                "original": self._detect_env_type(original),
                "reproduction": environment.env_type.value
            },
            "dependencies": {
                "matched": [],  # Dependencies that match exactly
                "version_drift": [],  # Same package, different version
                "missing": [],  # In original but not reproduction
                "added": []  # In reproduction but not original
            },
            "environment_digest": {
                "original": self._hash_original_env(original),
                "reproduction": result.environment_digest,
                "match": False  # Will be computed
            }
        }

    def _compare_artifacts(
        self,
        original_products: List["ProductAttestation"],
        reproduced_artifacts: List[ArtifactDigest]
    ) -> Dict[str, Any]:
        """Compare original and reproduced artifacts."""
        comparison = {
            "artifacts": [],
            "bit_for_bit_reproducible": True,
            "semantic_reproducible": True,  # Same outputs modulo timestamps etc
            "reproduction_rate": 0.0
        }

        # Match artifacts by name
        for orig in original_products:
            match = next(
                (a for a in reproduced_artifacts if a.name == orig.name),
                None
            )

            if match:
                artifact_match = {
                    "name": orig.name,
                    "original_digest": orig.digest,
                    "reproduced_digest": match.sha256,
                    "bit_for_bit_match": orig.digest == match.sha256,
                    "size_match": True  # Compare sizes
                }
                comparison["artifacts"].append(artifact_match)

                if not artifact_match["bit_for_bit_match"]:
                    comparison["bit_for_bit_reproducible"] = False
            else:
                comparison["artifacts"].append({
                    "name": orig.name,
                    "original_digest": orig.digest,
                    "reproduced_digest": None,
                    "status": "not_reproduced"
                })
                comparison["bit_for_bit_reproducible"] = False
                comparison["semantic_reproducible"] = False

        # Calculate reproduction rate
        matched = sum(1 for a in comparison["artifacts"] if a.get("bit_for_bit_match"))
        comparison["reproduction_rate"] = matched / len(original_products) if original_products else 0

        return comparison

    def _determine_verdict(
        self,
        original: WitnessBundle,
        result: ExecutionResult
    ) -> Dict[str, Any]:
        """Determine reproducibility verdict."""
        return {
            "reproducible": result.status == ExecutionStatus.SUCCESS,
            "reproducibility_level": self._calculate_level(original, result),
            "confidence": self._calculate_confidence(original, result),
            "issues": self._identify_issues(original, result),
            "recommendations": self._generate_recommendations(original, result)
        }
```

### 2.3 GUAC Publisher

Publishes attestations to OpenSSF GUAC.

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/publish/guac.py

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import httpx
import json

@dataclass
class GUACPublishResult:
    """Result of publishing to GUAC."""
    success: bool
    artifact_id: Optional[str]
    attestation_id: Optional[str]
    graph_uri: Optional[str]
    error: Optional[str]

class GUACPublisher:
    """Publishes attestations to OpenSSF GUAC."""

    def __init__(self, config: "ReproducibilityConfig"):
        self.config = config
        self.guac_url = config.guac_url
        self.graphql_endpoint = f"{self.guac_url}/query"

    async def publish_attestation(
        self,
        attestation: Dict[str, Any],
        signed_bundle: Optional[bytes] = None
    ) -> GUACPublishResult:
        """Publish attestation to GUAC."""

        async with httpx.AsyncClient() as client:
            # First, ensure the artifact exists in GUAC
            artifact_id = await self._ensure_artifact(
                client,
                attestation["subject"][0]
            )

            # Then ingest the attestation
            # GUAC accepts in-toto attestations via its collector/certifier system
            ingest_result = await self._ingest_attestation(
                client,
                attestation,
                signed_bundle
            )

            if not ingest_result["success"]:
                return GUACPublishResult(
                    success=False,
                    artifact_id=artifact_id,
                    attestation_id=None,
                    graph_uri=None,
                    error=ingest_result.get("error")
                )

            # Create HasMetadata linking attestation to artifact
            metadata_result = await self._create_metadata_link(
                client,
                artifact_id,
                attestation
            )

            return GUACPublishResult(
                success=True,
                artifact_id=artifact_id,
                attestation_id=ingest_result["id"],
                graph_uri=f"{self.guac_url}/artifact/{artifact_id}",
                error=None
            )

    async def _ensure_artifact(
        self,
        client: httpx.AsyncClient,
        subject: Dict[str, Any]
    ) -> str:
        """Ensure artifact exists in GUAC, create if not."""

        query = """
        mutation IngestArtifact($artifact: ArtifactInputSpec!) {
            ingestArtifact(artifact: $artifact)
        }
        """

        variables = {
            "artifact": {
                "algorithm": "sha256",
                "digest": subject["digest"]["sha256"]
            }
        }

        response = await client.post(
            self.graphql_endpoint,
            json={"query": query, "variables": variables}
        )

        data = response.json()
        return data["data"]["ingestArtifact"]

    async def _ingest_attestation(
        self,
        client: httpx.AsyncClient,
        attestation: Dict[str, Any],
        signed_bundle: Optional[bytes]
    ) -> Dict[str, Any]:
        """Ingest attestation into GUAC."""

        # GUAC accepts SLSA/in-toto attestations via HasSLSA
        # For custom predicates, we use HasMetadata

        if attestation["predicateType"].startswith("https://slsa.dev"):
            return await self._ingest_slsa(client, attestation)
        else:
            # Custom predicate - use HasMetadata
            return await self._ingest_custom_attestation(client, attestation)

    async def _ingest_custom_attestation(
        self,
        client: httpx.AsyncClient,
        attestation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ingest custom attestation type via HasMetadata."""

        # GUAC's HasMetadata allows attaching arbitrary metadata to artifacts
        query = """
        mutation IngestHasMetadata(
            $subject: PackageSourceOrArtifactInput!,
            $pkgMatchType: MatchFlags!,
            $hasMetadata: HasMetadataInputSpec!
        ) {
            ingestHasMetadata(
                subject: $subject,
                pkgMatchType: $pkgMatchType,
                hasMetadata: $hasMetadata
            )
        }
        """

        # Convert attestation to GUAC format
        variables = {
            "subject": {
                "artifact": {
                    "algorithm": "sha256",
                    "digest": attestation["subject"][0]["digest"]["sha256"]
                }
            },
            "pkgMatchType": {"pkg": "SPECIFIC_VERSION"},
            "hasMetadata": {
                "key": attestation["predicateType"],
                "value": json.dumps(attestation["predicate"]),
                "timestamp": attestation["predicate"]["assessor"]["timestamp"],
                "justification": "Reproducibility attestation from darnit",
                "origin": "darnit-reproducibility",
                "collector": "darnit"
            }
        }

        response = await client.post(
            self.graphql_endpoint,
            json={"query": query, "variables": variables}
        )

        if response.status_code == 200:
            data = response.json()
            if "errors" in data:
                return {"success": False, "error": data["errors"]}
            return {"success": True, "id": data["data"]["ingestHasMetadata"]}
        else:
            return {"success": False, "error": response.text}

    async def query_reproducibility_history(
        self,
        artifact_digest: str
    ) -> List[Dict[str, Any]]:
        """Query GUAC for reproducibility history of an artifact."""

        query = """
        query GetReproducibilityHistory($filter: HasMetadataSpec!) {
            HasMetadata(hasMetadataSpec: $filter) {
                id
                subject {
                    ... on Artifact {
                        algorithm
                        digest
                    }
                }
                key
                value
                timestamp
                origin
            }
        }
        """

        variables = {
            "filter": {
                "subject": {
                    "artifact": {
                        "algorithm": "sha256",
                        "digest": artifact_digest
                    }
                },
                "key": "https://darnit.dev/attestations/reproducibility/v1"
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.graphql_endpoint,
                json={"query": query, "variables": variables}
            )

            data = response.json()
            return [
                {
                    "id": m["id"],
                    "attestation": json.loads(m["value"]),
                    "timestamp": m["timestamp"]
                }
                for m in data.get("data", {}).get("HasMetadata", [])
            ]
```

---

## MCP Server Interface

### Tool Definitions

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/server/tools.py

REPRODUCIBILITY_TOOLS = [
    {
        "name": "analyze_reproducibility",
        "description": """
        Analyze a software project for reproducibility using Witness provenance data.

        This tool:
        1. Ingests Witness attestation bundles (including future eBPF traces)
        2. Builds a complete provenance graph
        3. Identifies reproducibility challenges
        4. Recommends target environments (container, HPC, Nix)

        Args:
            local_path: Path to the repository
            witness_bundle: Path to Witness attestation bundle (optional)
            archivista_url: URL to fetch attestations from Archivista (optional)
            artifact_digest: Digest of artifact to analyze (optional)

        Returns:
            Analysis results including:
            - Provenance graph summary
            - Dependency analysis
            - Hardware requirements
            - Environment recommendations
            - Reproducibility score
        """,
        "inputSchema": {
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "default": "."},
                "witness_bundle": {"type": "string"},
                "archivista_url": {"type": "string"},
                "artifact_digest": {"type": "string"}
            }
        }
    },
    {
        "name": "generate_reproducible_environment",
        "description": """
        Generate a reproducible environment definition based on provenance analysis.

        Supports:
        - Dockerfile / Singularity.def (containers)
        - Slurm/PBS job scripts (HPC)
        - flake.nix / default.nix (Nix)
        - spack.yaml (Spack)

        Args:
            local_path: Path to the repository
            target_env: Target environment type (container, hpc, nix, auto)
            witness_bundle: Path to Witness attestation bundle
            output_dir: Where to write generated files

        Returns:
            Generated environment files with build instructions
        """,
        "inputSchema": {
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "default": "."},
                "target_env": {
                    "type": "string",
                    "enum": ["container", "hpc", "nix", "auto"],
                    "default": "auto"
                },
                "witness_bundle": {"type": "string"},
                "output_dir": {"type": "string", "default": "."}
            },
            "required": ["witness_bundle"]
        }
    },
    {
        "name": "execute_reproducible_build",
        "description": """
        Execute a reproducible build with Witness tracing and generate attestations.

        This tool:
        1. Builds the generated environment
        2. Executes the build command with Witness tracing
        3. Compares artifacts with original build
        4. Generates reproducibility attestation

        Args:
            local_path: Path to the repository
            environment_file: Path to generated environment definition
            command: Build command to execute
            original_bundle: Original Witness bundle for comparison

        Returns:
            Execution results and reproducibility attestation
        """,
        "inputSchema": {
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "default": "."},
                "environment_file": {"type": "string"},
                "command": {"type": "string"},
                "original_bundle": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 3600}
            },
            "required": ["environment_file", "command"]
        }
    },
    {
        "name": "publish_to_guac",
        "description": """
        Publish reproducibility attestation to OpenSSF GUAC.

        This tool:
        1. Signs the attestation with Sigstore (optional)
        2. Publishes to GUAC GraphQL API
        3. Links attestation to artifact in the graph
        4. Returns queryable URI

        Args:
            attestation_path: Path to attestation JSON
            guac_url: GUAC GraphQL endpoint
            sign: Whether to sign with Sigstore

        Returns:
            GUAC artifact URI and attestation ID
        """,
        "inputSchema": {
            "type": "object",
            "properties": {
                "attestation_path": {"type": "string"},
                "guac_url": {"type": "string", "default": "http://localhost:8080"},
                "sign": {"type": "boolean", "default": True}
            },
            "required": ["attestation_path"]
        }
    },
    {
        "name": "query_reproducibility_history",
        "description": """
        Query GUAC for reproducibility history of an artifact.

        Args:
            artifact_digest: SHA256 digest of artifact
            guac_url: GUAC GraphQL endpoint

        Returns:
            List of reproducibility attestations with verdicts
        """,
        "inputSchema": {
            "type": "object",
            "properties": {
                "artifact_digest": {"type": "string"},
                "guac_url": {"type": "string", "default": "http://localhost:8080"}
            },
            "required": ["artifact_digest"]
        }
    }
]
```

---

## Configuration Schema

```yaml
# .project/reproducibility.yaml

# Reproducibility configuration for darnit
reproducibility:
  # Witness integration
  witness:
    # Archivista server for fetching attestations
    archivista_url: "https://archivista.example.com"
    # Local attestation storage
    attestation_dir: ".attestations"
    # Attestors to use when generating new attestations
    attestors:
      - environment
      - git
      - product
      - command_run
      # Future eBPF-based attestors
      # - process_trace
      # - file_access
      # - network_trace

  # GUAC integration
  guac:
    url: "https://guac.example.com"
    # Authentication (optional)
    auth:
      type: "oidc"  # or "api_key"

  # Environment generation preferences
  environment:
    # Preferred target environments (in order)
    preferred:
      - container
      - nix
      - hpc
    # Container settings
    container:
      registry: "ghcr.io/myorg"
      base_images:
        python: "python:3.11-slim"
        cuda: "nvidia/cuda:12.0-devel-ubuntu22.04"
    # HPC settings
    hpc:
      scheduler: "slurm"  # or pbs, lsf
      default_partition: "gpu"
      module_system: "lmod"
    # Nix settings
    nix:
      nixpkgs_channel: "nixos-24.05"
      use_flakes: true

  # Execution settings
  execution:
    timeout_seconds: 3600
    retry_count: 3
    # Witness tracing during execution
    trace_execution: true

  # Reproducibility verification settings
  verification:
    # What counts as "reproducible"
    thresholds:
      bit_for_bit: 1.0  # All artifacts must match exactly
      semantic: 0.95    # 95% of artifacts match semantically
      functional: 0.90  # 90% produce same functional output
    # Ignore list for non-reproducible elements
    ignore_patterns:
      - "*.log"
      - "*.timestamp"
      - "__pycache__"
```

---

## Integration with Existing Darnit Architecture

### Plugin Registration

```python
# packages/darnit-reproducibility/src/darnit_reproducibility/__init__.py

from importlib.resources import files
from pathlib import Path


def register() -> "ReproducibilityImplementation":
    """Register darnit-reproducibility as a compliance implementation."""
    return ReproducibilityImplementation()

class ReproducibilityImplementation:
    """Reproducibility verification as a compliance framework."""

    @property
    def name(self) -> str:
        return "reproducibility"

    @property
    def display_name(self) -> str:
        return "Scientific Reproducibility Checks"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "repro v0.1"

    def get_framework_config_path(self) -> Path | None:
        """The controls live in the framework TOML, not in Python."""
        return Path(str(files(__package__) / "reproducibility.toml"))

    def register_handlers(self) -> None:
        """Register reproducibility-specific step types (framework-design 6.4)."""
        ...
```

The controls are declared in `reproducibility.toml`:

```toml
[controls."REPRO-ENV-01"]
name = "Environment Capture"
description = "Build environment is fully captured and documented"
tags = { level = 1, category = "environment" }

[[controls."REPRO-ENV-01".passes]]
handler = "file_exists"
files = [".project/reproducibility.yaml"]

[[controls."REPRO-ENV-01".passes]]
handler = "pattern"
files = [".witness.yaml"]  # wherever the project keeps its Witness configuration
patterns = { witness_config = 'witness:\s+attestors:' }

[controls."REPRO-BUILD-01"]
name = "Reproducible Build Definition"
description = "Project has reproducible build definition"
tags = { level = 1, category = "build" }

[[controls."REPRO-BUILD-01".passes]]
handler = "file_exists"
files = ["Dockerfile", "Singularity.def", "flake.nix", "spack.yaml"]

[controls."REPRO-ATTEST-01"]
name = "Reproducibility Attestation"
description = "Build has reproducibility attestation"
tags = { level = 2, category = "attestation" }

[[controls."REPRO-ATTEST-01".passes]]
handler = "file_exists"
files = [".attestations/*.intoto.json"]

[[controls."REPRO-ATTEST-01".passes]]
handler = "pattern"
files = [".attestations/*.json"]
patterns = { repro_predicate = 'darnit\.dev/attestations/reproducibility' }

[controls."REPRO-VERIFY-01"]
name = "Verified Reproducibility"
description = "Build has been independently verified as reproducible"
tags = { level = 3, category = "verification" }

# Check GUAC for independent verification
[[controls."REPRO-VERIFY-01".passes]]
handler = "llm_eval"
prompt = "Analyze the reproducibility attestations in GUAC..."
analysis_hints = ["Look for independent verifications"]
```

### Sieve Integration

The reproducibility system reuses darnit's sieve pipeline for verification:

```python
# Example: Using sieve to verify reproducibility controls

def verify_reproducibility(local_path: str) -> list[dict]:
    """Verify reproducibility controls using the sieve pipeline."""
    from darnit.tools.audit import run_sieve_audit

    results, _ = run_sieve_audit(
        owner="",
        repo="",
        local_path=local_path,
        default_branch="main",
        framework_name="reproducibility",
    )
    return results
```

---

## Use Cases for Computational Research

### Use Case 1: Protein Folding Simulation

```text
Researcher runs AlphaFold on their HPC cluster:

1. Initial Run (with Witness):
   $ witness run \
       --step protein-fold \
       --attestations environment git product command_run \
       -- python run_alphafold.py --target protein.fasta

2. Witness captures:
   - CUDA version, driver, GPU model
   - Python environment, packages
   - Input data hashes
   - Output structure hashes

3. Darnit analyzes and generates:
   $ darnit analyze-reproducibility \
       --witness-bundle protein-fold.witness.json

   Output: Recommends Singularity container for HPC portability

4. Generate reproducible environment:
   $ darnit generate-env \
       --target hpc \
       --witness-bundle protein-fold.witness.json

   Creates: Singularity.def, spack.yaml, run.slurm

5. Another researcher reproduces:
   $ darnit execute-reproducible \
       --environment Singularity.def \
       --original protein-fold.witness.json

   Generates: reproducibility attestation

6. Publish to GUAC:
   $ darnit publish-to-guac \
       --attestation repro-attestation.json

   Creates: Queryable provenance in GUAC graph
```

### Use Case 2: Molecular Dynamics (GROMACS)

```text
HPC workflow with MPI and GPU:

1. Witness captures during original run:
   - MPI implementation (OpenMPI 4.1.5)
   - GROMACS version, build flags
   - GPU kernel hashes
   - Input topology files
   - Energy/trajectory outputs

2. Darnit analysis identifies:
   - MPI requirement → HPC environment preferred
   - Specific GPU architecture → CUDA constraint
   - Memory requirements → Resource allocation

3. Generated artifacts:
   - Slurm job script with correct resource requests
   - Spack environment for GROMACS + dependencies
   - Reproducibility verification script

4. Attestation captures:
   - Environment equivalence (or differences)
   - Energy conservation (semantic reproducibility)
   - Trajectory divergence metrics
```

---

## NSF Proposal Integration Points

### Intellectual Merit

1. **Novel reproducibility verification framework** that bridges supply chain security (Witness, GUAC) with scientific computing reproducibility
2. **LLM-assisted environment inference** using darnit's sieve pipeline to fill gaps in captured provenance
3. **Multi-environment generation** from single provenance source (containers, HPC, Nix)
4. **Cryptographic reproducibility attestations** that create verifiable claims about computational results

### Broader Impacts

1. **Reproducibility crisis solution** for computational biology, chemistry, physics
2. **Open source tools** that any research lab can adopt
3. **Standards development** for reproducibility attestation formats
4. **Training materials** for researchers on reproducibility best practices

### Technical Innovation

1. **eBPF-based provenance capture** (via Witness) provides complete execution trace without code modification
2. **Graph-based provenance storage** (via GUAC) enables complex queries about software lineage
3. **Progressive verification** (via sieve) scales from simple checks to LLM-assisted analysis
4. **Attestation chain** creates cryptographic proof of reproducibility

---

## Development Roadmap

### Phase 1: Foundation (Months 1-6)

- [ ] Witness bundle ingestion (current attestors)
- [ ] Basic provenance analysis
- [ ] Dockerfile generation
- [ ] Simple attestation generation

### Phase 2: HPC Support (Months 7-12)

- [ ] Slurm/PBS script generation
- [ ] Spack environment integration
- [ ] Singularity support
- [ ] HPC-specific reproducibility metrics

### Phase 3: Advanced Analysis (Months 13-18)

- [ ] eBPF trace analysis (when Witness supports it)
- [ ] LLM-assisted gap filling
- [ ] Nix derivation generation
- [ ] GUAC integration

### Phase 4: Production & Research (Months 19-24)

- [ ] Pilot with research groups
- [ ] Publication of results
- [ ] Standards contribution
- [ ] Community adoption

---

## References

- [CNCF Witness](https://github.com/in-toto/witness)
- [OpenSSF GUAC](https://guac.sh/)
- [in-toto Specification](https://in-toto.io/)
- [Sigstore](https://sigstore.dev/)
- [Reproducible Builds](https://reproducible-builds.org/)
- [Nix](https://nixos.org/)
- [Spack](https://spack.io/)
