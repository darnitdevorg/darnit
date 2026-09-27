# Contract: Step Declarations (framework TOML)

## Fields

```toml
[[controls."OSPS-DO-01.01".passes]]
handler = "file_exists"
files = ["README.md", "README.rst"]
# ceiling for file_exists is {fail}: a missing README proves FAIL; presence alone never concludes PASS

[[controls."OSPS-DO-01.01".passes]]
handler = "pattern"
files = ["README.md"]
patterns = ["(?i)install", "(?i)usage"]
# ceiling {fail}; a miss is INCONCLUSIVE unless fail_on_miss = true

[[controls."OSPS-DO-01.01".passes]]
handler = "llm_eval"
prompt = "..."
# produces a PASS candidate or a suggestive FAIL; never concludes PASS

[[controls."OSPS-LE-03.01".passes]]
handler = "file_exists"
files = ["LICENSE", "LICENSE.md"]
existence = true          # the requirement is literally that the file exists: may conclude PASS

[[controls."OSPS-AC-03.01".passes]]
handler = "gh_api"
endpoint = "/repos/$OWNER/$REPO/branches/$BRANCH/protection"
fail_on_status = [404]    # 404 proves "no branch protection"; 401/403/429/5xx are ERROR
expr = 'has(response.body.required_pull_request_reviews)'

[[controls."OSPS-XX-01.01".passes]]
handler = "pattern"
files = ["SOMEFILE.md"]
patterns = ["..."]
concludes = ["fail", "pass"]
promotion = { outcome = "pass", corpus = "c-2026.10.01-3f9a", note = "0 false PASS across 14 fixtures" }
```

## Rules

1. Effective set = (`existence_ceiling` if `existence = true` else `ceiling`), narrowed by `concludes` if present, widened only by `promotion`.
2. Loading rejects: `existence` on a non-presence/pattern handler; `fail_on_miss` without `fail` in the effective set; `fail_on_status` on a handler other than `gh_api` or without `fail` in the effective set; any outcome outside the ceiling without a promotion. Errors name the framework, control, step index, and outcome.
3. Validation runs in every control-loading path after plugin handlers register.
4. A step result whose outcome is not in the effective set is recorded as evidence; evaluation continues.
5. Plugin handlers register their ceiling with the handler; a plugin handler that registers no ceiling defaults to `{}` (evidence only).
