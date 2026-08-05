"""Regression contracts for generated files that must stay outside task scope."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_push_branch_falls_back_to_github_ref_name() -> None:
    source = (ROOT / "tools" / "governance" / "run.py").read_text(encoding="utf-8")
    assert "GITHUB_REF_NAME" in source


def test_editable_install_metadata_is_ignored() -> None:
    patterns = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert any("egg-info" in pattern for pattern in patterns)


def test_governance_commands_use_current_python_interpreter() -> None:
    source = (ROOT / "tools" / "governance" / "run.py").read_text(encoding="utf-8")
    assert "sys.executable" in source
