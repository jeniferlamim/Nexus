import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="nexus-test-")
os.environ["DATABASE_URL"] = os.environ.get("NEXUS_TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["NEXUS_SYNC_JOBS"] = "1"
os.environ["AUTH_MODE"] = "dev"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from nexus_engine.api.app import app  # noqa: E402
from nexus_engine.demo.generator import generate  # noqa: E402
from nexus_engine.seed import T1, T2, U_ADMIN, U_ANALYST, U_AUDITOR, U_CFO, U_DIRECTOR  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def headers(user: str, tenant: str = T1) -> dict:
    return {"X-Nexus-User": user, "X-Nexus-Tenant": tenant}


@pytest.fixture(scope="session")
def dataset():
    return generate()


@pytest.fixture(scope="session")
def loaded(client):
    r = client.post("/api/demo/load", headers=headers(U_ANALYST))
    assert r.status_code == 202
    return True


H = headers
__all__ = ["H", "T1", "T2", "U_ADMIN", "U_ANALYST", "U_AUDITOR", "U_CFO", "U_DIRECTOR"]
