import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import security
from app.database import models
from app.database.database import Base
from app.main import app, get_db
from app.services import daily_summary_service

WIB = timezone(timedelta(hours=7))


class DailyAlertSummaryTests(unittest.TestCase):
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

    def create_user(self, *, email="operator@sakafarma.com", password="Strong1!", role="technician", **extra):
        db = self.SessionLocal()
        user = models.User(
            full_name="SPMS Operator",
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
        token = security.create_access_token({"user_id": user.id, "email": user.email, "role": user.role})
        return {"Authorization": f"Bearer {token}"}

    def seed_anomaly_events(self, target_date_wib: datetime):
        db = self.SessionLocal()
        # Create event 1: 09:15 WIB (Normal)
        t1 = target_date_wib.replace(hour=9, minute=15, second=0).astimezone(timezone.utc)
        e1 = models.AnomalyEvent(
            timestamp=t1,
            machine_id="PMA Granulator #01",
            reconstruction_error=0.021,
            threshold=0.045,
            is_anomaly=False,
            severity="normal",
            threshold_policy="LSTM Autoencoder Reconstruction MAE Threshold",
        )
        # Create event 2: 14:30 WIB (Critical Anomaly)
        t2 = target_date_wib.replace(hour=14, minute=30, second=0).astimezone(timezone.utc)
        e2 = models.AnomalyEvent(
            timestamp=t2,
            machine_id="PMA Granulator #01",
            reconstruction_error=0.089,
            threshold=0.045,
            is_anomaly=True,
            severity="critical",
            threshold_policy="LSTM Autoencoder Reconstruction MAE Threshold",
            acknowledged_at=t2 + timedelta(minutes=10),
            acknowledged_by="engineer@sakafarma.com",
            acknowledgement_note="Inspected impeller bearing vibration",
        )
        # Create event 3: 14:45 WIB (Warning Anomaly)
        t3 = target_date_wib.replace(hour=14, minute=45, second=0).astimezone(timezone.utc)
        e3 = models.AnomalyEvent(
            timestamp=t3,
            machine_id="PMA Granulator #01",
            reconstruction_error=0.052,
            threshold=0.045,
            is_anomaly=True,
            severity="warning",
            threshold_policy="LSTM Autoencoder Reconstruction MAE Threshold",
        )
        db.add_all([e1, e2, e3])
        db.commit()

        # Seed linked ticket for e2
        ticket = models.MaintenanceTicket(
            anomaly_event_id=e2.id,
            machine_id="PMA Granulator #01",
            issue_description="Impeller high vibration alert ticket",
            reported_by="engineer@sakafarma.com",
            status="OPEN",
        )
        db.add(ticket)
        db.commit()
        db.close()

    def test_daily_summary_computation_and_kpis(self):
        user = self.create_user(role="operator")
        headers = self.auth_headers(user)
        now_wib = datetime.now(timezone.utc).astimezone(WIB)
        self.seed_anomaly_events(now_wib)

        date_str = now_wib.strftime("%Y-%m-%d")
        resp = self.client.get(f"/api/alerts/daily-summary?date={date_str}", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["date"], date_str)
        self.assertEqual(data["total_events"], 3)
        self.assertEqual(data["anomaly_count"], 2)
        self.assertEqual(data["critical_count"], 1)
        self.assertEqual(data["warning_count"], 1)
        self.assertEqual(data["normal_count"], 1)
        self.assertEqual(data["acknowledged_count"], 1)
        self.assertEqual(data["unacknowledged_count"], 2)
        self.assertEqual(data["ticket_count"], 1)
        self.assertEqual(data["status"], "critical")
        self.assertEqual(data["status_label"], "CRITICAL")

        # Verify Indonesian AI analysis structure
        ai = data["ai_analysis"]
        self.assertIn("health_verdict", ai)
        self.assertIn("subsystem_motor", ai)
        self.assertIn("subsystem_vibration", ai)
        self.assertIn("subsystem_temperature", ai)
        self.assertIn("recommended_actions", ai)
        self.assertTrue(len(ai["recommended_actions"]) > 0)
        self.assertIn("/api/alerts/daily-summary/report-pdf", data["pdf_report_url"])

    def test_daily_summary_history_timeline(self):
        user = self.create_user(role="technician")
        headers = self.auth_headers(user)
        now_wib = datetime.now(timezone.utc).astimezone(WIB)
        self.seed_anomaly_events(now_wib)

        resp = self.client.get("/api/alerts/daily-summary/history?limit=14", headers=headers)
        self.assertEqual(resp.status_code, 200)
        history = resp.json()
        self.assertEqual(len(history), 14)
        
        today_item = history[0]
        self.assertEqual(today_item["date"], now_wib.strftime("%Y-%m-%d"))
        self.assertEqual(today_item["status"], "critical")
        self.assertEqual(today_item["critical_count"], 1)

    def test_daily_summary_pdf_report_export(self):
        user = self.create_user(role="technician")
        headers = self.auth_headers(user)
        now_wib = datetime.now(timezone.utc).astimezone(WIB)
        self.seed_anomaly_events(now_wib)

        date_str = now_wib.strftime("%Y-%m-%d")
        resp = self.client.get(f"/api/alerts/daily-summary/report-pdf?date={date_str}", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertIn("inline; filename=SPMS_Laporan_Harian", resp.headers["content-disposition"])
        self.assertTrue(len(resp.content) > 1000)
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_admin_daily_summary_schedule_management(self):
        admin = self.create_user(email="admin@sakafarma.com", role="admin")
        tech = self.create_user(email="tech@sakafarma.com", role="technician")

        admin_headers = self.auth_headers(admin)
        tech_headers = self.auth_headers(tech)

        # Non-admin cannot access admin schedule endpoint
        forbidden_resp = self.client.get("/api/admin/daily-summary-schedule", headers=tech_headers)
        self.assertEqual(forbidden_resp.status_code, 403)

        # Admin can view default schedule
        get_resp = self.client.get("/api/admin/daily-summary-schedule", headers=admin_headers)
        self.assertEqual(get_resp.status_code, 200)
        schedule = get_resp.json()
        self.assertEqual(schedule["dispatch_time"], "17:00")
        self.assertEqual(schedule["timezone"], "Asia/Jakarta")

        # Admin updates schedule to 18:30 WIB
        update_payload = {
            "enabled": True,
            "dispatch_time": "18:30",
            "reason": "Shift handover time adjusted to 18:30 WIB",
        }
        put_resp = self.client.put("/api/admin/daily-summary-schedule", json=update_payload, headers=admin_headers)
        self.assertEqual(put_resp.status_code, 200)
        updated = put_resp.json()
        self.assertEqual(updated["dispatch_time"], "18:30")
        self.assertEqual(updated["reason"], "Shift handover time adjusted to 18:30 WIB")

        # Verify invalid time format rejected
        bad_resp = self.client.put(
            "/api/admin/daily-summary-schedule",
            json={"enabled": True, "dispatch_time": "25:99", "reason": "Invalid time"},
            headers=admin_headers,
        )
        self.assertEqual(bad_resp.status_code, 422)

    @patch("app.services.telegram_service.send_telegram_message", new_callable=AsyncMock)
    def test_on_demand_dispatch_endpoint(self, mock_send_telegram):
        mock_send_telegram.return_value = (True, "msg_123", None)

        tech = self.create_user(
            email="lead_tech@sakafarma.com",
            role="technician",
            notify_eligible=True,
            telegram_notifications_enabled=True,
            telegram_chat_id="12345678",
            email_notifications=False,
        )
        headers = self.auth_headers(tech)
        now_wib = datetime.now(timezone.utc).astimezone(WIB)
        self.seed_anomaly_events(now_wib)

        with patch("app.core.config.settings.TELEGRAM_BOT_TOKEN", "mock_bot_token"):
            resp = self.client.post(
                "/api/alerts/daily-summary/dispatch",
                json={"date": now_wib.strftime("%Y-%m-%d")},
                headers=headers,
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["success"])
            self.assertIn("telegram", data["channels"])
            self.assertEqual(data["recipients_count"], 1)


if __name__ == "__main__":
    unittest.main()
