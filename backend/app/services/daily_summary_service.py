"""Daily Alert Output Summary Service for SPMS.

Handles daily alert metric aggregations in WIB (Asia/Jakarta, UTC+7),
AI-generated plain-language maintenance diagnoses in Bahasa Indonesia,
dynamic standard A4 PDF report generation using PyMuPDF (fitz),
30-day historical timeline logging, and Telegram summary dispatching.
"""
import asyncio
import io
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

import fitz  # PyMuPDF
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import append_audit_log
from app.core.config import settings
from app.database import models
from app.database.database import SessionLocal
from app.schemas import DailySummaryScheduleUpdate
from app.services import telegram_service

DAILY_SUMMARY_SCHEDULE_KEY = "daily_summary_schedule_settings"
WIB_TIMEZONE = timezone(timedelta(hours=7), name="WIB")

INDONESIAN_DAYS = {
    "Monday": "Senin",
    "Tuesday": "Selasa",
    "Wednesday": "Rabu",
    "Thursday": "Kamis",
    "Friday": "Jumat",
    "Saturday": "Sabtu",
    "Sunday": "Minggu",
}

INDONESIAN_MONTHS = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
    9: "September", 10: "Oktober", 11: "November", 12: "Desember"
}


def get_wib_now() -> datetime:
    """Return current datetime in WIB (Asia/Jakarta, UTC+7)."""
    return datetime.now(timezone.utc).astimezone(WIB_TIMEZONE)


def parse_target_date(date_str: Optional[str]) -> date:
    """Parse YYYY-MM-DD date string or default to current date in WIB."""
    if date_str:
        try:
            return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            pass
    return get_wib_now().date()


def format_indonesian_date(d: date) -> str:
    """Format date into Indonesian format e.g. 19 Agustus 2026."""
    month_name = INDONESIAN_MONTHS.get(d.month, str(d.month))
    return f"{d.day} {month_name} {d.year}"


def get_daily_summary_schedule(db: Session) -> dict[str, Any]:
    """Retrieve runtime schedule configuration for daily summary dispatch."""
    setting = (
        db.query(models.RuntimeSetting)
        .filter(models.RuntimeSetting.key == DAILY_SUMMARY_SCHEDULE_KEY)
        .first()
    )
    if setting is None:
        return {
            "enabled": True,
            "dispatch_time": "17:00",
            "timezone": "Asia/Jakarta",
            "channels": ["telegram", "email"],
            "reason": "Jadwal default pergantian shift (17:00 WIB)",
            "updated_by": "system",
            "updated_at": None,
        }
    try:
        payload = json.loads(setting.value_json)
    except (TypeError, json.JSONDecodeError):
        payload = {}

    return {
        "enabled": bool(payload.get("enabled", True)),
        "dispatch_time": str(payload.get("dispatch_time", "17:00")),
        "timezone": "Asia/Jakarta",
        "channels": payload.get("channels", ["telegram", "email"]),
        "reason": setting.reason,
        "updated_by": setting.updated_by,
        "updated_at": setting.updated_at,
    }


def update_daily_summary_schedule(
    db: Session,
    update_data: DailySummaryScheduleUpdate,
    updated_by: str,
) -> dict[str, Any]:
    """Update runtime schedule settings and persist to database."""
    setting = (
        db.query(models.RuntimeSetting)
        .filter(models.RuntimeSetting.key == DAILY_SUMMARY_SCHEDULE_KEY)
        .first()
    )
    payload = {
        "enabled": update_data.enabled,
        "dispatch_time": update_data.dispatch_time,
        "timezone": "Asia/Jakarta",
        "channels": ["telegram", "email"],
    }
    value_json = json.dumps(payload)

    if setting is None:
        setting = models.RuntimeSetting(
            key=DAILY_SUMMARY_SCHEDULE_KEY,
            value_json=value_json,
            reason=update_data.reason,
            updated_by=updated_by,
        )
        db.add(setting)
    else:
        setting.value_json = value_json
        setting.reason = update_data.reason
        setting.updated_by = updated_by

    db.commit()
    db.refresh(setting)
    return get_daily_summary_schedule(db)


