"""Adversarial fixture corpus runner (feature 041, framework-design.md section 5.5).

Runs a framework's controls against every fixture under the corpus root,
offline and deterministically, and measures each step against the fixture's
human labels. See ``README.md`` in this directory for the fixture format.

Offline means: platform calls made through ``gh_api_with_status`` are served
by ``RecordedGhApi`` from the fixture's ``[fixture.platform]`` recordings, and
``gh`` subprocesses (``exec`` steps) are served the same recordings by a stub
placed first on a ``PATH`` that otherwise holds only ``/usr/bin`` and
``/bin``. An unrecorded path is a transport failure. ``HOME`` and the XDG
directories point into a scratch directory, so the developer's operator
configuration, confirmations, and caches are never read or written.

Deterministic only: no model is consulted. A control waiting for a model
judgment is ``PENDING``, which is simply not PASS.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock

CORPUS_ROOT = Path(__file__).resolve().parent
LABELS_FILE = "labels.toml"
KNOWN_FALSE_PASS_FILE = CORPUS_ROOT / "known_false_pass.toml"
EXPECTED_VALUES = ("PASS", "FAIL", "NOT_PASS", "N/A")
OWNER = "corpus"
BRANCH = "main"
LEVEL = 3
RECORDINGS_ENV = "DARNIT_CORPUS_GH_RECORDINGS"

_CONCLUSIONS = frozenset({"PASS", "FAIL", "WARN"})
_NOT_PASS_LABELS = frozenset({"FAIL", "NOT_PASS"})
_SCRUBBED_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GH_HOST", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")

_GH_STUB = """
import json
import os
import sys

args = sys.argv[1:]
if not args or args[0] != "api":
    sys.stderr.write("corpus gh stub: no recording for `gh %s`\\n" % " ".join(args))
    sys.exit(1)
path = None
jq = None
rest = args[1:]
i = 0
while i < len(rest):
    token = rest[i]
    if token in ("--jq", "-q"):
        jq = rest[i + 1] if i + 1 < len(rest) else ""
        i += 2
        continue
    if not token.startswith("-") and path is None:
        path = token
    i += 1
with open(os.environ["__RECORDINGS_ENV__"], encoding="utf-8") as handle:
    recordings = json.load(handle)
key = "/" + (path or "").lstrip("/")
recorded = recordings.get(key)
if recorded is None:
    sys.stderr.write("corpus gh stub: no recorded response for %s\\n" % key)
    sys.exit(1)
status = int(recorded.get("status", 200))
if not 200 <= status < 300:
    if recorded.get("body") is not None:
        sys.stdout.write(json.dumps(recorded["body"]) + "\\n")
    sys.stderr.write("gh: %s\\n" % (recorded.get("error") or "HTTP %d" % status))
    sys.exit(1)
if jq is not None:
    outputs = recorded.get("jq") or {}
    if jq not in outputs:
        sys.stderr.write("corpus gh stub: no recorded --jq output for %r on %s\\n" % (jq, key))
        sys.exit(1)
    sys.stdout.write(str(outputs[jq]) + "\\n")
    sys.exit(0)
