from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, EmailStr
from typing import Optional

class RequestOTP(BaseModel):
    email: str

class UserCreateWithOTP(BaseModel):
    full_name: str
    email: str
    password: str = Field(max_length=72)
    otp: str
    
class UserUpdate(BaseModel):
    role: str
    is_active: bool
    
class UserResponse(BaseModel): # <--- This must match exactly
    id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    email_notifications: bool
    created_at: datetime | None = None

class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class ResetPassword(BaseModel):
    email: str
    otp: str
    new_password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class UserPreferencesUpdate(BaseModel):
    email_notifications: bool

    class Config:
        from_attributes = True


class TelemetryReadingCreate(BaseModel):
    timestamp: datetime | None = None
    machine_id: str = "PMA Granulator #01"
    batch_id: str | None = None
    process_id: str | None = None
    impeller_rpm: float | None = None
    chopper_rpm: float | None = None
    impeller_ampere: float | None = None
    x_axis_rms_velocity: float | None = None
    z_axis_rms_velocity: float | None = None
    x_axis_peak_acceleration: float | None = None
    z_axis_peak_acceleration: float | None = None
    temperature_c: float | None = None


class TelemetryReadingResponse(TelemetryReadingCreate):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True


class AnomalyPredictionRequest(BaseModel):
    machine_id: str = "PMA Granulator #01"
    window: list[TelemetryReadingCreate] = Field(..., min_length=15, max_length=15)


class AnomalyPredictionResponse(BaseModel):
    machine_id: str
    reconstruction_error: float
    threshold: float
    is_anomaly: bool
    severity: str
    threshold_policy: str
    threshold_source: str = "artifact_baseline"
    window_size: int
    features: list[str]
    model_version: str
    limitations: list[str]
    window_start: datetime | None = None
    window_end: datetime | None = None
    source: str | None = None


class AlertResponse(BaseModel):
    id: int
    timestamp: datetime
    machine_id: str
    reconstruction_error: float
    threshold: float
    is_anomaly: bool
    severity: str
    threshold_policy: str | None = None
    threshold_source: str | None = None
    model_version: str | None = None
    details: str | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    acknowledgement_note: str | None = None

    class Config:
        from_attributes = True


class AlertAcknowledgeRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class DashboardSummary(BaseModel):
    machine_id: str
    status: str
    latest_reading: TelemetryReadingResponse | None
    latest_prediction: AlertResponse | None
    threshold: float | None
    threshold_policy: str
    threshold_source: str
    artifact_threshold: float | None = None
    valid_window_count: int | None
    skipped_window_count: int | None
    artifact_status: dict[str, Any]
    recent_alerts: list[AlertResponse]

class MaintenanceTicketCreate(BaseModel):
    machine_id: str
    issue_description: str
    anomaly_event_id: int | None = None

class MaintenanceTicketResponse(BaseModel):
    id: int
    anomaly_event_id: int | None = None
    machine_id: str
    issue_description: str
    resolution_note: str | None = None
    reported_by: str
    timestamp: datetime
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
    status: str

    class Config:
        from_attributes = True


class MaintenanceTicketStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(OPEN|IN_REVIEW|RESOLVED)$")
    resolution_note: str | None = None


class ThresholdSettingResponse(BaseModel):
    threshold: float
    threshold_policy: str
    threshold_source: str
    artifact_threshold: float | None = None
    override_active: bool
    reason: str | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None


class ThresholdSettingUpdate(BaseModel):
    threshold: float = Field(..., gt=0)
    reason: str = Field(..., min_length=3, max_length=1000)


class SystemStatusResponse(BaseModel):
    checked_at: datetime
    database: dict[str, Any]
    ml_artifacts: dict[str, Any]
    threshold: ThresholdSettingResponse
    audit_chain: dict[str, Any]
    telemetry_source: dict[str, Any]


class TelegramLinkTokenResponse(BaseModel):
    token: str
    deep_link: str
    expires_at: datetime


class TelegramStatusResponse(BaseModel):
    linked: bool
    linked_at: datetime | None = None
    notifications_enabled: bool


class TelegramNotificationToggle(BaseModel):
    enabled: bool


class UserNotificationEligibility(BaseModel):
    id: int
    full_name: str
    email: str
    role: str
    notify_eligible: bool
    telegram_linked: bool
    telegram_notifications_enabled: bool


class NotificationEligibilityUpdate(BaseModel):
    notify_eligible: bool


class NotificationSettingResponse(BaseModel):
    enabled: bool
    min_severity: str
    reason: str | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None


class NotificationSettingUpdate(BaseModel):
    enabled: bool
    min_severity: str = Field(..., pattern="^(warning|critical)$")
    reason: str = Field(..., min_length=3, max_length=1000)


class NotificationLogResponse(BaseModel):
    id: int
    anomaly_event_id: int
    user_id: int
    user_email: str
    channel: str
    status: str
    severity: str | None = None
    machine_id: str | None = None
    error_detail: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class DailyHistoryItem(BaseModel):
    date: str
    day_name: str
    status: str
    status_label: str
    total_events: int
    anomaly_count: int
    critical_count: int
    warning_count: int
    batches_processed: list[str]


class DailySummaryAIAnalysis(BaseModel):
    health_verdict: str
    subsystem_motor: str
    subsystem_vibration: str
    subsystem_temperature: str
    operational_notes: str
    recommended_actions: list[str]


class DailyAlertSummaryResponse(BaseModel):
    date: str
    machine_id: str
    status: str
    status_label: str
    total_events: int
    anomaly_count: int
    normal_count: int
    critical_count: int
    warning_count: int
    acknowledged_count: int
    unacknowledged_count: int
    acknowledgement_rate_percent: float
    ticket_count: int
    batches_processed: list[str]
    ai_analysis: DailySummaryAIAnalysis
    top_anomalies: list[AlertResponse]
    pdf_report_url: str


class DailySummaryScheduleResponse(BaseModel):
    enabled: bool
    dispatch_time: str = "17:00"
    timezone: str = "Asia/Jakarta"
    channels: list[str] = ["telegram", "email"]
    reason: str | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None


class DailySummaryScheduleUpdate(BaseModel):
    enabled: bool
    dispatch_time: str = Field(..., pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    reason: str = Field(..., min_length=3, max_length=1000)


class DailySummaryDispatchRequest(BaseModel):
    date: str | None = None


class DailySummaryDispatchResponse(BaseModel):
    success: bool
    recipients_count: int
    channels: list[str]
    summary_date: str
    message: str
