from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_production_compose_declares_postgres_and_healthcheck() -> None:
    compose = _read("compose.yaml")
    assert "postgres:" in compose
    assert "healthcheck:" in compose
    assert "FINOPS_DATABASE_URL" in compose
    assert "FINOPS_IDENTITY_MODE: signed" in compose
    assert "FINOPS_IDENTITY_SECRET" in compose


def test_production_repository_uses_postgres_url_and_rls_session_context() -> None:
    persistence = _read("app/finops/persistence.py")
    migration_dir = ROOT / "migrations" / "finops"
    migrations = "\n".join(path.read_text(encoding="utf-8") for path in migration_dir.glob("*.sql"))
    assert "PostgresRepository" in persistence
    assert "FINOPS_DATABASE_URL" in persistence
    assert "set_config" in migrations
    assert "ENABLE ROW LEVEL SECURITY" in migrations
    assert "FORCE ROW LEVEL SECURITY" in persistence
    assert "FORCE ROW LEVEL SECURITY" in migrations
    assert "UNIQUE (tenant_id, idempotency_key)" in persistence
    assert "ON CONFLICT (tenant_id, idempotency_key)" in persistence


def test_production_api_does_not_use_client_rows_as_query_source() -> None:
    api = _read("app/finops/api.py")
    assert "payload.rows" not in api
    assert "trusted_rows" in api


def test_real_model_and_github_ticket_adapters_are_explicit() -> None:
    model = _read("app/finops/intent/model.py")
    ticket = _read("app/finops/tickets/service.py")
    assert "QWEN_API_KEY" in model
    assert "GitHub" in ticket or "github" in ticket
    assert "blocked" in model.lower()


def test_production_sources_do_not_select_fake_adapters() -> None:
    sources = list((ROOT / "app").rglob("*.py"))
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in sources)
    assert "fake repository" not in text
    assert "recordedadapter" not in text