sys.stdout.write(json.dumps(recorded.get("body")) + "\\n")
""".replace("__RECORDINGS_ENV__", RECORDINGS_ENV)


class CorpusError(ValueError):
    """A fixture or its labels cannot be used."""


@dataclass(frozen=True)
class Label:
    expected: str
    why: str


@dataclass(frozen=True)
class Fixture:
    name: str
    path: Path
    description: str
    platform: dict[str, dict[str, Any]]
    labels: dict[str, Label]

    def recordings(self) -> dict[str, dict[str, Any]]:
        """Recorded platform responses keyed by concrete API path."""
        subs = {"$OWNER": OWNER, "$REPO": self.name, "$BRANCH": BRANCH}
        out: dict[str, dict[str, Any]] = {}
        for raw, response in self.platform.items():
            path = raw
            for var, value in subs.items():
                path = path.replace(var, value)
            out["/" + path.lstrip("/")] = dict(response)
        return out


@dataclass(frozen=True)
class Framework:
    """Controls to measure. ``implementation`` names the plugin whose handlers the audit registers."""

    name: str
    controls: list[Any]
    implementation: str | None = None


@dataclass(frozen=True)
class StepObservation:
    control_id: str
    step_index: int | None
    handler: str
    outcome: str
    concluded: bool


@dataclass
class FixtureRun:
    fixture: Fixture
    results: dict[str, dict[str, Any]]
    steps: list[StepObservation]


@dataclass
class StepRow:
    framework: str
    control_id: str
    step_index: int
    handler: str
    outcome: str
    may_conclude_pass: bool
    observed: int = 0
    concluded: int = 0
    correct: int = 0
    incorrect: int = 0
    false_pass: int = 0
    false_pass_fixtures: list[str] = field(default_factory=list)


@dataclass
class StepSummary:
    framework: str
    control_id: str
    step_index: int
    handler: str
    may_conclude_pass: bool
    measured: bool
    true_pass: int
    false_pass: int
    eligible_for_promotion: bool


@dataclass
class ControlOutcome:
    framework: str
    fixture: str
    control_id: str
    expected: str
    why: str
    status: str
    concluded_by: str | None
    step_index: int | None
    verdict: str


@dataclass(frozen=True)
class Violation:
    framework: str
    fixture: str
    control_id: str
    step_index: int | None
    handler: str
    expected: str
    why: str

    def describe(self) -> str:
        step = "inferred_from" if self.step_index is None else f"pass[{self.step_index}] ({self.handler})"
        return (
            f"{self.framework} {self.control_id} {step} concluded PASS on fixture "
            f"'{self.fixture}' labelled {self.expected}: {self.why}"
        )


@dataclass(frozen=True)
class KnownFalsePass:
    framework: str
    fixture: str
    control_id: str
    step_index: int | None
    handler: str
    task: str
    why: str

    def matches(self, violation: Violation) -> bool:
        return (
            self.framework == violation.framework
            and self.fixture == violation.fixture
            and self.control_id == violation.control_id
            and self.step_index == violation.step_index
            and self.handler == violation.handler
        )


@dataclass
class CorpusReport:
    corpus_version: str
    frameworks: list[str]
    fixtures: dict[str, dict[str, Any]]
    rows: list[StepRow]
    steps: list[StepSummary]
    controls: list[ControlOutcome]
    violations: list[Violation]
    unknown_labels: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_version": self.corpus_version,
            "frameworks": self.frameworks,
            "fixtures": self.fixtures,
            "rows": [asdict(r) for r in self.rows],
            "steps": [asdict(s) for s in self.steps],
            "controls": [asdict(c) for c in self.controls],
            "violations": [asdict(v) for v in self.violations],
            "unknown_labels": self.unknown_labels,
        }


# ---------------------------------------------------------------------------
# Fixtures, labels, and the corpus version
# ---------------------------------------------------------------------------


def load_fixture(path: Path) -> Fixture:
    labels_path = path / LABELS_FILE
    try:
        data = tomllib.loads(labels_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise CorpusError(f"{labels_path}: {exc}") from exc
    meta = data.get("fixture") or {}
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        raise CorpusError(f"{labels_path}: [fixture].description is required")
    platform = meta.get("platform") or {}
    for key, response in platform.items():
        if not isinstance(response, dict) or not isinstance(response.get("status", 200), int):
            raise CorpusError(f"{labels_path}: [fixture.platform.{key!r}] needs an integer status")
    labels: dict[str, Label] = {}
    for control_id, entry in (data.get("labels") or {}).items():
        expected = entry.get("expected") if isinstance(entry, dict) else None
        why = entry.get("why") if isinstance(entry, dict) else None
        if expected not in EXPECTED_VALUES:
            raise CorpusError(
                f"{labels_path}: {control_id}.expected must be one of {EXPECTED_VALUES}, got {expected!r}"
            )
        if not isinstance(why, str) or not why.strip():
            raise CorpusError(f"{labels_path}: {control_id}.why is required")
        labels[control_id] = Label(expected=expected, why=why.strip())
    return Fixture(name=path.name, path=path, description=description.strip(), platform=platform, labels=labels)


def fixture_dirs(root: Path = CORPUS_ROOT) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / LABELS_FILE).is_file())


def load_fixtures(root: Path = CORPUS_ROOT) -> list[Fixture]:
    return [load_fixture(p) for p in fixture_dirs(root)]


def corpus_version(root: Path = CORPUS_ROOT) -> str:
    """Digest over every fixture file and label, in path order."""
    digest = hashlib.sha256()
    files = sorted(
        (f.relative_to(root).as_posix(), f)
        for d in fixture_dirs(root)
        for f in d.rglob("*")
        if f.is_file() and "__pycache__" not in f.parts and f.name != ".DS_Store"
    )
    for rel, path in files:
        data = path.read_bytes()
        digest.update(f"{rel}\0{len(data)}\0".encode())
        digest.update(data)
    return "sha256:" + digest.hexdigest()


def load_known_false_pass(path: Path = KNOWN_FALSE_PASS_FILE) -> list[KnownFalsePass]:
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = []
    for entry in data.get("known", []):
        entries.append(
            KnownFalsePass(
                framework=entry["framework"],
                fixture=entry["fixture"],
                control_id=entry["control"],
                step_index=entry.get("step"),
                handler=entry["handler"],
                task=entry["task"],
                why=entry["why"],
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Frameworks
# ---------------------------------------------------------------------------


def load_framework(name: str) -> Framework:
    """Controls of an installed implementation, loaded after its handlers register."""
    from darnit.config import load_controls_from_framework, load_framework_config
    from darnit.core.discovery import get_implementation, register_implementation_handlers

    impl = get_implementation(name)
    if impl is None:
        raise CorpusError(f"no implementation named {name!r}")
    register_implementation_handlers(name)
    path = impl.get_framework_config_path()
    controls = load_controls_from_framework(load_framework_config(Path(str(path))))
    return Framework(name=name, controls=controls, implementation=name)


def framework_from_toml(path: Path) -> Framework:
    """A framework defined only by a TOML file (used by the runner's self-tests)."""
    from darnit.config import load_controls_from_framework, load_framework_config

    config = load_framework_config(path)
    return Framework(name=config.metadata.name, controls=load_controls_from_framework(config))


def _may_conclude_pass(invocation: Any) -> bool:
    from darnit.sieve.handler_registry import effective_outcomes, get_sieve_handler_registry

    info = get_sieve_handler_registry().get(invocation.handler)
    return info is not None and "pass" in effective_outcomes(info, invocation)


# ---------------------------------------------------------------------------
# Running one fixture
# ---------------------------------------------------------------------------


@contextmanager
def _environment(updates: dict[str, str]) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in (*updates, *_SCRUBBED_ENV)}
    try:
        for key in _SCRUBBED_ENV:
            os.environ.pop(key, None)
        os.environ.update(updates)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _control_registry_restored() -> Iterator[None]:
    from darnit.sieve.registry import get_control_registry
    from darnit.tools import audit

    registry = get_control_registry()
    saved_specs = dict(registry._specs)
    saved_registered = set(audit._toml_controls_registered)
    try:
        yield
    finally:
        registry._specs.clear()
        registry._specs.update(saved_specs)
        audit._toml_controls_registered.clear()
        audit._toml_controls_registered.update(saved_registered)


