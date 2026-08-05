# generated-by: central-agent-governance
import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]

def blocked(message):
    raise SystemExit("blocked: " + message)

def git(*arguments, check=True):
    result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True)
    if check and result.returncode != 0:
        blocked("git command failed: " + " ".join(arguments))
    return result.stdout

def status_entries():
    output = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = []
    for entry in output.split("\0"):
        if not entry:
            continue
        status = entry[:2]
        path = entry[3:].replace("\\", "/")
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append((status, path))
    return entries

def matches(path, patterns):
    return any(pattern == "**" or fnmatch.fnmatch(path, pattern) for pattern in patterns)

manifest_path = root / ".agent-governance" / "manifest.json"
if not manifest_path.is_file():
    blocked("manifest missing")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("status") != "managed":
    blocked("project is not managed")

branch = (
    git("branch", "--show-current").strip()
    or os.environ.get("GITHUB_HEAD_REF", "").strip()
    or os.environ.get("GITHUB_REF_NAME", "").strip()
)
task_files = list((root / ".agent-governance" / "tasks").glob("*.json"))
matching_tasks = []
for task_file in task_files:
    candidate = json.loads(task_file.read_text(encoding="utf-8"))
    if candidate.get("branch") == branch:
        matching_tasks.append(candidate)
task = matching_tasks[0] if len(matching_tasks) == 1 else None

parser = argparse.ArgumentParser()
parser.add_argument("gate", choices=["status", "manifest", "task-packet", "branch-policy", "scope", "test-integrity", "secrets", "focused-tests", "regression", "handoff"])
args = parser.parse_args()

if args.gate in {"status", "manifest"}:
    print(args.gate + ": passed")
    raise SystemExit(0)
if task is None:
    blocked("exactly one task packet must match current branch")

base_sha = str(task.get("base_sha", ""))
if re.fullmatch(r"[0-9a-f]{40}", base_sha) is None:
    blocked("task base_sha missing or invalid")
if subprocess.run(["git", "cat-file", "-e", base_sha + "^{commit}"], cwd=root, capture_output=True).returncode != 0:
    blocked("task base_sha does not exist")

activation_candidates = list(filter(None, git("rev-list", "--reverse", base_sha + "..HEAD").splitlines()))
if not activation_candidates:
    blocked("task activation commit missing")
activation_commit = activation_candidates[0]
activation_subject = git("show", "--format=%s", "--no-patch", activation_commit).strip()
expected_subject = "chore(governance): activate " + str(task["task_id"])
if activation_subject != expected_subject:
    blocked("first commit after base must be task activation")
task_relative = ".agent-governance/tasks/" + str(task["task_id"]) + ".json"
activation_paths = set(filter(None, git("diff-tree", "--no-commit-id", "--name-only", "-r", activation_commit).splitlines()))
if activation_paths != {task_relative}:
    blocked("activation commit may only change its task packet")
activation_task = git("show", activation_commit + ":" + task_relative)
if activation_task != (root / task_relative).read_text(encoding="utf-8"):
    blocked("task packet changed after activation")

def changed_entries():
    committed = set(filter(None, git("diff", "--name-only", activation_commit + "..HEAD").splitlines()))
    result = [("C ", path.replace("\\", "/")) for path in committed]
    allowed_untracked = manifest.get("allowed_untracked_paths", [])
    for status, path in status_entries():
        if status == "??" and matches(path, allowed_untracked):
            continue
        result.append((status, path))
    return sorted(set(result))

changed = changed_entries()
changed_paths = sorted({path for _, path in changed})
if len(changed_paths) > int(task.get("max_changed_files", 0)):
    blocked("max_changed_files exceeded")
numstat = git("diff", "--numstat", activation_commit + "..HEAD")
diff_lines = 0
for line in numstat.splitlines():
    additions, deletions, _ = line.split("\t", 2)
    if additions.isdigit():
        diff_lines += int(additions)
    if deletions.isdigit():
        diff_lines += int(deletions)
for status, path in status_entries():
    if status == "??" and not matches(path, manifest.get("allowed_untracked_paths", [])):
        target = root / path
        if target.is_file() and target.stat().st_size <= 1000000:
            diff_lines += len(target.read_text(encoding="utf-8", errors="replace").splitlines())
if diff_lines > int(task.get("max_diff_lines", 0)):
    blocked("max_diff_lines exceeded")

if args.gate == "task-packet":
    for field in ("task_id", "project_id", "branch", "base_sha", "scope", "tdd", "delivery"):
        if field not in task:
            blocked("task packet missing field: " + field)
    if task["project_id"] != manifest["project_id"]:
        blocked("task project mismatch")

elif args.gate == "branch-policy":
    expected = "codex/" + manifest["project_id"] + "/"
    if not branch.startswith(expected):
        blocked("branch policy violation")
    if git("rev-list", "--min-parents=2", activation_commit + "..HEAD").strip():
        blocked("merge commits after task base are forbidden")

elif args.gate == "scope":
    scope = task["scope"]
    allowed = scope.get("allowed_paths", []) + scope.get("allowed_create_paths", [])
    forbidden = scope.get("read_denylist", []) + scope.get("write_denylist", []) + manifest.get("protected_paths", [])
    governance_exempt = [".agent-governance/**", ".github/workflows/governance.yml", "tools/governance/**", "AGENTS.md"]
    for status, path in changed:
        if matches(path, governance_exempt):
            continue
        if matches(path, forbidden):
            blocked("forbidden path changed: " + path)
        if not matches(path, allowed):
            blocked("outside task scope: " + path)

elif args.gate == "test-integrity":
    marker = re.compile(r"pytest\.mark\.(?:skip|xfail)|@unittest\.skip|\bskipTest\(")
    for status, path in changed:
        if not (path.startswith("tests/") or "/test" in path):
            continue
        target = root / path
        if not target.exists() or "D" in status:
            blocked("test deletion is forbidden: " + path)
        if marker.search(target.read_text(encoding="utf-8", errors="replace")):
            blocked("skip/xfail marker is forbidden: " + path)

elif args.gate == "secrets":
    rules = (("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")), ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")), ("credential assignment", re.compile(r"(?i)(?:api[_-]?key|secret|token|password)\s*=\s*['\"][^'\"]{12,}")))
    for status, path in changed:
        if matches(path, manifest.get("allowed_untracked_paths", [])) and status == "??":
            continue
        if Path(path).name.startswith(".env"):
            blocked("sensitive environment file changed: " + path)
        target = root / path
        if not target.is_file() or target.stat().st_size > 1000000:
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        for label, rule in rules:
            if rule.search(text):
                blocked(label + " detected in " + path)

elif args.gate in {"focused-tests", "regression"}:
    field = "green_command" if args.gate == "focused-tests" else "regression_commands"
    commands = task["tdd"].get(field, [])
    if isinstance(commands, str):
        commands = [commands]
    if not commands:
        blocked(field + " missing")
    for command in commands:
        result = subprocess.run(shlex.split(command), cwd=root)
        if result.returncode != 0:
            blocked(args.gate + " failed")

elif args.gate == "handoff":
    handoff = root / task["delivery"]["handoff_file"]
    if not handoff.is_file():
        blocked("handoff missing")
    report = json.loads(handoff.read_text(encoding="utf-8"))
    if report.get("branch") != branch or not report.get("commit_sha") or report.get("base_sha") != base_sha:
        blocked("handoff does not match current branch/base/commit")
    if subprocess.run(["git", "cat-file", "-e", str(report["commit_sha"]) + "^{commit}"], cwd=root, capture_output=True).returncode != 0:
        blocked("handoff commit does not exist")

print(args.gate + ": passed")
