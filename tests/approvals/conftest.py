import pytest

from tests.authz.conftest import database as database
from tests.authz.conftest import password_hashes as password_hashes
from tests.authz.conftest import postgres_dsn as postgres_dsn
from tests.authz.conftest import service as service


@pytest.fixture
def authority(service):
    from backend.approvals.service import ApprovalService
    from tests.approvals.finance import SQLFinance

    with service.database.connection() as connection:
        connection.execute("UPDATE actors SET scopes=scopes || ARRAY['payment:execute']")
        connection.execute(
            "UPDATE actors SET scopes=scopes || ARRAY['mandate:manage'] WHERE role='SPONSOR'"
        )
    return ApprovalService(service, SQLFinance(service.database))


@pytest.fixture
def student(authority):
    return authority.auth.login("student", "a-long-student-test-password", "authority-tests").actor


@pytest.fixture
def sponsor(authority):
    return authority.auth.login("sponsor", "a-long-sponsor-test-password", "authority-tests").actor
