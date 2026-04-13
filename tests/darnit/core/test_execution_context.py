from darnit.core.models import ExecutionContext, CheckResult

def test_get_or_run_tool():
    ctx = ExecutionContext("owner", "repo", "/path")
    calls = []
    
    def my_tool():
        calls.append(1)
        return "data"
        
    res = ctx.get_or_run_tool("my_tool", my_tool)
    assert res == "data"
    assert len(calls) == 1
    
    res2 = ctx.get_or_run_tool("my_tool", my_tool)
    assert res2 == "data"
    assert len(calls) == 1

def test_cache_result():
    ctx = ExecutionContext("owner", "repo", "/path")
    assert ctx.get_cached_result("CTRL-1") is None
    
    res = CheckResult(control_id="CTRL-1", status="PASS", message="OK")
    ctx.cache_result(res)
    
    assert ctx.get_cached_result("CTRL-1") == res
    assert ctx.get_cached_result("CTRL-2") is None

def test_concurrent_execution_context():
    import concurrent.futures
    import time
    
    ctx = ExecutionContext("owner", "repo", "/path")
    calls = []

    def slow_tool():
        calls.append(1)
        time.sleep(0.1)
        return "data"

    def worker(i):
        return ctx.get_or_run_tool("my_tool", slow_tool)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(worker, range(20)))

    # Should have run exactly once due to the lock
    assert len(calls) == 1
    assert all(r == "data" for r in results)

    # concurrent cache_result
    def cache_writer(i):
        ctx.cache_result(CheckResult(control_id=f"CTRL-{i}", status="PASS", message="OK"))
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(cache_writer, range(20)))
        
    assert ctx.get_cached_result("CTRL-5").status == "PASS"

