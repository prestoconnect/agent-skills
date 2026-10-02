from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
PLUGIN = ROOT / "plugins" / "prestoconnect"
SKILL_NAMES = {"prestoconnect:presto-pay", "presto-pay"}


def run_query(query: str, workdir: Path, model: str | None, timeout: int) -> dict:
    workdir.mkdir(parents=True)
    claude = shutil.which("claude")
    if claude is None:
        raise SystemExit("claude CLI not found on PATH")
    # Stopping after the first turn is enough: an agent that will use the skill loads it before doing anything else.
    command = [
        claude, "-p", "--output-format", "stream-json", "--verbose",
        "--setting-sources", "project", "--strict-mcp-config", "--plugin-dir", str(PLUGIN),
        "--max-turns", "1", "--no-session-persistence",
    ]
    if model:
        command += ["--model", model]
    try:
        stdout = subprocess.run(command, input=query, cwd=workdir, capture_output=True, text=True,
                                encoding="utf-8", timeout=timeout, check=False).stdout
    except subprocess.TimeoutExpired as expired:
        stdout = expired.stdout or ""
    (workdir / "events.jsonl").write_text(stdout, encoding="utf-8")

    tools: list[str] = []
    triggered, completed, cost = False, False, 0.0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for content in event["message"]["content"]:
                if content.get("type") != "tool_use":
                    continue
                skill = content["input"].get("skill", "") if content["name"] == "Skill" else ""
                tools.append(f"Skill:{skill}" if skill else content["name"])
                triggered = triggered or skill in SKILL_NAMES
        elif event.get("type") == "result":
            completed = True
            cost = event.get("total_cost_usd") or 0.0
    return {"triggered": triggered, "completed": completed, "tools": tools, "cost": cost}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that Claude Code loads the presto-pay skill for the right prompts")
    parser.add_argument("--runs-per-query", type=int, default=3)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--model", help="Claude Code model alias or name; defaults to the CLI default")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--runs-dir", type=Path, default=EVALS / "runs")
    args = parser.parse_args()

    queries = json.loads((EVALS / "trigger-evals.json").read_text(encoding="utf-8"))
    run_root = args.runs_dir.resolve() / ("trigger-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    run_root.mkdir(parents=True, exist_ok=False)
    print(f"run: {run_root}", flush=True)

    jobs = [(index, attempt) for index in range(len(queries)) for attempt in range(args.runs_per_query)]

    def run_job(job: tuple[int, int]) -> dict:
        index, attempt = job
        result = run_query(queries[index]["query"], run_root / f"q{index:02d}-r{attempt}", args.model, args.timeout)
        return {"index": index, "attempt": attempt, **result}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_job, jobs))
    (run_root / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    passed = 0
    for index, query in enumerate(queries):
        rows = [row for row in results if row["index"] == index]
        hits = sum(row["triggered"] for row in rows)
        incomplete = sum(not row["completed"] for row in rows)
        ok = (hits * 2 > len(rows)) == query["should_trigger"]
        passed += ok
        expected = "trigger" if query["should_trigger"] else "skip"
        note = f" incomplete={incomplete}" if incomplete else ""
        print(f"{'PASS' if ok else 'FAIL'} {expected:7} {hits}/{len(rows)}{note}  {query['query'][:90]}")
        if not ok:
            for row in rows:
                print(f"    run {row['attempt']}: {row['tools']}")
    print(f"\n{passed}/{len(queries)} queries passed, ${sum(row['cost'] for row in results):.2f}")
    return 0 if passed == len(queries) else 1


if __name__ == "__main__":
    sys.exit(main())
