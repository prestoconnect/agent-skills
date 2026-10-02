from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
SKILL = ROOT / "plugins" / "prestoconnect" / "skills" / "presto-pay" / "SKILL.md"


def checked_fixture_path(case_name: str, relative_path: str) -> Path:
    fixture_root = (EVALS / "fixtures" / case_name).resolve()
    source = (fixture_root / relative_path).resolve()
    if not source.is_relative_to(fixture_root) or not source.is_file():
        raise ValueError(f"Missing or unsafe fixture path: {case_name}/{relative_path}")
    return source


def prepare_workspace(case: dict, arm: str, run_root: Path) -> Path:
    workspace = run_root / case["name"] / arm
    workspace.mkdir(parents=True)
    for relative_path in case["files"]:
        source = checked_fixture_path(case["name"], relative_path)
        destination = workspace / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return workspace


def run_case(case: dict, arm: str, run_root: Path, timeout: int) -> dict:
    workspace = prepare_workspace(case, arm, run_root)
    prompt = case["prompt"]
    if arm == "skill":
        prompt = f"Read and apply the Presto Pay skill at {SKILL}. Then complete this request:\n\n{prompt}"
    prompt += "\n\nWork only in this fixture. Do not install dependencies or contact live services. State any unfinished work."
    result_path = workspace.parent / f"{arm}-answer.txt"
    if os.name == "nt":
        codex = Path(shutil.which("codex.cmd") or "codex.cmd")
        executable = ["node", str(codex.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js")]
    else:
        executable = ["codex"]
    command = [
        *executable, "exec", "--ephemeral", "--skip-git-repo-check", "--disable", "memories",
        "-C", str(workspace), "-s", "workspace-write", "--json",
        "-o", str(result_path), "-",
    ]
    process_options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with (workspace.parent / f"{arm}-events.jsonl").open("w", encoding="utf-8") as events:
        with (workspace.parent / f"{arm}-stderr.txt").open("w", encoding="utf-8") as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=events, stderr=errors,
                                       text=True, encoding="utf-8", **process_options)
            try:
                process.communicate(input=prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, check=False)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                return {"case": case["name"], "arm": arm, "error": f"timed out after {timeout}s",
                        "workspace": str(workspace)}
    return {"case": case["name"], "arm": arm, "exit_code": process.returncode,
            "workspace": str(workspace), "answer": str(result_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", help="Run only the named case; repeatable")
    parser.add_argument("--arm", choices=("both", "skill", "baseline"), default="both")
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--runs-dir", type=Path, default=EVALS / "runs",
                        help="Where to write runs; use a directory outside this repository so the baseline can't read the skill")
    args = parser.parse_args()
    cases = json.loads((EVALS / "evals.json").read_text(encoding="utf-8"))["evals"]
    if args.case:
        cases = [case for case in cases if case["name"] in args.case]
        if len(cases) != len(set(args.case)):
            parser.error("unknown or duplicate case name")
    if not cases:
        parser.error("no cases selected")
    run_root = args.runs_dir.resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_root.mkdir(parents=True, exist_ok=False)
    print(f"run: {run_root}", flush=True)
    arms = ("baseline", "skill") if args.arm == "both" else (args.arm,)
    results = []
    results_path = run_root / "results.json"
    for case in cases:
        for arm in arms:
            print(f"running: {case['name']} {arm}", flush=True)
            result = run_case(case, arm, run_root, args.timeout)
            results.append(result)
            results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(json.dumps(result), flush=True)
    return 0 if all(result.get("exit_code") == 0 for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
