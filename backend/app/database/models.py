from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text
from sqlalchemy.sql import func
from app.database.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="technician")    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    email_notifications = Column(Boolean, default=True)
    reset_otp = Column(String(6), nullable=True)
    reset_otp_expire = Column(DateTime(timezone=True), nullable=True)
    telegram_chat_id = Column(String(64), nullable=True, unique=True, index=True)
    telegram_linked_at = Column(DateTime(timezone=True), nullable=True)
    telegram_link_token = Column(String(64), nullable=True, unique=True, index=True)
    telegram_link_token_expires = Column(DateTime(timezone=True), nullable=True)
    telegram_notifications_enabled = Column(Boolean, default=False)
    notify_eligible = Column(Boolean, default=False)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_email = Column(String(255), nullable=True, index=True)    
    action = Column(String(255), nullable=False)
    status = Column(String(50), nullable=True) 
    ip_address = Column(String(45), nullable=True)
    browser_info = Column(String(500), nullable=True)
    record_hash = Column(String(64), nullable=True, index=True)
    previous_hash = Column(String(64), nullable=True)
    hash_algorithm = Column(String(20), nullable=False, default="SHA-256")
    hash_payload_version = Column(String(20), nullable=False, default="audit-v1")


class TelemetryReading(Base):
    __tablename__ = "telemetry_readings"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    machine_id = Column(String(100), default="PMA Granulator #01", index=True)
    batch_id = Column(String(100), nullable=True)
    process_id = Column(String(100), nullable=True)
    impeller_rpm = Column(Float, nullable=True)
    chopper_rpm = Column(Float, nullable=True)
    impeller_ampere = Column(Float, nullable=True)
    x_axis_rms_velocity = Column(Float, nullable=True)
    z_axis_rms_velocity = Column(Float, nullable=True)
    x_axis_peak_acceleration = Column(Float, nullable=True)
    z_axis_peak_acceleration = Column(Float, nullable=True)
    temperature_c = Column(Float, nullable=True)


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    machine_id = Column(String(100), default="PMA Granulator #01", index=True)
    reconstruction_error = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)
    is_anomaly = Column(Boolean, default=False, index=True)
    severity = Column(String(30), default="normal")
    threshold_policy = Column(String(255), nullable=True)
    threshold_source = Column(String(50), default="artifact_baseline")
    model_version = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String(255), nullable=True)
    acknowledgement_note = Column(Text, nullable=True)
    
class MaintenanceTicket(Base):
    __tablename__ = "maintenance_tickets"

    id = Column(Integer, primary_key=True, index=True)
    anomaly_event_id = Column(Integer, nullable=True, index=True)
    machine_id = Column(String(100), index=True)
    issue_description = Column(Text, nullable=False)
    resolution_note = Column(Text, nullable=True)
    reported_by = Column(String(100), nullable=False)
    status = Column(String(20), default="OPEN", index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value_json = Column(Text, nullable=False)
    reason = Column(Text, nullable=True)
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    anomaly_event_id = Column(Integer, index=True, nullable=False)
    user_id = Column(Integer, index=True, nullable=False)
    user_email = Column(String(255), nullable=False)
    channel = Column(String(20), default="telegram", index=True)
    status = Column(String(20), index=True, nullable=False)
    severity = Column(String(30), nullable=True)
    machine_id = Column(String(100), nullable=True)
    error_detail = Column(Text, nullable=True)
    telegram_message_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