@contextmanager
def _observe_steps(sink: list[StepObservation]) -> Iterator[None]:
    """Record every executed step's handler outcome and whether it concluded.

    The orchestrator computes each step's effective set right after the
    handler runs and then resolves the step's disposition; wrapping those two
    calls identifies the step (by identity in the control's invocation list)
    and its raw outcome without changing either.
    """
    from darnit.sieve import orchestrator as orch

    concluding = {
        orch.StepDisposition.CONCLUDE_PASS,
        orch.StepDisposition.CONCLUDE_FAIL,
        orch.StepDisposition.CONCLUDE_WARN,
    }
    current: list[Any] = []
    pending: list[tuple[str, int | None, str]] = []
    original_dispatch = orch.SieveOrchestrator._dispatch_handler_invocations
    original_effective = orch.effective_outcomes
    original_resolve = orch.resolve_step_result

    def dispatch(self: Any, control_spec: Any, context: Any) -> Any:
        current.append(control_spec)
        try:
            return original_dispatch(self, control_spec, context)
        finally:
            current.pop()

    def effective(info: Any, step: Any) -> frozenset[str]:
        if current:
            invocations = current[-1].metadata.get("handler_invocations") or []
            index = next((i for i, s in enumerate(invocations) if s is step), None)
            pending[:] = [(current[-1].control_id, index, step.handler)]
        return original_effective(info, step)

    def resolve(handler_status: Any, allowed: frozenset[str], is_last_step: bool = False) -> Any:
        disposition = original_resolve(handler_status=handler_status, allowed=allowed, is_last_step=is_last_step)
        if pending:
            control_id, index, handler = pending.pop()
            sink.append(
                StepObservation(
                    control_id=control_id,
                    step_index=index,
                    handler=handler,
                    outcome=str(getattr(handler_status, "value", handler_status)).upper(),
                    concluded=disposition in concluding,
                )
            )
        return disposition

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(orch.SieveOrchestrator, "_dispatch_handler_invocations", dispatch))
        stack.enter_context(mock.patch.object(orch, "effective_outcomes", effective))
        stack.enter_context(mock.patch.object(orch, "resolve_step_result", resolve))
        yield


