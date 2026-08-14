import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import models
from app.database.database import Base
from app.main import app, get_db
import app.main as main_module


class AuditDeadlockRetryTests(unittest.TestCase):
    """Covers `_record_audit_log(..., retry_on_deadlock=...)` - see app/core/audit.py
    and app/main.py for why a MariaDB 1213 deadlock needs a full session rollback
    (InnoDB rolls back the whole victim transaction, not just the losing statement)
    and why that's only safe to auto-retry when nothing else is pending in the
    session."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _fake_request(self):
        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers.get.return_value = "pytest"
        return request

    def _deadlock_exc(self):
        orig = MagicMock()
        orig.args = (1213, "Deadlock found when trying to get lock; try restarting transaction")
        return OperationalError("INSERT INTO audit_logs ...", {}, orig)

    def test_retry_on_deadlock_recovers_after_transient_deadlock(self):
        db = self.SessionLocal()
        real_append = main_module._append_audit_log
        call_count = {"n": 0}

        def flaky_append(db_, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise self._deadlock_exc()
            return real_append(db_, **kwargs)

        with patch.object(main_module, "_append_audit_log", side_effect=flaky_append):
            main_module._record_audit_log(
                db,
                request=self._fake_request(),
                user_email="tech@sakafarma.com",
                action="TEST_VIEW",
                status_value="SUCCESS",
                retry_on_deadlock=True,
            )

        self.assertEqual(call_count["n"], 2)
        logged = db.query(models.AuditLog).filter(models.AuditLog.action == "TEST_VIEW").first()
        self.assertIsNotNone(logged)
        db.close()

    def test_without_retry_flag_deadlock_raises_immediately(self):
        db = self.SessionLocal()

        with patch.object(main_module, "_append_audit_log", side_effect=self._deadlock_exc()):
            with self.assertRaises(OperationalError):
                main_module._record_audit_log(
                    db,
                    request=self._fake_request(),
                    user_email="tech@sakafarma.com",
                    action="TEST_WRITE",
                    status_value="SUCCESS",
                )
        db.close()

    def test_non_deadlock_operational_error_is_not_retried(self):
        db = self.SessionLocal()
        orig = MagicMock()
        orig.args = (1046, "No database selected")
        non_deadlock_exc = OperationalError("SELECT ...", {}, orig)
        call_count = {"n": 0}

        def always_fail(db_, **kwargs):
            call_count["n"] += 1
            raise non_deadlock_exc

        with patch.object(main_module, "_append_audit_log", side_effect=always_fail):
            with self.assertRaises(OperationalError):
                main_module._record_audit_log(
                    db,
                    request=self._fake_request(),
                    user_email="tech@sakafarma.com",
                    action="TEST_VIEW",
                    status_value="SUCCESS",
                    retry_on_deadlock=True,
                )

        self.assertEqual(call_count["n"], 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
