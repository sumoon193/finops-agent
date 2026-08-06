import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_public_repository_has_no_internal_governance_files() -> None:
    forbidden = [".agent-governance", "AGENTS.md", "tools/governance", "tests/governance", ".github/workflows/governance.yml"]
    result = subprocess.run(["git", "ls-files", "--", *forbidden], cwd=ROOT, check=True, capture_output=True, text=True)
    assert result.stdout.strip() == ""


def test_readme_is_public_facing_and_portable() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "D:\\Code\\" not in readme
    assert "D:\\py\\" not in readme
    assert ".agent-governance" not in readme
    assert "完成证明" not in readme
