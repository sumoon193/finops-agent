from fastapi.testclient import TestClient

from app.finops import api
from app.finops.persistence import Record, SQLiteRepository


def test_running_query_cancel_is_persisted_in_durable_repository(
    tmp_path, monkeypatch
) -> None:
    repository = SQLiteRepository(tmp_path / "finops.sqlite3", "query_run")
    monkeypatch.setattr(api.repos, "query_run", repository)

    class RecoveryLedger:
        def execute(self, *_args, **_kwargs):
            return {"status": "cancelled"}

    monkeypatch.setattr(
        "app.finops.recovery.ledger.IdentityContext", lambda: RecoveryLedger()
    )
    query_id = "qry-persistent-cancel"
    repository.put(
        Record(
            id=query_id,
            idempotency_key="query:persistent-cancel",
            payload={"tenant_id": "acme", "status": "running"},
        )
    )

    response = TestClient(api.app).delete(
        f"/queries/{query_id}",
        headers={"X-Tenant-Id": "acme", "X-Request-Id": "req-cancel"},
    )

    assert response.status_code == 202
    persisted = repository.get(query_id)
    assert persisted is not None
    assert persisted.payload["status"] == "cancelled"