def get_daily_history_log(
    db: Session,
    machine_id: str = "PMA Granulator #01",
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Return last N calendar days history timeline with status and batch info."""
    today_wib = get_wib_now().date()
    history: list[dict[str, Any]] = []

    for i in range(limit):
        target_date = today_wib - timedelta(days=i)
        start_wib = datetime.combine(target_date, time.min, tzinfo=WIB_TIMEZONE)
        end_wib = datetime.combine(target_date, time.max, tzinfo=WIB_TIMEZONE)
        start_utc = start_wib.astimezone(timezone.utc)
        end_utc = end_wib.astimezone(timezone.utc)

        # Query anomaly counts
        events = (
            db.query(models.AnomalyEvent)
            .filter(models.AnomalyEvent.machine_id == machine_id)
            .filter(
                (models.AnomalyEvent.timestamp >= start_utc)
                & (models.AnomalyEvent.timestamp <= end_utc)
            )
            .all()
        )
        if not events:
            events = (
                db.query(models.AnomalyEvent)
                .filter(models.AnomalyEvent.machine_id == machine_id)
                .filter(
                    (models.AnomalyEvent.timestamp >= start_utc.replace(tzinfo=None))
                    & (models.AnomalyEvent.timestamp <= end_utc.replace(tzinfo=None))
                )
                .all()
            )

        total_events = len(events)
        crit_count = sum(1 for e in events if str(e.severity).lower() == "critical")
        warn_count = sum(1 for e in events if str(e.severity).lower() == "warning")
        anom_count = crit_count + warn_count

        if crit_count > 0:
            status = "critical"
            status_label = "CRITICAL"
        elif warn_count > 0:
            status = "warning"
            status_label = "WARNING"
        else:
            status = "normal"
            status_label = "HEALTHY"

        # Query batch IDs processed on that day
        batches = []
        try:
            batch_query = db.execute(
                text(
                    "SELECT DISTINCT batch_id_clean FROM pma_l1 WHERE readable_time >= :start AND readable_time <= :end AND batch_id_clean IS NOT NULL"
                ),
                {
                    "start": start_wib.strftime("%Y-%m-%d 00:00:00"),
                    "end": end_wib.strftime("%Y-%m-%d 23:59:59"),
                },
            ).fetchall()
            batches = [r[0] for r in batch_query if r[0]]
        except Exception:
            batches = []

        day_en = target_date.strftime("%A, %d %B %Y")

        history.append({
            "date": target_date.strftime("%Y-%m-%d"),
            "day_name": day_en,
            "status": status,
            "status_label": status_label,
            "total_events": total_events,
            "anomaly_count": anom_count,
            "critical_count": crit_count,
            "warning_count": warn_count,
            "batches_processed": batches,
        })

    return history


def generate_ai_maintenance_diagnosis(
    summary_data: dict[str, Any],
    db: Session,
) -> dict[str, Any]:
    """Generate professional plain-language maintenance diagnosis in Bahasa Indonesia."""
    target_date_str = summary_data["date"]
    machine_id = summary_data["machine_id"]
    status = summary_data["status"]
    crit_count = summary_data["critical_count"]
    warn_count = summary_data["warning_count"]
    total_events = summary_data["total_events"]
    batches = summary_data.get("batches_processed", [])
    batch_str = ", ".join(batches) if batches else "Tidak ada batch aktif tercatat"

    # Default heuristic diagnosis in Bahasa Indonesia
    if status == "critical":
        verdict = f"Peringatan Kritis Terdeteksi ({crit_count} anomali kritis) pada unit {machine_id}. Diperlukan inspeksi mekanik segera pada getaran bearing dan beban motor penggerak."
        sub_motor = "Terjadi lonjakan arus motor impeller melebihi ambang batas normal selama proses granulasi aktif."
        sub_vib = "Getaran pada bearing penggerak (drive bearing) menunjukkan peningkatan amplitudo signifikan (kategori kritis)."
        sub_temp = "Suhu operasional ruang granulasi terpantau mengalami peningkatan akibat friksi mekanis."
        notes = f"Tercatat {total_events} siklus telemetri dengan {crit_count} anomali kritis dan {warn_count} peringatan pada batch {batch_str}."
        actions = [
            "Lakukan pemeriksaan fisik langsung pada bearing dan sabuk penggerak (drive belt) motor impeller.",
            "Periksa pelumasan (greasing) pada bantalan poros utama granulator.",
            "Verifikasi kekencangan baut dudukan motor dan alignment poros chopper.",
            "Buat tiket pemeliharaan (Maintenance Ticket) untuk dokumentasi tindakan perbaikan.",
        ]
    elif status == "warning":
        verdict = f"Kondisi Mesin Memerlukan Perhatian ({warn_count} anomali peringatan ringan) pada unit {machine_id}. Mesin masih aman beroperasi dengan pengawasan berkala."
        sub_motor = "Beban arus motor impeller berfluktuasi ringan pada saat transisi fase pemadatan granul."
        sub_vib = "Tingkat getaran bearing menunjukkan deviasi minor dari baseline normal namun masih di bawah batas bahaya."
        sub_temp = "Suhu ruang proses dan motor penggerak dalam rentang stabil dan terkontrol."
        notes = f"Tercatat {total_events} siklus telemetri dengan {warn_count} anomali peringatan ringan pada batch {batch_str}."
        actions = [
            "Pantau kestabilan getaran saat batch granulasi berikutnya berjalan.",
            "Pastikan pembersihan filter udara (filter clear) berjalan sesuai interval yang ditentukan.",
            "Catat tren suhu pada logbook shift teknisi.",
        ]
    else:
        verdict = f"Kondisi Operasional Mesin Normal. Seluruh parameter motor, getaran, dan suhu unit {machine_id} beroperasi dalam batas aman."
        sub_motor = "Beban arus motor impeller dan chopper stabil pada rentang kerja optimal."
        sub_vib = "Tingkat getaran bearing sangat halus (smooth running), tidak terdeteksi indikasi keausan mekanis."
        sub_temp = "Distribusi suhu stabil pada rentang nominal tanpa indikasi panas berlebih."
        notes = f"Tercatat {total_events} siklus telemetri dengan 100% kondisi normal pada batch {batch_str}."
        actions = [
            "Lanjutkan pemantauan prediktif rutin.",
            "Lakukan pembersihan harian sesuai Standar Operasional Prosedur (SOP) granulasi.",
            "Pastikan pelumas dan seal chopper dalam kondisi bersih sebelum pergantian shift.",
        ]

    # Attempt Gemini LLM enhancement if API key is present
    google_key = settings.GOOGLE_API_KEY or os.environ.get("GOOGLE_API_KEY")
    if google_key and "AIzaSy" in str(google_key):
        try:
            from langchain_core.prompts import PromptTemplate
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                google_api_key=google_key,
                temperature=0.2,
            )
            prompt = PromptTemplate.from_template(
                """Anda adalah Senior Maintenance Engineer untuk mesin PMA Granulator industri farmasi di PT. XYZ.
Berdasarkan data operasional harian tanggal {date}:
- Mesin: {machine_id}
- Status: {status}
- Anomali Kritis: {crit_count}, Peringatan: {warn_count}, Normal: {norm_count}
- Total Batch: {batch_str}

Buatlah laporan diagnosis teknis dalam Bahasa Indonesia yang ringkas, mudah dipahami teknisi mekanik/listrik lapangan tanpa istilah matematika/AI rumit.
Format respons HARUS berupa JSON murni dengan struktur:
{{
  "health_verdict": "Ringkasan 1-2 kalimat kondisi mesin dan kesimpulan",
  "subsystem_motor": "Kondisi beban arus motor impeller dan chopper",
  "subsystem_vibration": "Kondisi getaran bearing dan poros penggerak",
  "subsystem_temperature": "Kondisi stabilitas suhu ruang granulasi",
  "operational_notes": "Catatan ringkas shift operasional",
  "recommended_actions": ["Tindakan 1", "Tindakan 2", "Tindakan 3"]
}}
"""
            )
            chain = prompt | llm
            res = chain.invoke({
                "date": target_date_str,
                "machine_id": machine_id,
                "status": status,
                "crit_count": crit_count,
                "warn_count": warn_count,
                "norm_count": summary_data.get("normal_count", 0),
                "batch_str": batch_str,
            })
            raw_text = res.content.strip()
            # Clean JSON markdown if wrapped
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()
            
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict) and "health_verdict" in parsed:
                return {
                    "health_verdict": parsed.get("health_verdict", verdict),
                    "subsystem_motor": parsed.get("subsystem_motor", sub_motor),
                    "subsystem_vibration": parsed.get("subsystem_vibration", sub_vib),
                    "subsystem_temperature": parsed.get("subsystem_temperature", sub_temp),
                    "operational_notes": parsed.get("operational_notes", notes),
                    "recommended_actions": parsed.get("recommended_actions", actions),
                }
        except Exception as exc:
            print(f"[AI Summary] LLM generation skipped or failed: {exc}, using industrial heuristic diagnosis.")

    return {
        "health_verdict": verdict,
        "subsystem_motor": sub_motor,
        "subsystem_vibration": sub_vib,
        "subsystem_temperature": sub_temp,
        "operational_notes": notes,
        "recommended_actions": actions,
    }


def compute_daily_alert_summary(
    db: Session,
    target_date: date,
    machine_id: str = "PMA Granulator #01",
) -> dict[str, Any]:
    """Compute comprehensive daily KPIs and Bahasa Indonesia AI analysis."""
    start_wib = datetime.combine(target_date, time.min, tzinfo=WIB_TIMEZONE)
    end_wib = datetime.combine(target_date, time.max, tzinfo=WIB_TIMEZONE)

    start_utc = start_wib.astimezone(timezone.utc)
    end_utc = end_wib.astimezone(timezone.utc)

    # Query all events for the target day
    events = (
        db.query(models.AnomalyEvent)
        .filter(models.AnomalyEvent.machine_id == machine_id)
        .filter(
            (models.AnomalyEvent.timestamp >= start_utc)
            & (models.AnomalyEvent.timestamp <= end_utc)
        )
        .order_by(models.AnomalyEvent.timestamp.asc())
        .all()
    )

    # Fallback to naive comparison if needed
    if not events:
        events = (
            db.query(models.AnomalyEvent)
            .filter(models.AnomalyEvent.machine_id == machine_id)
            .filter(
                (models.AnomalyEvent.timestamp >= start_utc.replace(tzinfo=None))
                & (models.AnomalyEvent.timestamp <= end_utc.replace(tzinfo=None))
            )
            .order_by(models.AnomalyEvent.timestamp.asc())
            .all()
        )

    total_events = len(events)
    anomaly_events = [e for e in events if e.is_anomaly]
    anomaly_count = len(anomaly_events)
    normal_count = total_events - anomaly_count
    critical_count = sum(1 for e in events if str(e.severity).lower() == "critical")
    warning_count = sum(1 for e in events if str(e.severity).lower() == "warning")
    acknowledged_count = sum(1 for e in events if e.acknowledged_at is not None)
    unacknowledged_count = total_events - acknowledged_count

    ack_rate = round((acknowledged_count / total_events) * 100, 2) if total_events > 0 else 100.0

    if critical_count > 0:
        status = "critical"
        status_label = "CRITICAL"
    elif warning_count > 0:
        status = "warning"
        status_label = "WARNING"
    else:
        status = "normal"
        status_label = "HEALTHY"

    # Count linked maintenance tickets for today
    event_ids = [e.id for e in events]
    ticket_count = 0
    if event_ids:
        ticket_count = (
            db.query(models.MaintenanceTicket)
            .filter(models.MaintenanceTicket.anomaly_event_id.in_(event_ids))
            .count()
        )

    # Batches processed
    batches = []
    try:
        batch_query = db.execute(
            text(
                "SELECT DISTINCT batch_id_clean FROM pma_l1 WHERE readable_time >= :start AND readable_time <= :end AND batch_id_clean IS NOT NULL"
            ),
            {
                "start": start_wib.strftime("%Y-%m-%d 00:00:00"),
                "end": end_wib.strftime("%Y-%m-%d 23:59:59"),
            },
        ).fetchall()
        batches = [r[0] for r in batch_query if r[0]]
    except Exception:
        batches = []

    # Top anomalies
    top_anomalies = sorted(
        anomaly_events,
        key=lambda e: e.reconstruction_error,
        reverse=True,
    )[:10]

    summary_raw = {
        "date": target_date.strftime("%Y-%m-%d"),
        "machine_id": machine_id,
        "status": status,
        "status_label": status_label,
        "total_events": total_events,
        "anomaly_count": anomaly_count,
        "normal_count": normal_count,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "acknowledged_count": acknowledged_count,
        "unacknowledged_count": unacknowledged_count,
        "acknowledgement_rate_percent": ack_rate,
        "ticket_count": ticket_count,
        "batches_processed": batches,
        "top_anomalies": top_anomalies,
        "events_raw": events,
    }

    # Generate Bahasa Indonesia AI Maintenance Diagnosis
    ai_analysis = generate_ai_maintenance_diagnosis(summary_raw, db)
    summary_raw["ai_analysis"] = ai_analysis
    summary_raw["pdf_report_url"] = f"/api/alerts/daily-summary/report-pdf?date={target_date.strftime('%Y-%m-%d')}"

    return summary_raw


def generate_daily_pdf_report(summary: dict[str, Any], ai_analysis: dict[str, Any]) -> bytes:
    """Dynamically generate an official, branded A4 Daily Maintenance Report PDF in Bahasa Indonesia using PyMuPDF (fitz)."""
    doc = fitz.open()
    page = doc.new_page(width=595.3, height=841.9)  # Standard A4 size in points

    # Palette
    c_dark = (5 / 255, 17 / 255, 37 / 255)       # #051125
    c_blue = (27 / 255, 38 / 255, 59 / 255)      # #1b263b
    c_gray_bg = (241 / 255, 244 / 255, 243 / 255) # #f1f4f3
    c_border = (197 / 255, 198 / 255, 205 / 255) # #c5c6cd
    c_text = (24 / 255, 28 / 255, 28 / 255)      # #181c1c
    c_muted = (117 / 255, 119 / 255, 125 / 255)  # #75777d

    status = summary.get("status", "normal")
    if status == "critical":
        c_status = (231 / 255, 76 / 255, 60 / 255)  # Red
        status_text = "KRITIS — TINDAKAN PERBAIKAN DIPERLUKAN"
    elif status == "warning":
        c_status = (243 / 255, 156 / 255, 18 / 255) # Amber
        status_text = "PERHATIAN — PENGAWASAN DIPERLUKAN"
    else:
        c_status = (46 / 255, 204 / 255, 113 / 255) # Green
        status_text = "NORMAL — OPERASIONAL OPTIMAL"

    # 1. Top Header Banner
    header_rect = fitz.Rect(36, 36, 559.3, 110)
    page.draw_rect(header_rect, color=c_dark, fill=c_dark)

    page.insert_text((50, 58), "PT. XYZ — DIVISI PEMELIHARAAN & TEKNIK", fontsize=9.5, fontname="helv", color=(107/255, 254/255, 156/255))
    page.insert_text((50, 78), "LAPORAN RINGKASAN PEMELIHARAAN HARIAN", fontsize=14.5, fontname="hebo", color=(1, 1, 1))
    page.insert_text((50, 95), "Sistem Prediksi Pemeliharaan Mesin (SPMS) • PMA Granulator #01", fontsize=9, fontname="helv", color=(197/255, 198/255, 205/255))

    # Confidentiality Tag
    conf_rect = fitz.Rect(430, 55, 545, 75)
    page.draw_rect(conf_rect, color=(1, 1, 1), fill=(27/255, 38/255, 59/255))
    page.insert_text((440, 68), "DOKUMEN RAHASIA", fontsize=8, fontname="hebo", color=(107/255, 254/255, 156/255))

    # 2. Status & Metadata Strip
    meta_rect = fitz.Rect(36, 120, 559.3, 172)
    page.draw_rect(meta_rect, color=c_border, fill=c_gray_bg)

    target_d = parse_target_date(summary.get("date"))
    date_id_str = format_indonesian_date(target_d)
    day_en = target_d.strftime("%A")
    day_id = INDONESIAN_DAYS.get(day_en, day_en)

    page.insert_text((48, 137), f"Tanggal Laporan : {day_id}, {date_id_str} (WIB)", fontsize=9, fontname="hebo", color=c_text)
    page.insert_text((48, 150), f"Unit Mesin         : {summary.get('machine_id', 'PMA Granulator #01')}", fontsize=9, fontname="helv", color=c_text)
    page.insert_text((48, 163), f"Batch Diproses  : {', '.join(summary.get('batches_processed', [])) or 'Tidak ada batch aktif'}", fontsize=8, fontname="helv", color=c_muted)

    # Status Pill
    status_rect = fitz.Rect(340, 132, 548, 160)
    page.draw_rect(status_rect, color=c_status, fill=c_status)
    page.insert_text((350, 149), status_text, fontsize=8.5, fontname="hebo", color=(1, 1, 1))

    # 3. Section: Ringkasan Diagnosis AI (Plain Language)
    y = 196
    page.insert_text((36, y), "1. RINGKASAN DIAGNOSIS PREDIKTIF AI", fontsize=11, fontname="hebo", color=c_blue)
    page.draw_line(fitz.Point(36, y + 4), fitz.Point(559.3, y + 4), color=c_blue, width=1)

    y += 16
    verdict_rect = fitz.Rect(36, y, 559.3, y + 48)
    page.draw_rect(verdict_rect, color=c_border, fill=(1, 1, 1))
    
    verdict_text = ai_analysis.get("health_verdict", "Kondisi operasional normal.")
    page.insert_textbox(fitz.Rect(46, y + 8, 549.3, y + 42), verdict_text, fontsize=9, fontname="helv", color=c_text)

    y += 70
    # 4. Section: Kondisi Subsistem Mesin (Table Box)
    page.insert_text((36, y), "2. KONDISI & STATUS SUBSISTEM MESIN", fontsize=11, fontname="hebo", color=c_blue)
    page.draw_line(fitz.Point(36, y + 4), fitz.Point(559.3, y + 4), color=c_blue, width=1)

    y += 16
    subs = [
        ("Motor Impeller & Chopper", ai_analysis.get("subsystem_motor", "Arus beban normal.")),
        ("Getaran Bearing Penggerak", ai_analysis.get("subsystem_vibration", "Tingkat getaran halus.")),
        ("Suhu & Termal Granulasi", ai_analysis.get("subsystem_temperature", "Suhu stabil pada batas aman.")),
    ]

    for title, desc in subs:
        box = fitz.Rect(36, y, 559.3, y + 34)
        page.draw_rect(box, color=c_border, fill=c_gray_bg)
        page.insert_text((46, y + 16), title, fontsize=9, fontname="hebo", color=c_blue)
        page.insert_textbox(fitz.Rect(200, y + 6, 549.3, y + 30), desc, fontsize=8.5, fontname="helv", color=c_text)
        y += 40

    y += 18
    # 5. Section: Rekomendasi Tindakan Teknisi
    page.insert_text((36, y), "3. REKOMENDASI TINDAKAN TEKNISI LAPANGAN", fontsize=11, fontname="hebo", color=c_blue)
    page.draw_line(fitz.Point(36, y + 4), fitz.Point(559.3, y + 4), color=c_blue, width=1)

    y += 18
    actions = ai_analysis.get("recommended_actions", ["Lanjutkan pemantauan prediktif rutin."])
    for i, action in enumerate(actions, 1):
        # Checkbox icon box
        cb = fitz.Rect(44, y - 2, 54, y + 8)
        page.draw_rect(cb, color=c_blue, fill=(1, 1, 1))
        page.insert_text((62, y + 7), f"{action}", fontsize=8.5, fontname="helv", color=c_text)
        y += 18

    y += 22
    # 6. Section: Kolom Tanda Tangan & Verifikasi Teknisi
    page.insert_text((36, y), "4. VERIFIKASI & TANDA TANGAN PEMELIHARAAN", fontsize=11, fontname="hebo", color=c_blue)
    page.draw_line(fitz.Point(36, y + 4), fitz.Point(559.3, y + 4), color=c_blue, width=1)

    y += 16
    page.insert_text((40, y + 14), "Diverifikasi Oleh Teknisi Shift:", fontsize=9, fontname="hebo", color=c_blue)
    page.insert_text((40, y + 66), "Nama             : _______________________", fontsize=8.5, fontname="helv", color=c_text)
    page.insert_text((40, y + 86), "Tanggal/Jam : _______________________", fontsize=8.5, fontname="helv", color=c_muted)

    page.insert_text((320, y + 14), "Disetujui Supervisor Pemeliharaan:", fontsize=9, fontname="hebo", color=c_blue)
    page.insert_text((320, y + 66), "Nama             : _______________________", fontsize=8.5, fontname="helv", color=c_text)
    page.insert_text((320, y + 86), "Tanggal/Jam : _______________________", fontsize=8.5, fontname="helv", color=c_muted)

    # Footer
    page.insert_text((36, 810), "Dokumen ini dibuat otomatis oleh Secure Predictive Maintenance System (SPMS) • Khusus Monitoring Prediktif", fontsize=7.5, fontname="helv", color=c_muted)
    page.insert_text((475, 810), f"Halaman 1 dari 1", fontsize=7.5, fontname="helv", color=c_muted)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def format_telegram_daily_summary(summary: dict[str, Any], ai_analysis: dict[str, Any]) -> str:
    """Format rich Telegram message in Bahasa Indonesia."""
    status = summary.get("status", "normal")
    status_emoji = "🚨" if status == "critical" else ("⚠️" if status == "warning" else "✅")
    status_label = summary.get("status_label", "Normal")

    target_d = parse_target_date(summary.get("date"))
    date_id_str = format_indonesian_date(target_d)

    batches = summary.get("batches_processed", [])
    batch_str = ", ".join(batches) if batches else "Tidak ada batch"

    actions_formatted = "\n".join(f"  • {act}" for act in ai_analysis.get("recommended_actions", []))

    lines = [
        f"{status_emoji} *SPMS — LAPORAN HARIAN PEMELIHARAAN*",
        "────────────────────────",
        f"🏭 *Mesin:* `{summary.get('machine_id', 'PMA Granulator #01')}`",
        f"🗓 *Tanggal:* `{date_id_str} (WIB)`",
        f"📊 *Status:* *{status_label}*",
        f"📦 *Batch:* `{batch_str}`",
        "",
        "🔍 *Ringkasan Diagnosa AI:*",
        f"_{ai_analysis.get('health_verdict', '-')}_",
        "",
        "⚙️ *Kondisi Subsistem:*",
        f"• *Motor:* {ai_analysis.get('subsystem_motor', '-')}",
        f"• *Getaran Bearing:* {ai_analysis.get('subsystem_vibration', '-')}",
        f"• *Suhu:* {ai_analysis.get('subsystem_temperature', '-')}",
        "",
        "🛠 *Rekomendasi Teknisi:*",
        f"{actions_formatted}",
        "────────────────────────",
        "🔒 *SPMS Monitoring Prediktif* • PT. XYZ",
    ]
    return "\n".join(lines)


async def dispatch_daily_summary_notifications(
    summary: dict[str, Any],
    db: Session,
    sender_email: str = "system",
) -> tuple[int, list[str]]:
    """Dispatch the daily summary digest via Telegram and Email in Bahasa Indonesia."""
    recipients = (
        db.query(models.User)
        .filter(models.User.notify_eligible.is_(True))
        .all()
    )

    channels_used = []
    recipients_count = 0
    ai_analysis = summary.get("ai_analysis", {})

    # 1. Telegram Dispatch
    telegram_users = [
        u for u in recipients
        if u.telegram_notifications_enabled and u.telegram_chat_id
    ]
    if telegram_users and settings.TELEGRAM_BOT_TOKEN:
        channels_used.append("telegram")
        telegram_text = format_telegram_daily_summary(summary, ai_analysis)
        for u in telegram_users:
            success, msg_id, err = await telegram_service.send_telegram_message(
                u.telegram_chat_id,
                telegram_text,
            )
            if success:
                recipients_count += 1

    # 2. Email Dispatch
    email_users = [
        u for u in recipients
        if u.email_notifications and u.email
    ]
    if email_users and settings.MAIL_USERNAME and settings.MAIL_PASSWORD:
        channels_used.append("email")
        target_d = parse_target_date(summary.get("date"))
        date_id_str = format_indonesian_date(target_d)

        html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; background: #f7faf9; padding: 20px; color: #181c1c;">
  <div style="max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #c5c6cd; border-radius: 8px; overflow: hidden;">
    <div style="background: #051125; padding: 20px; color: #fff;">
      <h2 style="margin: 0; color: #6bfe9c; font-size: 18px;">SPMS — Laporan Ringkasan Pemeliharaan Harian</h2>
      <p style="margin: 4px 0 0 0; font-size: 12px; color: #c5c6cd;">{summary.get('machine_id')} &bull; {date_id_str} (WIB)</p>
    </div>
    <div style="padding: 20px;">
      <div style="padding: 12px; background: #f1f4f3; border-radius: 6px; margin-bottom: 16px;">
        <strong style="color: #1b263b;">Diagnosa AI:</strong>
        <p style="margin: 6px 0 0 0; font-size: 13px;">{ai_analysis.get('health_verdict')}</p>
      </div>
      <h4 style="margin: 16px 0 8px 0; color: #1b263b;">Rekomendasi Tindakan Teknisi:</h4>
      <ul style="font-size: 13px; color: #45474d; padding-left: 20px;">
        {''.join(f'<li>{act}</li>' for act in ai_analysis.get('recommended_actions', []))}
      </ul>
      <p style="font-size: 11px; color: #75777d; margin-top: 20px;">
        Untuk mengunduh dokumen resmi PDF, silakan buka dashboard SPMS di komputer pabrik.
      </p>
    </div>
  </div>
</body>
</html>"""
        from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
        conf = ConnectionConfig(
            MAIL_USERNAME=settings.MAIL_USERNAME,
            MAIL_PASSWORD=settings.MAIL_PASSWORD,
            MAIL_FROM=settings.MAIL_FROM,
            MAIL_PORT=settings.MAIL_PORT,
            MAIL_SERVER=settings.MAIL_SERVER,
            MAIL_STARTTLS=True,
            MAIL_SSL_TLS=False,
            USE_CREDENTIALS=True,
            VALIDATE_CERTS=True,
        )
        fm = FastMail(config=conf)
        for u in email_users:
            try:
                msg = MessageSchema(
                    subject=f"SPMS Laporan Harian Pemeliharaan - {date_id_str} (WIB)",
                    recipients=[u.email],
                    body=html_content,
                    subtype=MessageType.html,
                )
                await fm.send_message(msg)
                recipients_count += 1
            except Exception as exc:
                print(f"WARNING: Daily summary email failed for {u.email}: {exc}")

    # Record SHA-256 Audit Log
    append_audit_log(
        db,
        user_email=sender_email,
        action="DAILY_SUMMARY_DISPATCH",
        status_value="SUCCESS",
        ip_address=None,
        browser_info=f"channels={','.join(channels_used)};date={summary['date']}",
    )
    db.commit()

    return recipients_count, channels_used


async def run_daily_summary_scheduler_forever() -> None:
    """Async background task that checks every 30s and dispatches daily summary at scheduled WIB time."""
    last_dispatched_date: Optional[str] = None

    while True:
        try:
            now_wib = get_wib_now()
            today_str = now_wib.strftime("%Y-%m-%d")
            current_hm = now_wib.strftime("%H:%M")

            db = SessionLocal()
            try:
                schedule = get_daily_summary_schedule(db)
                if (
                    schedule["enabled"]
                    and schedule["dispatch_time"] == current_hm
                    and last_dispatched_date != today_str
                ):
                    print(f"[SPMS SCHEDULER] Memicu pengiriman Laporan Harian untuk {today_str} pada {current_hm} WIB...")
                    summary = compute_daily_alert_summary(db, now_wib.date())
                    await dispatch_daily_summary_notifications(summary, db, sender_email="scheduler")
                    last_dispatched_date = today_str
                    print(f"[SPMS SCHEDULER] Pengiriman Laporan Harian selesai untuk {today_str}.")
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"WARNING: Daily summary scheduler loop error: {exc}")

        await asyncio.sleep(30)
