import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.database import models
from app.database.database import Base
from app.main import app, get_db
import app.main as main_module


class Form4BackendSecurityTests(unittest.TestCase):
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

    def create_user(
        self,
        *,
        email: str = "operator@sakafarma.com",
        password: str = "Strong1!",
        role: str = "technician",
        is_active: bool = True,
        email_notifications: bool = True,
    ) -> models.User:
        db = self.SessionLocal()
        user = models.User(
            full_name="SPMS Operator",
            email=email,
            hashed_password=security.get_password_hash(password),
            role=role,
            is_active=is_active,
            email_notifications=email_notifications,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.close()
        return user

    def auth_headers(self, user: models.User) -> dict[str, str]:
        token = security.create_access_token(data={"user_id": user.id, "role": user.role})
        return {"Authorization": f"Bearer {token}"}

    def test_users_me_includes_email_notifications_and_preferences_persist(self):
        user = self.create_user(email_notifications=False)

        response = self.client.get("/api/users/me", headers=self.auth_headers(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email_notifications"], False)

        update = self.client.patch(
            "/api/users/me/preferences",
            json={"email_notifications": True},
            headers=self.auth_headers(user),
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()["email_notifications"], True)

        db = self.SessionLocal()
        refreshed = db.query(models.User).filter(models.User.id == user.id).first()
        audit = db.query(models.AuditLog).filter(models.AuditLog.action == "PREFERENCES_UPDATED").first()
        db.close()

        self.assertTrue(refreshed.email_notifications)
        self.assertIsNotNone(audit)

    def test_inactive_user_cannot_login_or_use_token(self):
        inactive = self.create_user(is_active=False)

        login_response = self.client.post(
            "/api/login",
            data={"username": inactive.email, "password": "Strong1!"},
        )
        self.assertEqual(login_response.status_code, 403)

        token_response = self.client.get("/api/users/me", headers=self.auth_headers(inactive))
        self.assertEqual(token_response.status_code, 401)

    def test_reset_password_enforces_policy_scope_and_successful_login(self):
        user = self.create_user(password="OldPass1!")
        db = self.SessionLocal()
        stored = db.query(models.User).filter(models.User.id == user.id).first()
        stored.reset_otp = "123456"
        stored.reset_otp_expire = datetime.utcnow() + timedelta(minutes=15)
        db.commit()
        db.close()

        weak_response = self.client.post(
            "/api/reset-password",
            json={"email": user.email, "otp": "123456", "new_password": "weak"},
        )
        self.assertEqual(weak_response.status_code, 400)

        wrong_otp_response = self.client.post(
            "/api/reset-password",
            json={"email": user.email, "otp": "000000", "new_password": "NewPass1!"},
        )
        self.assertEqual(wrong_otp_response.status_code, 400)

        success_response = self.client.post(
            "/api/reset-password",
            json={"email": user.email, "otp": "123456", "new_password": "NewPass1!"},
        )
        self.assertEqual(success_response.status_code, 200)

        login_response = self.client.post(
            "/api/login",
            data={"username": user.email, "password": "NewPass1!"},
        )
        self.assertEqual(login_response.status_code, 200)

    def test_register_and_dashboard_summary_create_audit_evidence(self):
        test_email = "new.user@gmail.com"
        main_module.pending_registration_otps[test_email] = {
            "otp": "123456",
            "expires": datetime.utcnow() + timedelta(minutes=15),
        }
        register_response = self.client.post(
            "/api/register",
            json={
                "full_name": "New User",
                "email": test_email,
                "password": "Strong1!",
                "otp": "123456",
            },
        )
        self.assertEqual(register_response.status_code, 201)

        user = self.create_user(email="dashboard@sakafarma.com")
        summary_response = self.client.get(
            "/api/dashboard/summary",
            headers=self.auth_headers(user),
        )
        self.assertEqual(summary_response.status_code, 200)
        self.assertIn("artifact_status", summary_response.json())

        db = self.SessionLocal()
        actions = {row.action for row in db.query(models.AuditLog).all()}
        db.close()

        self.assertIn("USER_REGISTER", actions)
        self.assertIn("DASHBOARD_SUMMARY_VIEW", actions)

    def test_audit_logs_are_admin_only_and_exportable(self):
        technician = self.create_user(email="tech@sakafarma.com", role="technician")
        admin = self.create_user(email="admin@sakafarma.com", role="admin")

        denied = self.client.get("/api/audit-logs", headers=self.auth_headers(technician))
        self.assertEqual(denied.status_code, 403)

        denied_verify = self.client.get("/api/audit-logs/verify", headers=self.auth_headers(technician))
        self.assertEqual(denied_verify.status_code, 403)

        allowed = self.client.get("/api/audit-logs", headers=self.auth_headers(admin))
        self.assertEqual(allowed.status_code, 200)

        verified = self.client.get("/api/audit-logs/verify", headers=self.auth_headers(admin))
        self.assertEqual(verified.status_code, 200)
        self.assertIn(verified.json()["overall_status"], {"VERIFIED", "COMPROMISED"})
        self.assertIn("total_logs_checked", verified.json())

        exported = self.client.get("/api/audit-logs/export", headers=self.auth_headers(admin))
        self.assertEqual(exported.status_code, 200)
        self.assertIn("text/csv", exported.headers["content-type"])
        self.assertIn("User Email", exported.text)
        self.assertIn("Record Hash", exported.text)
        self.assertIn("Previous Hash", exported.text)

    def test_audit_log_creation_generates_sha256_hash_fields(self):
        user = self.create_user(email="hash-fields@sakafarma.com")

        response = self.client.patch(
            "/api/users/me/preferences",
            json={"email_notifications": False},
            headers=self.auth_headers(user),
        )
        self.assertEqual(response.status_code, 200)

        db = self.SessionLocal()
        audit = db.query(models.AuditLog).filter(models.AuditLog.action == "PREFERENCES_UPDATED").first()
        db.close()

        self.assertIsNotNone(audit)
        self.assertEqual(len(audit.record_hash), 64)
        self.assertEqual(audit.hash_algorithm, "SHA-256")
        self.assertEqual(audit.hash_payload_version, "audit-v1")

    def test_audit_hash_chain_verifies_clean_rows(self):
        admin = self.create_user(email="verify-clean@sakafarma.com", role="admin")
        self.client.patch(
            "/api/users/me/preferences",
            json={"email_notifications": False},
            headers=self.auth_headers(admin),
        )

        response = self.client.get("/api/audit-logs/verify", headers=self.auth_headers(admin))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["overall_status"], "VERIFIED")
        self.assertEqual(payload["invalid_log_ids"], [])
        self.assertEqual(payload["total_logs_checked"], payload["valid_count"])
        self.assertEqual(len(payload["chain_head_hash"]), 64)

    def test_audit_hash_chain_detects_manual_tampering(self):
        admin = self.create_user(email="verify-tamper@sakafarma.com", role="admin")
        self.client.patch(
            "/api/users/me/preferences",
            json={"email_notifications": False},
            headers=self.auth_headers(admin),
        )

        db = self.SessionLocal()
        audit = db.query(models.AuditLog).filter(models.AuditLog.action == "PREFERENCES_UPDATED").first()
        tampered_id = audit.id
        audit.status = "FAILED"
        db.commit()
        db.close()

        response = self.client.get("/api/audit-logs/verify", headers=self.auth_headers(admin))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["overall_status"], "COMPROMISED")
        self.assertIn(tampered_id, payload["invalid_log_ids"])

    def test_alerts_endpoint_returns_saved_anomaly_events(self):
        user = self.create_user(email="alerts@sakafarma.com")
        db = self.SessionLocal()
        db.add(
            models.AnomalyEvent(
                machine_id="PMA Granulator #01",
                reconstruction_error=0.5,
                threshold=0.2,
                is_anomaly=True,
                severity="warning",
                threshold_policy="test policy",
                model_version="test-model",
            )
        )
        db.commit()
        db.close()

        response = self.client.get("/api/alerts", headers=self.auth_headers(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["severity"], "warning")

        db = self.SessionLocal()
        audit = db.query(models.AuditLog).filter(models.AuditLog.action == "ALERTS_VIEW").first()
        db.close()
        self.assertIsNotNone(audit)

    def test_admin_threshold_override_is_audited_and_resettable(self):
        technician = self.create_user(email="threshold-tech@sakafarma.com", role="technician")
        admin = self.create_user(email="threshold-admin@sakafarma.com", role="admin")

        denied = self.client.patch(
            "/api/settings/threshold",
            json={"threshold": 0.5, "reason": "demo sensitivity review"},
            headers=self.auth_headers(technician),
        )
        self.assertEqual(denied.status_code, 403)

        updated = self.client.patch(
            "/api/settings/threshold",
            json={"threshold": 0.5, "reason": "demo sensitivity review"},
            headers=self.auth_headers(admin),
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["threshold"], 0.5)
        self.assertEqual(updated.json()["threshold_source"], "admin_override")

        rows = [{"timestamp": datetime.utcnow()} for _ in range(15)]
        with patch.object(main_module, "validate_prediction_window", return_value=rows), patch.object(
            main_module.inference_service,
            "window_size",
            return_value=15,
        ), patch.object(
            main_module.inference_service,
            "feature_names",
            return_value=["impeller_rpm"],
        ), patch.object(
            main_module.inference_service,
            "predict_window",
            return_value={
                "reconstruction_error": 0.3,
                "threshold": 0.2,
                "is_anomaly": True,
                "threshold_policy": "artifact policy",
                "window_size": 15,
                "features": ["impeller_rpm"],
                "model_version": "test-model",
                "limitations": [],
            },
        ):
            prediction = self.client.post(
                "/api/predict/anomaly",
                json={"machine_id": "PMA Granulator #01", "window": [{} for _ in range(15)]},
                headers=self.auth_headers(admin),
            )

        self.assertEqual(prediction.status_code, 200)
        self.assertEqual(prediction.json()["threshold"], 0.5)
        self.assertEqual(prediction.json()["threshold_source"], "admin_override")
        self.assertFalse(prediction.json()["is_anomaly"])

        reset = self.client.delete("/api/settings/threshold", headers=self.auth_headers(admin))
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.json()["threshold_source"], "artifact_baseline")

        db = self.SessionLocal()
        actions = {row.action for row in db.query(models.AuditLog).all()}
        db.close()
        self.assertIn("THRESHOLD_OVERRIDE_UPDATE", actions)
        self.assertIn("THRESHOLD_OVERRIDE_RESET", actions)

    def test_alert_acknowledgement_ticket_lifecycle_export_and_status(self):
        user = self.create_user(email="workflow@sakafarma.com", role="admin")
        db = self.SessionLocal()
        alert = models.AnomalyEvent(
            machine_id="PMA Granulator #01",
            reconstruction_error=0.6,
            threshold=0.2,
            is_anomaly=True,
            severity="critical",
            threshold_policy="test policy",
            threshold_source="artifact_baseline",
            model_version="test-model",
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        alert_id = alert.id
        db.close()

        ack = self.client.post(
            f"/api/alerts/{alert_id}/acknowledge",
            json={"note": "Supervisor reviewed anomaly."},
            headers=self.auth_headers(user),
        )
        self.assertEqual(ack.status_code, 200)
        self.assertEqual(ack.json()["acknowledged_by"], user.email)

        ticket = self.client.post(
            "/api/tickets",
            json={
                "machine_id": "PMA Granulator #01",
                "anomaly_event_id": alert_id,
                "issue_description": "encrypted issue payload",
            },
            headers=self.auth_headers(user),
        )
        self.assertEqual(ticket.status_code, 201)
        self.assertEqual(ticket.json()["status"], "OPEN")

        in_review = self.client.patch(
            f"/api/tickets/{ticket.json()['id']}/status",
            json={"status": "IN_REVIEW"},
            headers=self.auth_headers(user),
        )
        self.assertEqual(in_review.status_code, 200)
        self.assertEqual(in_review.json()["status"], "IN_REVIEW")

        resolved = self.client.patch(
            f"/api/tickets/{ticket.json()['id']}/status",
            json={"status": "RESOLVED", "resolution_note": "encrypted resolution payload"},
            headers=self.auth_headers(user),
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["status"], "RESOLVED")
        self.assertIsNotNone(resolved.json()["resolved_at"])

        exported = self.client.get("/api/alerts/export", headers=self.auth_headers(user))
        self.assertEqual(exported.status_code, 200)
        self.assertIn("Linked Ticket IDs", exported.text)
        self.assertIn("Supervisor reviewed anomaly.", exported.text)

        system_status = self.client.get("/api/system/status", headers=self.auth_headers(user))
        self.assertEqual(system_status.status_code, 200)
        self.assertIn("database", system_status.json())
        self.assertIn("audit_chain", system_status.json())


if __name__ == "__main__":
    unittest.main()
