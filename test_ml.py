from pathlib import Path

from darnit_baseline.threat_model.ts_discovery import discover_all


def main():
    repo_root = Path("packages/darnit-hello")
    res = discover_all(repo_root)
    print(f"Total findings: {len(res.findings)}")
    print("Findings:")
    for f in res.findings:
        print(f"[{f.category.value}] {f.title} (confidence: {f.confidence.value})")

    print("\nEntry points:")
    for e in res.entry_points:
        print(f"[{e.kind.value}] {e.name}")

if __name__ == "__main__":
    main()
