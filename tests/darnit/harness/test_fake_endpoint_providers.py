"""End-to-end integration tests for model providers against a local fake HTTP endpoint.

Covers Issue #780. Exercises PydanticAILLMStep through Darnit's harness and sieve
with real HTTP requests, headers, and response parsing against both Anthropic and
OpenAI endpoints on localhost.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from darnit.config.operator.loader import set_launch_options
from darnit.harness.driver import HarnessRun, LLMConsultationResponse
from darnit.sieve.models import CheckContext, ControlSpec, PassOutcome, SieveResult
from darnit.sieve.orchestrator import SieveOrchestrator
from tests.darnit.harness.verify_report import verify_control_llm_judgment


class FakeModelServerHandler(BaseHTTPRequestHandler):
    """Local HTTP handler that speaks both Anthropic Messages (SSE) and OpenAI Responses (JSON)."""

    def do_POST(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_len) if content_len > 0 else b""
        body_text = body_bytes.decode("utf-8", errors="ignore")

        # Record incoming request for assertions
        self.server.recorded_requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": body_text,
            }
        )

        handler_fn = self.server.response_handler
        status, content_type, response_bytes = handler_fn(self.path, body_text)

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if content_type == "text/event-stream":
            self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def log_message(self, *args: Any) -> None:
        # Suppress standard logging during tests
        pass


@pytest.fixture
def fake_endpoint(monkeypatch: pytest.MonkeyPatch):
    """Run an ephemeral fake model endpoint on 127.0.0.1:0 and configure environment."""
    server = HTTPServer(("127.0.0.1", 0), FakeModelServerHandler)
    server.allow_reuse_address = True
    server.recorded_requests = []
    port = server.server_address[1]

    ready_event = threading.Event()

    def run_server():
        ready_event.set()
        server.serve_forever()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    ready_event.wait(timeout=2.0)

    # Wire environment to our ephemeral server & block external traffic
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{port}/v1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-openai-key")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")  # Closed port proxy

    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _format_anthropic_sse(judgment_data: dict[str, Any]) -> bytes:
    """Format an Anthropic SSE response stream returning a final_result tool use."""
    args = json.dumps(judgment_data)
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 10},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "t1", "name": "final_result", "input": {}},
            },
        ),
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": args}},
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 10}},
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    out = []
    for ev, data in events:
        out.append(f"event: {ev}\ndata: {json.dumps(data)}\n\n")
    return "".join(out).encode("utf-8")


def _format_anthropic_json(judgment_data: dict[str, Any]) -> bytes:
    """Format an Anthropic Messages API non-streaming JSON response."""
    resp = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [
            {
                "type": "tool_use",
                "id": "t1",
                "name": "final_result",
                "input": judgment_data,
            }
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }
    return json.dumps(resp).encode("utf-8")


def _format_anthropic_response(judgment_data: dict[str, Any], body_text: str = "") -> tuple[int, str, bytes]:
    """Format an Anthropic response, choosing SSE stream or non-streaming JSON based on request."""
    is_stream = False
    if body_text:
        try:
            req_data = json.loads(body_text)
            is_stream = bool(req_data.get("stream", False))
        except Exception:
            is_stream = False
    if is_stream:
        return 200, "text/event-stream", _format_anthropic_sse(judgment_data)
    return 200, "application/json", _format_anthropic_json(judgment_data)


def _format_openai_json(judgment_data: dict[str, Any]) -> bytes:
    """Format an OpenAI Responses API JSON response delivering a final_result function call."""
    resp = {
        "id": "resp_test",
        "created_at": 1700000000,
        "model": "gpt-5",
        "status": "completed",
        "output": [
            {
                "id": "item_1",
                "type": "function_call",
                "call_id": "call_1",
                "name": "final_result",
                "arguments": json.dumps(judgment_data),
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }
    return json.dumps(resp).encode("utf-8")


@pytest.fixture
def repo_with_operator_config(tmp_path: Path):
    """Helper to write an operator config and fixture repo for a provider."""

    def _create(provider: str, model: str) -> tuple[Path, Path]:
        repo_dir = tmp_path / f"repo_{provider}"
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "README.md").write_text(
            "# test-repo\n\nFor security issues contact: security@example.com\n", encoding="utf-8"
        )
        # Operator configuration MUST live outside the audited repository (containment rule)
        op_path = tmp_path / f"operator_{provider}.toml"
        op_path.write_text(
            f'schema_version = 1\n\n[llm]\nprovider = "{provider}"\nmodel = "{model}"\n',
            encoding="utf-8",
        )
        return repo_dir, op_path

    return _create


def _run_harness_step(
    repo_dir: Path,
    consultation_req: dict[str, Any],
    file_contents: dict[str, str],
) -> tuple[LLMConsultationResponse, SieveResult]:
    """Execute HarnessRun._dispatch_llm_step and resolve through SieveOrchestrator."""
    run = HarnessRun(local_path=str(repo_dir))
    run._resolve_operator_config()

    llm_resp = asyncio.run(run._dispatch_llm_step(consultation_req))

    spec = ControlSpec(control_id="SEC-01", level=1, domain="security", name="Contact", description="Test")
    ctx = CheckContext(control_id="SEC-01", local_path=str(repo_dir), owner="test", repo="repo", default_branch="main")
    orch = SieveOrchestrator()
    consultation = {
        "file_contents": file_contents,
        "prompt": consultation_req.get("prompt", ""),
    }
    sieve_res = orch.verify_with_llm_response(
        control_spec=spec,
        context=ctx,
        llm_response=llm_resp,
        consultation=consultation,
    )
    return llm_resp, sieve_res


@pytest.mark.unit
@pytest.mark.parametrize(
    "provider,model,expected_path,expected_key",
    [
        ("anthropic", "claude-sonnet-5", "/v1/messages", "dummy-anthropic-key"),
        ("openai", "gpt-5", "/v1/responses", "dummy-openai-key"),
    ],
)
class TestFakeEndpointProviders:
    """Test both Anthropic and OpenAI providers against local fake endpoint across all 6 cases."""

    def test_valid_yes_citing_text_in_files(
        self,
        fake_endpoint,
        repo_with_operator_config,
        provider,
        model,
        expected_path,
        expected_key,
    ) -> None:
        """Case 1: Model answers yes citing text in files -> PASS candidate (PENDING, never PASS)."""
        repo_dir, op_path = repo_with_operator_config(provider, model)
        set_launch_options(op_path)

        def response_handler(path: str, body: str) -> tuple[int, str, bytes]:
            judgment = {
                "outcome": "yes",
                "confidence": 0.95,
                "reasoning": "Found security contact in README",
                "cited_evidence": ["For security issues contact: security@example.com"],
            }
            if provider == "anthropic":
                return _format_anthropic_response(judgment, body)
            return 200, "application/json", _format_openai_json(judgment)

        fake_endpoint.response_handler = response_handler

        consultation_req = {
            "control_id": "SEC-01",
            "prompt": "Is there a security contact in README?",
            "file_contents": {"README.md": (repo_dir / "README.md").read_text(encoding="utf-8")},
        }

        llm_resp, sieve_res = _run_harness_step(
            repo_dir,
            consultation_req,
            file_contents={"README.md": "For security issues contact: security@example.com"},
        )

        # Invariants from Issue #780:
        # A positive model judgment becomes a PASS candidate (PENDING, confirmation), NEVER unilateral PASS
        assert sieve_res.status == "PENDING"
        assert sieve_res.pending == {"kind": "confirmation"}
        assert sieve_res.status != "PASS"
        assert sieve_res.candidate is not None
        assert sieve_res.candidate["verdict"] == "pass"
        assert sieve_res.evidence["llm_model"] == f"{provider}:{model}"

        # HTTP request verification
        assert len(fake_endpoint.recorded_requests) >= 1
        req_rec = fake_endpoint.recorded_requests[0]
        assert expected_path in req_rec["path"]
        auth_header = (
            req_rec["headers"].get("Authorization")
            or req_rec["headers"].get("authorization")
            or req_rec["headers"].get("x-api-key")
            or req_rec["headers"].get("X-Api-Key")
        )
        assert auth_header is not None
        assert expected_key in auth_header

    def test_yes_citing_text_not_in_files(
        self,
        fake_endpoint,
        repo_with_operator_config,
        provider,
        model,
        expected_path,
        expected_key,
    ) -> None:
        """Case 2: Model answers yes with excerpt NOT in files -> rejected, not a candidate (WARN)."""
        repo_dir, op_path = repo_with_operator_config(provider, model)
        set_launch_options(op_path)

        def response_handler(path: str, body: str) -> tuple[int, str, bytes]:
            judgment = {
                "outcome": "yes",
                "confidence": 0.95,
                "reasoning": "Hallucinated citation",
                "cited_evidence": ["This excerpt is definitely not in the README!"],
            }
            if provider == "anthropic":
                return _format_anthropic_response(judgment, body)
            return 200, "application/json", _format_openai_json(judgment)

        fake_endpoint.response_handler = response_handler

        consultation_req = {
            "control_id": "SEC-01",
            "prompt": "Is there a security contact in README?",
            "file_contents": {"README.md": (repo_dir / "README.md").read_text(encoding="utf-8")},
        }

        llm_resp, sieve_res = _run_harness_step(
            repo_dir,
            consultation_req,
            file_contents={"README.md": "For security issues contact: security@example.com"},
        )

        # Invariants from Issue #780:
        # Cited excerpt not in files -> rejected, not a candidate (WARN)
        assert sieve_res.status == "WARN"
        assert sieve_res.pending is None
        assert sieve_res.candidate is None
        assert "rejected" in sieve_res.message
        assert sieve_res.evidence["llm_model"] == f"{provider}:{model}"

    def test_clean_no(
        self,
        fake_endpoint,
        repo_with_operator_config,
        provider,
        model,
        expected_path,
        expected_key,
    ) -> None:
        """Case 3: Model answers no -> a model finding (FAIL)."""
        repo_dir, op_path = repo_with_operator_config(provider, model)
        set_launch_options(op_path)

        def response_handler(path: str, body: str) -> tuple[int, str, bytes]:
            judgment = {
                "outcome": "no",
                "confidence": 0.85,
                "reasoning": "No contact information exists in README",
                "cited_evidence": [],
            }
            if provider == "anthropic":
                return _format_anthropic_response(judgment, body)
            return 200, "application/json", _format_openai_json(judgment)

        fake_endpoint.response_handler = response_handler

        consultation_req = {
            "control_id": "SEC-01",
            "prompt": "Is there a security contact in README?",
            "file_contents": {"README.md": (repo_dir / "README.md").read_text(encoding="utf-8")},
        }

        llm_resp, sieve_res = _run_harness_step(
            repo_dir,
            consultation_req,
            file_contents={"README.md": "For security issues contact: security@example.com"},
        )

        # Invariants from Issue #780:
        # Negative judgment -> model finding (FAIL)
        assert sieve_res.status == "FAIL"
        assert sieve_res.concluded_by == "llm_judgment"
        assert "Model finding" in sieve_res.message
        assert sieve_res.evidence["llm_model"] == f"{provider}:{model}"

    def test_inconclusive(
        self,
        fake_endpoint,
        repo_with_operator_config,
        provider,
        model,
        expected_path,
        expected_key,
    ) -> None:
        """Case 4: Model answers inconclusive -> WARN."""
        repo_dir, op_path = repo_with_operator_config(provider, model)
        set_launch_options(op_path)

        def response_handler(path: str, body: str) -> tuple[int, str, bytes]:
            judgment = {
                "outcome": "inconclusive",
                "confidence": 0.1,
                "reasoning": "Unable to determine",
                "cited_evidence": [],
            }
            if provider == "anthropic":
                return _format_anthropic_response(judgment, body)
            return 200, "application/json", _format_openai_json(judgment)

        fake_endpoint.response_handler = response_handler

        consultation_req = {
            "control_id": "SEC-01",
            "prompt": "Is there a security contact in README?",
            "file_contents": {"README.md": (repo_dir / "README.md").read_text(encoding="utf-8")},
        }

        llm_resp, sieve_res = _run_harness_step(
            repo_dir,
            consultation_req,
            file_contents={"README.md": "For security issues contact: security@example.com"},
        )

        # Invariants from Issue #780:
        # Inconclusive judgment -> WARN
        assert sieve_res.status == "WARN"
        assert sieve_res.evidence["llm_model"] == f"{provider}:{model}"

    def test_http_500_unavailable(
        self,
        fake_endpoint,
        repo_with_operator_config,
        provider,
        model,
        expected_path,
        expected_key,
    ) -> None:
        """Case 5: Server returns HTTP 500 error; mapped to unavailable in driver."""
        repo_dir, op_path = repo_with_operator_config(provider, model)
        set_launch_options(op_path)

        def response_handler(path: str, body: str) -> tuple[int, str, bytes]:
            return 500, "application/json", b'{"error": "internal server error"}'

        fake_endpoint.response_handler = response_handler

        consultation_req = {"control_id": "SEC-01", "prompt": "Q"}
        llm_resp, sieve_res = _run_harness_step(
            repo_dir,
            consultation_req,
            file_contents={"README.md": "content"},
        )

        # Invariants from Issue #780:
        # 500 error / unreachable -> ERROR, class unavailable
        assert llm_resp.status == PassOutcome.ERROR
        assert llm_resp.error_class == "unavailable"
        assert sieve_res.status == "ERROR"
        assert sieve_res.error_class == "unavailable"
        assert sieve_res.evidence["llm_model"] == f"{provider}:{model}"
        # Retries happened on 500 error
        assert len(fake_endpoint.recorded_requests) >= 2

    def test_malformed_body_evaluation(
        self,
        fake_endpoint,
        repo_with_operator_config,
        provider,
        model,
        expected_path,
        expected_key,
    ) -> None:
        """Case 6: Server returns unparseable / malformed body; mapped to evaluation."""
        repo_dir, op_path = repo_with_operator_config(provider, model)
        set_launch_options(op_path)

        def response_handler(path: str, body: str) -> tuple[int, str, bytes]:
            # Return broken syntax that causes a decoding / validation error
            return 200, "application/json", b"not-valid-json-{{{broken"

        fake_endpoint.response_handler = response_handler

        consultation_req = {"control_id": "SEC-01", "prompt": "Q"}
        llm_resp, sieve_res = _run_harness_step(
            repo_dir,
            consultation_req,
            file_contents={"README.md": "content"},
        )

        # Invariants from Issue #780 / #781:
        # Malformed response body -> ERROR, class evaluation (or unavailable)
        assert llm_resp.status == PassOutcome.ERROR
        assert llm_resp.error_class in ("evaluation", "unavailable")
        assert sieve_res.status == "ERROR"
        assert sieve_res.error_class in ("evaluation", "unavailable")
        assert sieve_res.evidence["llm_model"] == f"{provider}:{model}"

        # Shared control judgment verification
        violations = verify_control_llm_judgment(
            {"id": "SEC-01", "status": sieve_res.status, "evidence": sieve_res.evidence},
            expected_provider=provider,
            expected_model=model,
        )
        assert not violations


@pytest.mark.unit
class TestSharedReportInvariants:
    """Verify shared report and control invariant contracts (#781, #780)."""

    def test_shared_report_invariants_valid(self) -> None:
        """Verify that valid control judgment satisfies safety and attribution invariants."""
        ctrl = {
            "id": "OSPS-BR-07.02",
            "status": "FAIL",
            "evidence": {
                "llm_model": "openai:qwen2.5-coder:1.5b",
                "llm_reasoning": "Missing branch protection",
            },
        }
        violations = verify_control_llm_judgment(
            ctrl,
            expected_provider="openai",
            expected_model="qwen2.5-coder:1.5b",
        )
        assert not violations

    def test_shared_report_invariants_safety_rejection(self) -> None:
        """Verify that unilateral PASS from model is strictly rejected."""
        invalid_pass = {
            "id": "OSPS-BR-07.02",
            "status": "PASS",
            "evidence": {"llm_model": "openai:qwen2.5-coder:1.5b"},
        }
        violations = verify_control_llm_judgment(
            invalid_pass,
            expected_provider="openai",
            expected_model="qwen2.5-coder:1.5b",
        )
        assert any("[Safety]" in v for v in violations)

    def test_shared_report_invariants_attribution_mismatch(self) -> None:
        """Verify that provider/model attribution mismatch is detected."""
        mismatch_ctrl = {
            "id": "OSPS-BR-07.02",
            "status": "PENDING",
            "evidence": {"llm_model": "anthropic:claude-3-5-sonnet"},
        }
        violations = verify_control_llm_judgment(
            mismatch_ctrl,
            expected_provider="openai",
            expected_model="qwen2.5-coder:1.5b",
        )
        assert any("[Attribution]" in v for v in violations)