def _builtin_operator_config() -> Any:
    from darnit.config.operator.loader import BUILTIN_DEFAULTS, LoadedOperatorConfig
    from darnit.config.operator.schema import OperatorConfig

    return LoadedOperatorConfig(
        config=OperatorConfig(schema_version=1),
        source=BUILTIN_DEFAULTS,
        digest=None,
        permission_check="not_applicable",
        strict=False,
    )


def run_fixture(fixture: Fixture, framework: Framework) -> FixtureRun:
    """Audit a copy of ``fixture`` with ``framework``'s controls, offline."""
    from darnit.core.utils import RecordedGhApi, set_gh_api_responder
    from darnit.tools.audit import run_sieve_audit

    observations: list[StepObservation] = []
    with tempfile.TemporaryDirectory(prefix="darnit-corpus-") as scratch_name:
        scratch = Path(scratch_name).resolve()
        repo = scratch / fixture.name
        shutil.copytree(fixture.path, repo, ignore=shutil.ignore_patterns(LABELS_FILE, "__pycache__", ".DS_Store"))
        home = scratch / "home"
        home.mkdir()
        bin_dir = scratch / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(f"#!{sys.executable}\n{_GH_STUB}", encoding="utf-8")
        gh.chmod(0o755)
        recordings = fixture.recordings()
        recordings_path = scratch / "platform.json"
        recordings_path.write_text(json.dumps(recordings), encoding="utf-8")
        env = {
            "PATH": os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"]),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "GIT_CEILING_DIRECTORIES": str(scratch),
            RECORDINGS_ENV: str(recordings_path),
        }
        previous = set_gh_api_responder(RecordedGhApi(recordings))
        try:
            with _environment(env), _control_registry_restored(), _observe_steps(observations):
                results, _summary = run_sieve_audit(
                    OWNER,
                    fixture.name,
                    str(repo),
                    BRANCH,
                    LEVEL,
                    controls=list(framework.controls),
                    apply_user_config=False,
                    stop_on_llm=True,
                    framework_name=framework.implementation,
                    operator_config=_builtin_operator_config(),
                )
        finally:
            set_gh_api_responder(previous)
    return FixtureRun(fixture=fixture, results={r["id"]: dict(r) for r in results}, steps=observations)


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def judge_step(outcome: str, expected: str) -> str | None:
    """``correct`` / ``incorrect`` for a conclusion (PASS, FAIL, WARN); None otherwise."""
    if outcome not in _CONCLUSIONS:
        return None
    if outcome == "PASS":
        return "correct" if expected == "PASS" else "incorrect"
    return "correct" if expected in _NOT_PASS_LABELS else "incorrect"


def judge_control(result: dict[str, Any], expected: str) -> str:
    status = result.get("status", "")
    concluded_by = result.get("concluded_by")
    if status == "PASS":
        if expected == "PASS":
            return "correct"
        return "false_pass" if expected in _NOT_PASS_LABELS else "incorrect"
    if status == "N/A":
        return "correct" if expected == "N/A" else "incorrect"
    if status == "FAIL" or (status == "WARN" and concluded_by not in (None, "none")):
        return "correct" if expected in _NOT_PASS_LABELS else "incorrect"
    return "undetermined"


