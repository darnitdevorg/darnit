import pytest
from darnit.sieve.orchestrator import SieveOrchestrator
from darnit.sieve.models import CheckContext, ControlSpec

def test_execution_context_injected_in_batch():
    orchestrator = SieveOrchestrator()
    
    specs = [
        ControlSpec(control_id="C1", name="Control 1", level=1, metadata={}, passes=[], depends_on=[], tags=[]),
        ControlSpec(control_id="C2", name="Control 2", level=1, metadata={}, passes=[], depends_on=[], tags=[])
    ]
    
    contexts = {}
    
    def context_factory(cid: str) -> CheckContext:
        ctx = CheckContext(owner="o", repo="r", local_path="/local", default_branch="main", control_id=cid)
        contexts[cid] = ctx
        return ctx

    # We patch self.verify to just return a dummy
    from darnit.sieve.models import SieveResult
    import unittest.mock
    orchestrator.verify = unittest.mock.MagicMock()
    orchestrator.verify.side_effect = lambda spec, context: SieveResult(control_id=spec.control_id, status="PASS", message="O", level=1, source="s")

    orchestrator.verify_batch(specs, context_factory)
    
    assert len(contexts) == 2
    assert contexts["C1"].execution_context is not None
    assert contexts["C2"].execution_context is not None
    
    # Check it's the SAME execution context shared
    assert contexts["C1"].execution_context is contexts["C2"].execution_context
    assert contexts["C1"].execution_context.owner == "o"

