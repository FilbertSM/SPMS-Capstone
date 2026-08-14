import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.database import models
from app.database.database import Base
from app.main import app, get_db
from app.services import telegram_service


class TelegramNotificationTests(unittest.TestCase):
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

    def create_user(self, *, email="user@sakafarma.com", password="Strong1!", role="technician", **extra):
        db = self.SessionLocal()
        user = models.User(
            full_name="SPMS User",
            email=email,
            hashed_password=security.get_password_hash(password),
            role=role,
            is_active=True,
            **extra,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.close()
        return user

    def auth_headers(self, user: models.User) -> dict[str, str]:
        token = security.create_access_token(data={"user_id": user.id, "role": user.role})
        return {"Authorization": f"Bearer {token}"}

    def _enable_notifications(self, *, min_severity="warning"):
        db = self.SessionLocal()
        db.add(
            models.RuntimeSetting(
                key=telegram_service.NOTIFICATION_SETTINGS_KEY,
                value_json=f'{{"enabled": true, "min_severity": "{min_severity}"}}',
            )
        )
        db.commit()
        db.close()

    # --- Link token issuance ---

    def test_link_token_issuance_sets_token_and_audits(self):
        user = self.create_user(email="link@sakafarma.com")

        response = self.client.post("/api/users/me/telegram/link-token", headers=self.auth_headers(user))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(body["token"], body["deep_link"])

        db = self.SessionLocal()
        refreshed = db.query(models.User).filter(models.User.id == user.id).first()
        audit = db.query(models.AuditLog).filter(models.AuditLog.action == "TELEGRAM_LINK_TOKEN_ISSUED").first()
        db.close()
        self.assertEqual(refreshed.telegram_link_token, body["token"])
        self.assertIsNotNone(audit)

    def test_notifications_toggle_requires_linked_telegram(self):
        user = self.create_user(email="notlinked@sakafarma.com")

        response = self.client.patch(
            "/api/users/me/telegram/notifications",
            json={"enabled": True},
            headers=self.auth_headers(user),
        )
        self.assertEqual(response.status_code, 400)

    # --- Admin eligibility ---

    def test_notification_eligibility_requires_admin_and_audits(self):
        technician = self.create_user(email="tech@sakafarma.com", role="technician")
        admin = self.create_user(email="admin@sakafarma.com", role="admin")
        target = self.create_user(email="target@sakafarma.com", role="technician")

        denied = self.client.patch(
            f"/api/admin/notification-eligibility/{target.id}",
            json={"notify_eligible": True},
            headers=self.auth_headers(technician),
        )
        self.assertEqual(denied.status_code, 403)

        granted = self.client.patch(
            f"/api/admin/notification-eligibility/{target.id}",
            json={"notify_eligible": True},
            headers=self.auth_headers(admin),
        )
        self.assertEqual(granted.status_code, 200)
        self.assertTrue(granted.json()["notify_eligible"])

        db = self.SessionLocal()
        audit = db.query(models.AuditLog).filter(
            models.AuditLog.action.like("NOTIFY_ELIGIBILITY_GRANTED%")
        ).first()
        db.close()
        self.assertIsNotNone(audit)

    # --- Global settings ---

    def test_notification_settings_requires_admin_and_persists(self):
        technician = self.create_user(email="tech2@sakafarma.com", role="technician")
        admin = self.create_user(email="admin2@sakafarma.com", role="admin")

        denied = self.client.patch(
            "/api/settings/notifications",
            json={"enabled": True, "min_severity": "warning", "reason": "enable for demo"},
            headers=self.auth_headers(technician),
        )
        self.assertEqual(denied.status_code, 403)

        updated = self.client.patch(
            "/api/settings/notifications",
            json={"enabled": True, "min_severity": "warning", "reason": "enable for demo"},
            headers=self.auth_headers(admin),
        )
        self.assertEqual(updated.status_code, 200)
        self.assertTrue(updated.json()["enabled"])
        self.assertEqual(updated.json()["min_severity"], "warning")

        fetched = self.client.get("/api/settings/notifications", headers=self.auth_headers(admin))
        self.assertEqual(fetched.status_code, 200)
        self.assertTrue(fetched.json()["enabled"])

        db = self.SessionLocal()
        audit = db.query(models.AuditLog).filter(models.AuditLog.action == "NOTIFICATION_SETTINGS_UPDATE").first()
        db.close()
        self.assertIsNotNone(audit)

    # --- Dispatch logic (direct unit tests against telegram_service) ---

    def test_dispatch_skips_when_globally_disabled(self):
        self.create_user(
            email="recipient1@sakafarma.com",
            notify_eligible=True,
            telegram_notifications_enabled=True,
            telegram_chat_id="12345",
        )

        with patch.object(telegram_service, "SessionLocal", self.SessionLocal), patch.object(
            telegram_service, "send_telegram_message", new_callable=AsyncMock
        ) as mock_send:
            telegram_service.dispatch_alert_notifications(
                anomaly_event_id=1, machine_id="PMA Granulator #01", severity="critical", message_text="test"
            )

        mock_send.assert_not_called()
        db = self.SessionLocal()
        self.assertEqual(db.query(models.NotificationLog).count(), 0)
        db.close()

    def test_dispatch_skips_below_severity_threshold(self):
        self._enable_notifications(min_severity="critical")
        self.create_user(
            email="recipient2@sakafarma.com",
            notify_eligible=True,
            telegram_notifications_enabled=True,
            telegram_chat_id="12345",
        )

        with patch.object(telegram_service, "SessionLocal", self.SessionLocal), patch.object(
            telegram_service, "send_telegram_message", new_callable=AsyncMock
        ) as mock_send:
            telegram_service.dispatch_alert_notifications(
                anomaly_event_id=1, machine_id="PMA Granulator #01", severity="warning", message_text="test"
            )

        mock_send.assert_not_called()

    def test_dispatch_skips_users_missing_either_gate(self):
        self._enable_notifications(min_severity="warning")
        self.create_user(email="eligible-not-linked@sakafarma.com", notify_eligible=True)
        self.create_user(
            email="linked-not-eligible@sakafarma.com",
            telegram_notifications_enabled=True,
            telegram_chat_id="67890",
        )

        with patch.object(telegram_service, "SessionLocal", self.SessionLocal), patch.object(
            telegram_service, "send_telegram_message", new_callable=AsyncMock
        ) as mock_send:
            telegram_service.dispatch_alert_notifications(
                anomaly_event_id=1, machine_id="PMA Granulator #01", severity="critical", message_text="test"
            )

        mock_send.assert_not_called()

    def test_dispatch_records_sent_and_failed_notification_logs(self):
        self._enable_notifications(min_severity="warning")
        sent_user = self.create_user(
            email="recipient-ok@sakafarma.com",
            notify_eligible=True,
            telegram_notifications_enabled=True,
            telegram_chat_id="111",
        )
        failed_user = self.create_user(
            email="recipient-fail@sakafarma.com",
            notify_eligible=True,
            telegram_notifications_enabled=True,
            telegram_chat_id="222",
        )

        async def fake_send(chat_id, text):
            if chat_id == "111":
                return True, "msg-1", None
            return False, None, "simulated Telegram API error"

        with patch.object(telegram_service, "SessionLocal", self.SessionLocal), patch.object(
            telegram_service, "send_telegram_message", new_callable=AsyncMock, side_effect=fake_send
        ):
            telegram_service.dispatch_alert_notifications(
                anomaly_event_id=42, machine_id="PMA Granulator #01", severity="critical", message_text="test"
            )

        db = self.SessionLocal()
        logs = {log.user_email: log for log in db.query(models.NotificationLog).all()}
        db.close()

        self.assertEqual(logs[sent_user.email].status, "sent")
        self.assertEqual(logs[sent_user.email].telegram_message_id, "msg-1")
        self.assertEqual(logs[failed_user.email].status, "failed")
        self.assertEqual(logs[failed_user.email].error_detail, "simulated Telegram API error")

    # --- Delivery history endpoint ---

    def test_notification_history_requires_admin_and_returns_logged_rows(self):
        admin = self.create_user(email="admin3@sakafarma.com", role="admin")
        technician = self.create_user(email="tech3@sakafarma.com", role="technician")

        db = self.SessionLocal()
        db.add(
            models.NotificationLog(
                anomaly_event_id=1,
                user_id=technician.id,
                user_email=technician.email,
                channel="telegram",
                status="sent",
                severity="critical",
                machine_id="PMA Granulator #01",
            )
        )
        db.commit()
        db.close()

        denied = self.client.get("/api/notifications/history", headers=self.auth_headers(technician))
        self.assertEqual(denied.status_code, 403)

        allowed = self.client.get("/api/notifications/history", headers=self.auth_headers(admin))
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(len(allowed.json()), 1)
        self.assertEqual(allowed.json()[0]["status"], "sent")


if __name__ == "__main__":
    unittest.main()