def measure(framework: Framework, fixtures: list[Fixture], version: str) -> CorpusReport:
    """Run every fixture and measure each step and control against the labels."""
    control_ids = {c.control_id for c in framework.controls}
    invocations = {c.control_id: c.metadata.get("handler_invocations") or [] for c in framework.controls}
    rows: dict[tuple[str, int, str, str], StepRow] = {}
    controls: list[ControlOutcome] = []
    violations: list[Violation] = []
    unknown: list[str] = []
    fixture_meta: dict[str, dict[str, Any]] = {}

    for fixture in fixtures:
        unknown.extend(f"{fixture.name}:{cid}" for cid in sorted(fixture.labels) if cid not in control_ids)
        counts: dict[str, int] = {}
        for label in fixture.labels.values():
            counts[label.expected] = counts.get(label.expected, 0) + 1
        fixture_meta[fixture.name] = {"description": fixture.description, "labels": dict(sorted(counts.items()))}
        run = run_fixture(fixture, framework)

        for obs in run.steps:
            label = fixture.labels.get(obs.control_id)
            if label is None or obs.step_index is None:
                continue
            key = (obs.control_id, obs.step_index, obs.handler, obs.outcome)
            row = rows.get(key)
            if row is None:
                invocation = invocations[obs.control_id][obs.step_index]
                row = rows[key] = StepRow(
                    framework=framework.name,
                    control_id=obs.control_id,
                    step_index=obs.step_index,
                    handler=obs.handler,
                    outcome=obs.outcome,
                    may_conclude_pass=_may_conclude_pass(invocation),
                )
            row.observed += 1
            row.concluded += int(obs.concluded)
            verdict = judge_step(obs.outcome, label.expected)
            if verdict == "correct":
                row.correct += 1
            elif verdict == "incorrect":
                row.incorrect += 1
            if obs.outcome == "PASS" and label.expected in _NOT_PASS_LABELS:
                row.false_pass += 1
                row.false_pass_fixtures.append(fixture.name)

        for control_id, label in sorted(fixture.labels.items()):
            result = run.results.get(control_id)
            if result is None:
                continue
            verdict = judge_control(result, label.expected)
            concluded_by = result.get("concluded_by")
            step_index = result.get("resolving_pass_index")
            controls.append(
                ControlOutcome(
                    framework=framework.name,
                    fixture=fixture.name,
                    control_id=control_id,
                    expected=label.expected,
                    why=label.why,
                    status=result.get("status", ""),
                    concluded_by=concluded_by,
                    step_index=step_index,
                    verdict=verdict,
                )
            )
            if verdict == "false_pass":
                violations.append(
                    Violation(
                        framework=framework.name,
                        fixture=fixture.name,
                        control_id=control_id,
                        step_index=None if concluded_by == "inferred_from" else step_index,
                        handler=concluded_by or "unknown",
                        expected=label.expected,
                        why=label.why,
                    )
                )

    ordered = sorted(rows.values(), key=lambda r: (r.control_id, r.step_index, r.outcome))
    return CorpusReport(
        corpus_version=version,
        frameworks=[framework.name],
        fixtures=fixture_meta,
        rows=ordered,
        steps=_summarize_steps(framework, ordered),
        controls=controls,
        violations=violations,
        unknown_labels=unknown,
    )


def _summarize_steps(framework: Framework, rows: list[StepRow]) -> list[StepSummary]:
    """One entry per declared step; a step is eligible for a PASS promotion only
    when it may not yet conclude PASS, produced at least one correct PASS, and
    produced no false PASS anywhere in the corpus."""
    by_step: dict[tuple[str, int], list[StepRow]] = {}
    for row in rows:
        by_step.setdefault((row.control_id, row.step_index), []).append(row)
    summaries = []
    for control in sorted(framework.controls, key=lambda c: c.control_id):
        for index, invocation in enumerate(control.metadata.get("handler_invocations") or []):
            step_rows = by_step.get((control.control_id, index), [])
            may_pass = _may_conclude_pass(invocation)
            true_pass = sum(r.correct for r in step_rows if r.outcome == "PASS")
            false_pass = sum(r.false_pass for r in step_rows)
            summaries.append(
                StepSummary(
                    framework=framework.name,
                    control_id=control.control_id,
                    step_index=index,
                    handler=invocation.handler,
                    may_conclude_pass=may_pass,
                    measured=bool(step_rows),
                    true_pass=true_pass,
                    false_pass=false_pass,
                    eligible_for_promotion=not may_pass and true_pass > 0 and false_pass == 0,
                )
            )
    return summaries


def gate(report: CorpusReport, known: list[KnownFalsePass]) -> tuple[list[Violation], list[KnownFalsePass]]:
    """Violations not in the known list, and known entries that no longer occur."""
    unexpected = [v for v in report.violations if not any(k.matches(v) for k in known)]
    stale = [k for k in known if k.framework in report.frameworks and not any(k.matches(v) for v in report.violations)]
    return unexpected, stale


def run_corpus(framework: Framework, root: Path = CORPUS_ROOT) -> CorpusReport:
    return measure(framework, load_fixtures(root), corpus_version(root))
