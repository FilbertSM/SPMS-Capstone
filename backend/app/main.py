import re
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import os
import shutil

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

# --- USER IMPORTS RESTORED ---
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType

from app import schemas
from app.core import security
from app.core.config import settings
from app.core.security import ALGORITHM
from app.database import models
from app.database.database import SessionLocal, engine
from app.ml_integration.inference_service import inference_service
from app.ml_integration.window_builder import (
    WindowSourceUnavailable,
    WindowValidationError,
    build_latest_valid_pma_l1_window,
    fetch_latest_pma_l1_rows,
    validate_prediction_window,
)
import random
from datetime import timedelta

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.core.rag_engine.rag_engine import run_ingestion_pipeline, SPMSChatEngine

_global_chat_engine = None

def get_chat_engine():
    global _global_chat_engine
    if _global_chat_engine is not None:
        return _global_chat_engine
    print("Waking up AI models and loading into RAM for the first time...")
    from app.core.rag_engine.rag_engine import SPMSChatEngine # Safe local import
    _global_chat_engine = SPMSChatEngine()
    return _global_chat_engine

# --- INISIALISATION LIMITER ---
limiter = Limiter(key_func=get_remote_address)

# --- CONFIGURATION EMAIL ---
conf = ConnectionConfig(
    MAIL_USERNAME = settings.MAIL_USERNAME,
    MAIL_PASSWORD = settings.MAIL_PASSWORD,
    MAIL_FROM = settings.MAIL_FROM,
    MAIL_PORT = settings.MAIL_PORT,
    MAIL_SERVER = settings.MAIL_SERVER,
    MAIL_STARTTLS = True,
    MAIL_SSL_TLS = False,
    USE_CREDENTIALS = True,
    VALIDATE_CERTS = True
)


AUDIT_HASH_ALGORITHM = "SHA-256"
AUDIT_HASH_PAYLOAD_VERSION = "audit-v1"
THRESHOLD_OVERRIDE_KEY = "anomaly_threshold_override"
VALID_TICKET_STATUSES = {"OPEN", "IN_REVIEW", "RESOLVED"}


def _format_audit_timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _canonical_audit_payload(log: models.AuditLog) -> str:
    payload = {
        "id": log.id,
        "timestamp": _format_audit_timestamp(log.timestamp),
        "user_email": log.user_email or "",
        "action": log.action or "",
        "status": log.status or "",
        "ip_address": log.ip_address or "",
        "browser_info": log.browser_info or "",
        "previous_hash": log.previous_hash or "",
        "hash_algorithm": log.hash_algorithm or AUDIT_HASH_ALGORITHM,
        "hash_payload_version": log.hash_payload_version or AUDIT_HASH_PAYLOAD_VERSION,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _calculate_audit_hash(log: models.AuditLog) -> str:
    return hashlib.sha256(_canonical_audit_payload(log).encode("utf-8")).hexdigest()


def _append_audit_log(
    db: Session,
    *,
    user_email: str | None,
    action: str,
    status_value: str,
    ip_address: str | None,
    browser_info: str | None,
) -> models.AuditLog:
    previous = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.record_hash.isnot(None))
        .order_by(models.AuditLog.id.desc())
        .with_for_update() 
        .first()
    )
    
    # Membuang microsecond agar sinkron dengan format default MariaDB
    current_time = datetime.now(timezone.utc).replace(microsecond=0)

    log = models.AuditLog(
        timestamp=current_time,
        user_email=user_email,
        action=action,
        status=status_value,  
        ip_address=ip_address,
        browser_info=browser_info,
        previous_hash=previous.record_hash if previous else None,
        hash_algorithm=AUDIT_HASH_ALGORITHM,
        hash_payload_version=AUDIT_HASH_PAYLOAD_VERSION,
    )
    db.add(log)
    db.flush()
    log.record_hash = _calculate_audit_hash(log)
    return log


def _audit_context(request: Request) -> tuple[str, str]:
    client_ip = request.client.host if request.client else "Unknown"
    user_agent = request.headers.get("user-agent", "Unknown")
    return client_ip, user_agent


def _password_policy_error(password: str) -> str | None:
    has_uppercase = re.search(r"[A-Z]", password)
    has_number = re.search(r"[0-9]", password)
    has_symbol = re.search(r"[^A-Za-z0-9]", password)
    if len(password) < 8 or len(password) > 20 or not has_uppercase or not has_number or not has_symbol:
        return "Password must be at least 8 characters long and contain uppercase letters, numbers, and symbols."
    return None


def _verify_audit_hash_chain(db: Session) -> dict:
    logs = db.query(models.AuditLog).order_by(models.AuditLog.id.asc()).all()
    invalid_ids: list[int] = []
    valid_count = 0
    previous_hash = None
    chain_head_hash = None

    for log in logs:
        expected_hash = _calculate_audit_hash(log)
        if (
            not log.record_hash
            or log.previous_hash != previous_hash
            or log.hash_algorithm != AUDIT_HASH_ALGORITHM
            or log.hash_payload_version != AUDIT_HASH_PAYLOAD_VERSION
            or log.record_hash != expected_hash
        ):
            invalid_ids.append(log.id)
        else:
            valid_count += 1
        previous_hash = log.record_hash
        chain_head_hash = log.record_hash

    return {
        "total_logs_checked": len(logs),
        "valid_count": valid_count,
        "invalid_log_ids": invalid_ids,
        "chain_head_hash": chain_head_hash,
        "overall_status": "VERIFIED" if not invalid_ids else "COMPROMISED",
        "hash_algorithm": AUDIT_HASH_ALGORITHM,
        "hash_payload_version": AUDIT_HASH_PAYLOAD_VERSION,
    }


def _ensure_audit_log_hash_columns() -> None:
    try:
        existing = {column["name"] for column in inspect(engine).get_columns("audit_logs")}
    except SQLAlchemyError as exc:
        print(f"WARNING: audit hash column inspection skipped: {exc}")
        return

    definitions = {
        "record_hash": "VARCHAR(64)",
        "previous_hash": "VARCHAR(64)",
        "hash_algorithm": "VARCHAR(20) DEFAULT 'SHA-256'",
        "hash_payload_version": "VARCHAR(20) DEFAULT 'audit-v1'",
    }
    missing = [name for name in definitions if name not in existing]
    if not missing:
        return

    try:
        with engine.begin() as connection:
            for column_name in missing:
                connection.execute(
                    text(f"ALTER TABLE audit_logs ADD COLUMN {column_name} {definitions[column_name]}")
                )
    except SQLAlchemyError as exc:
        print(f"WARNING: audit hash column migration skipped: {exc}")


def _ensure_form4_workflow_columns() -> None:
    column_sets = {
        "anomaly_events": {
            "threshold_source": "VARCHAR(50) DEFAULT 'artifact_baseline'",
            "acknowledged_at": "DATETIME",
            "acknowledged_by": "VARCHAR(255)",
            "acknowledgement_note": "TEXT",
        },
        "maintenance_tickets": {
            "anomaly_event_id": "INTEGER",
            "resolution_note": "TEXT",
            "updated_at": "DATETIME",
            "resolved_at": "DATETIME",
        },
    }

    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
    except SQLAlchemyError as exc:
        print(f"WARNING: Form 4 workflow column inspection skipped: {exc}")
        return

    try:
        with engine.begin() as connection:
            for table_name, definitions in column_sets.items():
                if table_name not in table_names:
                    continue
                existing = {column["name"] for column in inspector.get_columns(table_name)}
                for column_name, definition in definitions.items():
                    if column_name not in existing:
                        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
    except SQLAlchemyError as exc:
        print(f"WARNING: Form 4 workflow column migration skipped: {exc}")


def _backfill_legacy_audit_hashes() -> None:
    db = SessionLocal()
    try:
        logs = db.query(models.AuditLog).order_by(models.AuditLog.id.asc()).all()
        if not logs or any(log.record_hash for log in logs):
            return

        previous_hash = None
        for log in logs:
            log.hash_algorithm = AUDIT_HASH_ALGORITHM
            log.hash_payload_version = AUDIT_HASH_PAYLOAD_VERSION
            log.previous_hash = previous_hash
            log.record_hash = _calculate_audit_hash(log)
            previous_hash = log.record_hash
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        print(f"WARNING: legacy audit hash backfill skipped: {exc}")
    finally:
        db.close()


def get_application() -> FastAPI:
    try:
        models.Base.metadata.create_all(bind=engine)
        _ensure_audit_log_hash_columns()
        _ensure_form4_workflow_columns()
        _backfill_legacy_audit_hashes()
    except SQLAlchemyError as exc:
        print(f"WARNING: database table initialization skipped: {exc}")

    app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        description="Secure Predictive Maintenance System API",
        version="1.0.0",
    )

    cors_origins = [str(origin).rstrip("/") for origin in settings.BACKEND_CORS_ORIGINS]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


app = get_application()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _record_audit_log(
    db: Session,
    *,
    request: Request,
    user_email: str | None,
    action: str,
    status_value: str,
):
    client_ip, user_agent = _audit_context(request)
    _append_audit_log(
        db,
        user_email=user_email,
        action=action,
        status_value=status_value,
        ip_address=client_ip,
        browser_info=user_agent,
    )
    db.commit()


@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": settings.PROJECT_NAME,
        "message": "SPMS API is ready for telemetry.",
    }


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        token_user_id = payload.get("user_id")
        if token_user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == token_user_id).first()
    if user is None or not user.is_active:
        raise credentials_exception

    return user


def get_current_admin(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Sekarang mengizinkan baik 'admin' maupun 'super_admin'
    if current_user.role.lower() not in ["admin", "super_admin"]:
        client_ip, user_agent = _audit_context(request)
        _append_audit_log(
            db,
            user_email=current_user.email,
            action="UNAUTHORIZED_ACCESS",
            status_value="FAILED",
            ip_address=client_ip,
            browser_info=user_agent,
        )
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Administrative Privileges Required",
        )

    return current_user


# --- PENYIMPANAN SEMENTARA UNTUK OTP REGISTRASI (Tidak masuk Database) ---
pending_registration_otps = {}

@app.post("/api/register/request-otp")
async def request_registration_otp(request: Request, data: schemas.RequestOTP, db: Session = Depends(get_db)):
    normalized_email = data.email.strip().lower()
    client_ip, user_agent = _audit_context(request)

    # 1. Cek Email Terdaftar
    existing_user = db.query(models.User).filter(models.User.email == normalized_email).first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered.")

    # 2. Cek Domain
    allowed_domains = ["kalbeconsumerhealth.co.id", "gmail.com", "president.ac.id", "student.president.ac.id"]
    email_domain = normalized_email.split("@")[-1] if "@" in normalized_email else ""
    if email_domain not in allowed_domains:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Registration is restricted to official company domains only.")

    # --- GENERATE OTP & SIMPAN DI MEMORY ---
    otp_code = str(random.randint(100000, 999999))
    pending_registration_otps[normalized_email] = {
        "otp": otp_code,
        "expires": datetime.utcnow() + timedelta(minutes=15)
    }

    # --- SEND VERIFICATION EMAIL ---
    message = MessageSchema(
        subject="SPMS - Verify Your Registration",
        recipients=[normalized_email],
        body=f"""
        <div style="font-family: Arial, sans-serif; max-width: 500px; padding: 20px; border: 1px solid #e5e7eb; border-radius: 12px; color: #1b263b; text-align: center;">
            <h3 style="font-size: 20px; font-weight: bold; margin-bottom: 8px;">Account Verification</h3>
            <p style="font-size: 14px; color: #45474d; margin-bottom: 24px;">Please use the verification code below to continue your SPMS registration:</p>
            
            <div style="background-color: #f1f4f3; padding: 16px; border-radius: 8px; margin-bottom: 24px;">
                <span style="font-size: 32px; font-weight: black; letter-spacing: 8px; color: #2ecc71;">{otp_code}</span>
            </div>
            
            <p style="font-size: 12px; color: #777; line-height: 1.5;">This code will expire in 15 minutes.</p>
        </div>
        """,
        subtype=MessageType.html,
    )

    try:
        fm = FastMail(config=conf)
        await fm.send_message(message)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to send verification email. Please try again.")

    _append_audit_log(db, user_email=normalized_email, action="OTP_REGISTRATION_SENT", status_value="SUCCESS", ip_address=client_ip, browser_info=user_agent)
    db.commit()

    return {"message": "OTP sent to your email. Please verify to continue registration."}


@app.post("/api/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(request: Request, user_data: schemas.UserCreateWithOTP, db: Session = Depends(get_db)):
    normalized_email = user_data.email.strip().lower()
    client_ip, user_agent = _audit_context(request)

    pending_data = pending_registration_otps.get(normalized_email)
    if not pending_data:
        raise HTTPException(status_code=400, detail="No pending registration found. Please request OTP first.")
    
    if pending_data["otp"] != user_data.otp:
        _append_audit_log(db, user_email=normalized_email, action="USER_REGISTRATION", status_value="FAILED_INVALID_OTP", ip_address=client_ip, browser_info=user_agent)
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid OTP code.")
    
    if datetime.utcnow() > pending_data["expires"]:
        del pending_registration_otps[normalized_email]
        raise HTTPException(status_code=400, detail="OTP code has expired. Please request a new one.")

    existing_user = db.query(models.User).filter(models.User.email == normalized_email).first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    password_error = _password_policy_error(user_data.password)
    if password_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=password_error)

    new_user = models.User(
        full_name=user_data.full_name,
        email=normalized_email,
        hashed_password=security.get_password_hash(user_data.password),
        is_active=True 
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    del pending_registration_otps[normalized_email]

    _record_audit_log(db, request=request, user_email=new_user.email, action="USER_REGISTER", status_value="SUCCESS")
    return new_user

@app.post("/api/login", response_model=schemas.Token)
@limiter.limit("5/minute")
def login(
    request: Request,
    user_credentials: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    normalized_email = user_credentials.username.strip().lower()
    user = db.query(models.User).filter(models.User.email == normalized_email).first()

    client_ip, user_agent = _audit_context(request)

    if not user or not security.verify_password(user_credentials.password, user.hashed_password):
        _append_audit_log(
            db,
            user_email=normalized_email,
            action="USER_LOGIN",
            status_value="FAILED",
            ip_address=client_ip,
            browser_info=user_agent,
        )
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        _append_audit_log(
            db,
            user_email=user.email,
            action="USER_LOGIN",
            status_value="FAILED_INACTIVE",
            ip_address=client_ip,
            browser_info=user_agent,
        )
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    _append_audit_log(
        db,
        user_email=user.email,
        action="USER_LOGIN",
        status_value="SUCCESS",
        ip_address=client_ip,
        browser_info=user_agent,
    )
    db.commit()

    access_token = security.create_access_token(
        data={"user_id": user.id, "role": user.role}
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/api/logout")
def logout(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client_ip, user_agent = _audit_context(request)
    _append_audit_log(
        db,
        user_email=current_user.email,
        action="USER_LOGOUT",
        status_value="SUCCESS",
        ip_address=client_ip,
        browser_info=user_agent,
    )
    db.commit()

    return {"message": "Logged out successfully"}


@app.post("/api/forgot-password")
async def forgot_password(
    request: Request,
    body: schemas.ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    client_ip, user_agent = _audit_context(request)
    normalized_email = body.email.strip().lower()

    user = db.query(models.User).filter(models.User.email == normalized_email).first()

    if user:
        # --- GENERATE 6-DIGIT OTP ---
        otp_code = str(random.randint(100000, 999999))
        
        # Simpan OTP dan waktu kedaluwarsa (15 menit dari sekarang) ke database
        user.reset_otp = otp_code
        user.reset_otp_expire = datetime.utcnow() + timedelta(minutes=15)
        db.commit()

        message = MessageSchema(
            subject="SPMS - Your Password Reset OTP",
            recipients=[user.email],
            body=f"""
            <div style="font-family: Arial, sans-serif; max-width: 500px; padding: 20px; border: 1px solid #e5e7eb; border-radius: 12px; color: #1b263b; text-align: center;">
                <h3 style="font-size: 20px; font-weight: bold; margin-bottom: 8px;">Password Reset Request</h3>
                <p style="font-size: 14px; color: #45474d; margin-bottom: 24px;">You requested a password reset for your SPMS account. Please use the verification code below:</p>
                
                <div style="background-color: #f1f4f3; padding: 16px; border-radius: 8px; margin-bottom: 24px;">
                    <span style="font-size: 32px; font-weight: black; letter-spacing: 8px; color: #2ecc71;">{otp_code}</span>
                </div>
                
                <p style="font-size: 12px; color: #777; line-height: 1.5;">
                    This code will expire in 15 minutes.<br>
                    If you did not request this, please ignore this email and your password will remain unchanged.
                </p>
            </div>
            """,
            subtype=MessageType.html,
        )

        fm = FastMail(config=conf)
        await fm.send_message(message)

        _append_audit_log(
            db,
            user_email=user.email,
            action="OTP_SENT",
            status_value="SUCCESS",
            ip_address=client_ip,
            browser_info=user_agent,
        )
    else:
        _append_audit_log(
            db,
            user_email=normalized_email,
            action="OTP_REQ_FAILED",
            status_value="FAILED",
            ip_address=client_ip,
            browser_info=user_agent,
        )

    db.commit()

    return {"message": "If this email is registered, an OTP code has been sent."}


@app.post("/api/reset-password")
def reset_password(
    request: Request,
    data: schemas.ResetPassword, # Ini otomatis akan membaca email, otp, dan new_password dari schemas.py
    db: Session = Depends(get_db),
):
    client_ip, user_agent = _audit_context(request)
    normalized_email = data.email.strip().lower()

    # Cari user berdasarkan email
    user = db.query(models.User).filter(models.User.email == normalized_email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # --- VALIDASI OTP ---
    if user.reset_otp != data.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP code.")
    
    # --- VALIDASI WAKTU KEDALUWARSA ---
    if user.reset_otp_expire is None or datetime.utcnow() > user.reset_otp_expire:
        raise HTTPException(status_code=400, detail="OTP code has expired. Please request a new one.")

    password_error = _password_policy_error(data.new_password)
    if password_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=password_error)

    # Jika lolos validasi, update password
    user.hashed_password = security.get_password_hash(data.new_password)
    
    # Hapus OTP dari database agar tidak bisa dipakai ulang
    user.reset_otp = None
    user.reset_otp_expire = None
    
    _append_audit_log(
        db,
        user_email=user.email,
        action="PASSWORD_RESET_SUCCESS",
        status_value="SUCCESS",
        ip_address=client_ip,
        browser_info=user_agent,
    )
    db.commit()

    return {"message": "Password updated successfully. You can now login."}


@app.get("/api/audit-logs")
def get_audit_logs(
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return db.query(models.AuditLog).order_by(models.AuditLog.timestamp.desc()).all()


@app.get("/api/audit-logs/verify")
def verify_audit_logs(
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return _verify_audit_hash_chain(db)


@app.get("/api/audit-logs/export")
def export_audit_logs(
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    logs = db.query(models.AuditLog).order_by(models.AuditLog.timestamp.desc()).all()

    stream = io.StringIO()
    csv_writer = csv.writer(stream)
    csv_writer.writerow(
        [
            "ID",
            "Timestamp (UTC)",
            "User Email",
            "Action",
            "Status",
            "IP Address",
            "Browser Info",
            "Record Hash",
            "Previous Hash",
            "Hash Algorithm",
            "Hash Payload Version",
        ]
    )

    for log in logs:
        time_str = log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "N/A"
        csv_writer.writerow(
            [
                log.id,
                time_str,
                log.user_email or "System/Anonymous",
                log.action,
                log.status,
                log.ip_address or "N/A",
                log.browser_info or "N/A",
                log.record_hash or "N/A",
                log.previous_hash or "N/A",
                log.hash_algorithm or "N/A",
                log.hash_payload_version or "N/A",
            ]
        )

    stream.seek(0)
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=security_audit_report.csv"
    return response


@app.get("/api/users/me", response_model=schemas.UserResponse)
def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user

@app.get("/api/users", response_model=list[schemas.UserResponse])
def get_all_users(
    current_user: models.User = Depends(get_current_user), # Just use get_current_user
    db: Session = Depends(get_db),
):
    # ALLOW BOTH ROLES
    allowed_roles = ["admin", "super_admin"]
    if current_user.role.lower() not in allowed_roles:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    return users

@app.patch("/api/users/{user_id}")
def update_user_role(
    user_id: int,
    user_update: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if current_user.role.lower() == "admin" and user_update.role.lower() == "super_admin":
        raise HTTPException(status_code=403, detail="Admins cannot assign Super Admin role.")
    
    # Update data
    user.role = user_update.role
    user.is_active = user_update.is_active
    db.commit()
    return {"message": "User updated successfully"}

@app.delete("/api/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    if current_user.role.lower() != "super_admin":
        _record_audit_log(
            db, request=request, user_email=current_user.email,
            action="UNAUTHORIZED_DELETE_ATTEMPT", status_value="FAILED"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Access Denied: Only Super Admin can deactivate users."
        )

    user_to_deactivate = db.query(models.User).filter(models.User.id == user_id).first()
    if not user_to_deactivate:
        raise HTTPException(status_code=404, detail="User not found")

    if user_to_deactivate.id == current_user.id:
        raise HTTPException(status_code=400, detail="Super Admin cannot deactivate their own account.")

    # SOFT DELETE: Ubah status menjadi non-aktif alih-alih menghapus permanen
    user_to_deactivate.is_active = False
    
    _record_audit_log(
        db, request=request, user_email=current_user.email,
        action=f"USER_SOFT_DELETE: {user_to_deactivate.email}", status_value="SUCCESS"
    )
    db.commit()

    return {"message": "User deactivated successfully."}

@app.patch("/api/users/me/preferences")
def update_user_preferences(
    request: Request,
    preferences: schemas.UserPreferencesUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.email_notifications = preferences.email_notifications

    client_ip, user_agent = _audit_context(request)
    _append_audit_log(
        db,
        user_email=current_user.email,
        action="PREFERENCES_UPDATED",
        status_value="SUCCESS",
        ip_address=client_ip,
        browser_info=user_agent,
    )
    db.commit()

    return {
        "message": "Preferences updated successfully",
        "email_notifications": current_user.email_notifications,
    }

# ==========================================
# --- AUDITED MAINTENANCE TICKET ENDPOINTS ---
# ==========================================

@app.post("/api/tickets", response_model=schemas.MaintenanceTicketResponse, status_code=status.HTTP_201_CREATED)
def create_maintenance_ticket(
    request: Request,
    ticket: schemas.MaintenanceTicketCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if ticket.anomaly_event_id is not None:
        linked_event = db.query(models.AnomalyEvent).filter(models.AnomalyEvent.id == ticket.anomaly_event_id).first()
        if linked_event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Linked anomaly event was not found.")

    new_ticket = models.MaintenanceTicket(
        anomaly_event_id=ticket.anomaly_event_id,
        machine_id=ticket.machine_id,
        issue_description=ticket.issue_description,
        reported_by=current_user.email,
        status="OPEN",
    )
    db.add(new_ticket)

    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="TICKET_CREATE",
        status_value="SUCCESS",
    )

    db.commit()
    db.refresh(new_ticket)
    return new_ticket


@app.get("/api/tickets", response_model=list[schemas.MaintenanceTicketResponse])
def get_maintenance_tickets(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="TICKETS_VIEW",
        status_value="SUCCESS",
    )

    return db.query(models.MaintenanceTicket).order_by(models.MaintenanceTicket.timestamp.desc()).all()


@app.patch("/api/tickets/{ticket_id}/status", response_model=schemas.MaintenanceTicketResponse)
def update_maintenance_ticket_status(
    ticket_id: int,
    request: Request,
    update: schemas.MaintenanceTicketStatusUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ticket = db.query(models.MaintenanceTicket).filter(models.MaintenanceTicket.id == ticket_id).first()
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance ticket was not found.")

    if update.status not in VALID_TICKET_STATUSES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid maintenance ticket status.")
    if update.status == "RESOLVED" and not update.resolution_note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Resolution note is required to resolve a ticket.")

    ticket.status = update.status
    ticket.updated_at = datetime.now(timezone.utc)
    if update.resolution_note is not None:
        ticket.resolution_note = update.resolution_note
    if update.status == "RESOLVED":
        ticket.resolved_at = datetime.now(timezone.utc)
    elif update.status in {"OPEN", "IN_REVIEW"}:
        ticket.resolved_at = None

    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="TICKET_STATUS_UPDATE",
        status_value=update.status,
    )

    db.commit()
    db.refresh(ticket)
    return ticket

# ==========================================
# --- TEAMMATE ML & TELEMETRY ENDPOINTS ---
# ==========================================

@app.get("/api/pma/getPMAData")
def get_pma_telemetry(
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query_str = """
        SELECT
            `time@timestamp` AS timestamp,
            data_format_2 AS impeller_rpm,
            data_format_3 AS filterclear_interval_sec,
            data_format_4 AS processtime_min,
            data_format_5 AS chopper_rpm,
            data_format_6 AS pump_speed,
            data_format_7 AS impeller_ampere
        FROM `cmt-fhdgea1_ebr_pma_data`
        WHERE `time@timestamp` IS NOT NULL
    """

    params = {}

    if start and end:
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            params["start_unix"] = start_dt.timestamp()
            params["end_unix"] = end_dt.timestamp()
            query_str += " AND `time@timestamp` >= :start_unix AND `time@timestamp` <= :end_unix"
        except ValueError:
            pass

    if start and end:
        query_str += " ORDER BY `time@timestamp` ASC"
    else:
        query_str += " ORDER BY `time@timestamp` DESC"

    if limit is not None:
        query_str += " LIMIT :limit"
        params["limit"] = limit
    elif not start and not end:
        query_str += " LIMIT 1000"

    try:
        results = db.execute(text(query_str), params).fetchall()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PMA telemetry source table is not initialized. Reset the local Docker database volume so db_init imports can run.",
        ) from exc

    data = [dict(row._mapping) for row in results]
    if not start and not end:
        return data[::-1]
    return data


@app.get("/api/motor/telemetry")
def get_motor_telemetry(
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query_str = """
        SELECT
            `time@timestamp` AS timestamp,
            (data_format_0 / 100.0) AS x_velocity_mm_s,
            (data_format_2 / 100.0) AS z_velocity_mm_s,
            (data_format_4 / 1000.0) AS x_peak_accel_g,
            (data_format_5 / 1000.0) AS z_peak_accel_g,
            (data_format_6 / 100.0) AS temperature
        FROM `cmt-mtc_motor1.1_data`
        WHERE `time@timestamp` IS NOT NULL
    """
    params = {}

    if start and end:
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            params["start_unix"] = start_dt.timestamp()
            params["end_unix"] = end_dt.timestamp()
            query_str += " AND `time@timestamp` >= :start_unix AND `time@timestamp` <= :end_unix"
            query_str += " ORDER BY `time@timestamp` ASC"
        except ValueError:
            pass
    else:
        query_str += " ORDER BY `time@timestamp` DESC"

    if limit is not None:
        query_str += " LIMIT :limit"
        params["limit"] = limit
    elif not start and not end:
        query_str += " LIMIT 1000"

    try:
        results = db.execute(text(query_str), params).fetchall()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Motor telemetry source table is not initialized. Reset the local Docker database volume so db_init imports can run.",
        ) from exc

    data = [dict(row._mapping) for row in results]
    if not start and not end:
        return data[::-1]
    return data


def _read_threshold_override(db: Session) -> models.RuntimeSetting | None:
    return db.query(models.RuntimeSetting).filter(models.RuntimeSetting.key == THRESHOLD_OVERRIDE_KEY).first()


def _threshold_state(db: Session) -> dict:
    artifact_threshold: float | None = None
    metadata = inference_service.metadata()
    metadata_threshold = metadata.get("threshold")
    if metadata_threshold is not None:
        artifact_threshold = float(metadata_threshold)
    else:
        artifact_threshold = float(inference_service.threshold())

    artifact_policy = metadata.get("threshold_policy", "artifact threshold baseline")
    override = _read_threshold_override(db)
    if override:
        try:
            override_payload = json.loads(override.value_json)
            override_threshold = float(override_payload["threshold"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            override_threshold = None
        if override_threshold and override_threshold > 0:
            reason = override.reason or "No reason recorded"
            return {
                "threshold": override_threshold,
                "threshold_policy": f"Admin runtime override: {reason}",
                "threshold_source": "admin_override",
                "artifact_threshold": artifact_threshold,
                "override_active": True,
                "reason": override.reason,
                "updated_by": override.updated_by,
                "updated_at": override.updated_at,
            }

    return {
        "threshold": artifact_threshold,
        "threshold_policy": artifact_policy,
        "threshold_source": "artifact_baseline",
        "artifact_threshold": artifact_threshold,
        "override_active": False,
        "reason": None,
        "updated_by": None,
        "updated_at": None,
    }


def _apply_effective_threshold(db: Session, prediction: dict) -> dict:
    threshold_state = _threshold_state(db)
    threshold = float(threshold_state["threshold"])
    effective_prediction = dict(prediction)
    effective_prediction["threshold"] = threshold
    effective_prediction["is_anomaly"] = float(prediction["reconstruction_error"]) > threshold
    effective_prediction["threshold_policy"] = threshold_state["threshold_policy"]
    effective_prediction["threshold_source"] = threshold_state["threshold_source"]
    return effective_prediction


def _anomaly_severity(reconstruction_error: float, threshold: float, is_anomaly: bool) -> str:
    if not is_anomaly:
        return "normal"
    if threshold > 0 and reconstruction_error >= threshold * 1.5:
        return "critical"
    return "warning"


def _reading_to_prediction_row(reading: schemas.TelemetryReadingCreate) -> dict:
    return {
        "timestamp": reading.timestamp,
        "machine_id": reading.machine_id,
        "batch_id": reading.batch_id,
        "process_id": reading.process_id,
        "impeller_rpm": reading.impeller_rpm,
        "chopper_rpm": reading.chopper_rpm,
        "impeller_ampere": reading.impeller_ampere,
        "x_axis_rms_velocity": reading.x_axis_rms_velocity,
        "z_axis_rms_velocity": reading.z_axis_rms_velocity,
        "x_axis_peak_acceleration": reading.x_axis_peak_acceleration,
        "z_axis_peak_acceleration": reading.z_axis_peak_acceleration,
        "temperature_c": reading.temperature_c,
    }


def _fallback_latest_telemetry(db: Session, *, machine_id: str, limit: int):
    return (
        db.query(models.TelemetryReading)
        .filter(models.TelemetryReading.machine_id == machine_id)
        .order_by(models.TelemetryReading.timestamp.desc())
        .limit(limit)
        .all()
    )


def _latest_telemetry_rows(db: Session, *, machine_id: str, limit: int):
    try:
        pma_rows = fetch_latest_pma_l1_rows(db, limit=limit, machine_id=machine_id)
    except WindowSourceUnavailable:
        pma_rows = []
    if pma_rows:
        return pma_rows
    return _fallback_latest_telemetry(db, machine_id=machine_id, limit=limit)


def _save_anomaly_event(
    db: Session,
    *,
    machine_id: str,
    prediction: dict,
    source: str,
    window_start: datetime | None,
    window_end: datetime | None,
) -> tuple[models.AnomalyEvent, str]:
    severity = _anomaly_severity(
        prediction["reconstruction_error"],
        prediction["threshold"],
        prediction["is_anomaly"],
    )

    event = models.AnomalyEvent(
        machine_id=machine_id,
        reconstruction_error=prediction["reconstruction_error"],
        threshold=prediction["threshold"],
        is_anomaly=prediction["is_anomaly"],
        severity=severity,
        threshold_policy=prediction["threshold_policy"],
        threshold_source=prediction.get("threshold_source", "artifact_baseline"),
        model_version=prediction["model_version"],
        details=json.dumps(
            {
                "features": prediction["features"],
                "window_size": prediction["window_size"],
                "limitations": prediction["limitations"],
                "source": source,
                "window_start": window_start.isoformat() if window_start else None,
                "window_end": window_end.isoformat() if window_end else None,
                "requested_at": datetime.utcnow().isoformat(),
            }
        ),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event, severity


def _prediction_response(
    *,
    machine_id: str,
    prediction: dict,
    severity: str,
    source: str,
    window_start: datetime | None,
    window_end: datetime | None,
) -> dict:
    return {
        "machine_id": machine_id,
        "reconstruction_error": prediction["reconstruction_error"],
        "threshold": prediction["threshold"],
        "is_anomaly": prediction["is_anomaly"],
        "severity": severity,
        "threshold_policy": prediction["threshold_policy"],
        "threshold_source": prediction.get("threshold_source", "artifact_baseline"),
        "window_size": prediction["window_size"],
        "features": prediction["features"],
        "model_version": prediction["model_version"],
        "limitations": prediction["limitations"],
        "window_start": window_start,
        "window_end": window_end,
        "source": source,
    }


@app.post("/api/telemetry", response_model=schemas.TelemetryReadingResponse, status_code=status.HTTP_201_CREATED)
def create_telemetry_reading(
    reading: schemas.TelemetryReadingCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = reading.model_dump(exclude_none=True)
    if reading.timestamp is None:
        payload.pop("timestamp", None)

    stored = models.TelemetryReading(**payload)
    db.add(stored)
    db.commit()
    db.refresh(stored)
    return stored


@app.get("/api/telemetry/latest", response_model=list[schemas.TelemetryReadingResponse])
def read_latest_telemetry(
    limit: int = 60,
    machine_id: str = "PMA Granulator #01",
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    safe_limit = max(1, min(limit, 500))
    return _latest_telemetry_rows(db, machine_id=machine_id, limit=safe_limit)


@app.get("/api/alerts", response_model=list[schemas.AlertResponse])
def read_alerts(
    request: Request,
    machine_id: str = "PMA Granulator #01",
    severity: str | None = None,
    acknowledgement_status: str | None = None,
    limit: int = 50,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="ALERTS_VIEW",
        status_value="SUCCESS",
    )

    safe_limit = max(1, min(limit, 200))
    query = db.query(models.AnomalyEvent).filter(models.AnomalyEvent.machine_id == machine_id)
    if severity and severity != "all":
        query = query.filter(models.AnomalyEvent.severity == severity)
    if acknowledgement_status == "acknowledged":
        query = query.filter(models.AnomalyEvent.acknowledged_at.isnot(None))
    elif acknowledgement_status == "unacknowledged":
        query = query.filter(models.AnomalyEvent.acknowledged_at.is_(None))
    return query.order_by(models.AnomalyEvent.timestamp.desc()).limit(safe_limit).all()


@app.post("/api/alerts/{alert_id}/acknowledge", response_model=schemas.AlertResponse)
def acknowledge_alert(
    alert_id: int,
    request: Request,
    body: schemas.AlertAcknowledgeRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    alert = db.query(models.AnomalyEvent).filter(models.AnomalyEvent.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert event was not found.")

    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = current_user.email
    alert.acknowledgement_note = body.note

    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="ALERT_ACKNOWLEDGE",
        status_value="SUCCESS",
    )

    db.commit()
    db.refresh(alert)
    return alert


@app.get("/api/alerts/export")
def export_alerts(
    request: Request,
    machine_id: str = "PMA Granulator #01",
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="ALERT_REPORT_EXPORT",
        status_value="SUCCESS",
    )

    alerts = (
        db.query(models.AnomalyEvent)
        .filter(models.AnomalyEvent.machine_id == machine_id)
        .order_by(models.AnomalyEvent.timestamp.desc())
        .all()
    )
    ticket_rows = db.query(models.MaintenanceTicket).all()
    tickets_by_alert: dict[int, list[models.MaintenanceTicket]] = {}
    for ticket in ticket_rows:
        if ticket.anomaly_event_id is not None:
            tickets_by_alert.setdefault(ticket.anomaly_event_id, []).append(ticket)

    stream = io.StringIO()
    csv_writer = csv.writer(stream)
    csv_writer.writerow(
        [
            "Alert ID",
            "Timestamp",
            "Machine ID",
            "Severity",
            "Reconstruction Error",
            "Threshold",
            "Threshold Source",
            "Acknowledged At",
            "Acknowledged By",
            "Acknowledgement Note",
            "Linked Ticket IDs",
            "Linked Ticket Statuses",
        ]
    )
    for alert in alerts:
        linked_tickets = tickets_by_alert.get(alert.id, [])
        csv_writer.writerow(
            [
                alert.id,
                alert.timestamp.isoformat() if alert.timestamp else "",
                alert.machine_id,
                alert.severity,
                alert.reconstruction_error,
                alert.threshold,
                alert.threshold_source,
                alert.acknowledged_at.isoformat() if alert.acknowledged_at else "",
                alert.acknowledged_by or "",
                alert.acknowledgement_note or "",
                ";".join(str(ticket.id) for ticket in linked_tickets),
                ";".join(ticket.status for ticket in linked_tickets),
            ]
        )

    stream.seek(0)
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=spms_alert_report.csv"
    return response


@app.post("/api/predict/anomaly", response_model=schemas.AnomalyPredictionResponse)
def predict_anomaly(
    http_request: Request,
    request: schemas.AnomalyPredictionRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        window = validate_prediction_window(
            [_reading_to_prediction_row(row) for row in request.window],
            expected_window=inference_service.window_size(),
            feature_names=inference_service.feature_names(),
        )
        prediction = _apply_effective_threshold(db, inference_service.predict_window(window))
    except WindowValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ML runtime dependency is missing: {exc}",
        ) from exc

    _, severity = _save_anomaly_event(
        db,
        machine_id=request.machine_id,
        prediction=prediction,
        source="manual",
        window_start=window[0]["timestamp"],
        window_end=window[-1]["timestamp"],
    )
    _record_audit_log(
        db,
        request=http_request,
        user_email=current_user.email,
        action="ANOMALY_PREDICTION_MANUAL",
        status_value="SUCCESS",
    )

    return _prediction_response(
        machine_id=request.machine_id,
        prediction=prediction,
        severity=severity,
        source="manual",
        window_start=window[0]["timestamp"],
        window_end=window[-1]["timestamp"],
    )


@app.post("/api/predict/anomaly/latest", response_model=schemas.AnomalyPredictionResponse)
def predict_latest_anomaly(
    request: Request,
    machine_id: str = "PMA Granulator #01",
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        window_payload = build_latest_valid_pma_l1_window(
            db,
            expected_window=inference_service.window_size(),
            feature_names=inference_service.feature_names(),
            machine_id=machine_id,
        )
        prediction = _apply_effective_threshold(db, inference_service.predict_window(window_payload["rows"]))
    except WindowValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except WindowSourceUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ML runtime dependency is missing: {exc}",
        ) from exc

    _, severity = _save_anomaly_event(
        db,
        machine_id=machine_id,
        prediction=prediction,
        source=window_payload["source"],
        window_start=window_payload["window_start"],
        window_end=window_payload["window_end"],
    )
    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="ANOMALY_PREDICTION_LATEST",
        status_value="SUCCESS",
    )

    return _prediction_response(
        machine_id=machine_id,
        prediction=prediction,
        severity=severity,
        source=window_payload["source"],
        window_start=window_payload["window_start"],
        window_end=window_payload["window_end"],
    )


@app.get("/api/settings/threshold", response_model=schemas.ThresholdSettingResponse)
def read_threshold_setting(
    request: Request,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="THRESHOLD_OVERRIDE_VIEW",
        status_value="SUCCESS",
    )
    return _threshold_state(db)


@app.patch("/api/settings/threshold", response_model=schemas.ThresholdSettingResponse)
def update_threshold_setting(
    request: Request,
    update: schemas.ThresholdSettingUpdate,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    setting = _read_threshold_override(db)
    payload = json.dumps({"threshold": update.threshold}, separators=(",", ":"))
    if setting is None:
        setting = models.RuntimeSetting(key=THRESHOLD_OVERRIDE_KEY, value_json=payload)
        db.add(setting)
    else:
        setting.value_json = payload
    setting.reason = update.reason
    setting.updated_by = current_user.email
    setting.updated_at = datetime.now(timezone.utc)

    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="THRESHOLD_OVERRIDE_UPDATE",
        status_value="SUCCESS",
    )

    db.commit()
    return _threshold_state(db)


@app.delete("/api/settings/threshold", response_model=schemas.ThresholdSettingResponse)
def reset_threshold_setting(
    request: Request,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    setting = _read_threshold_override(db)
    if setting is not None:
        db.delete(setting)

    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="THRESHOLD_OVERRIDE_RESET",
        status_value="SUCCESS",
    )

    db.commit()
    return _threshold_state(db)


@app.get("/api/system/status", response_model=schemas.SystemStatusResponse)
def read_system_status(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    database_status = {"connected": False, "detail": "Unavailable"}
    try:
        db.execute(text("SELECT 1"))
        database_status = {"connected": True, "detail": "SELECT 1 succeeded"}
    except SQLAlchemyError as exc:
        database_status = {"connected": False, "detail": str(exc)}

    telemetry_status = {"available": False, "source": None, "detail": "No telemetry rows returned"}
    try:
        rows = _latest_telemetry_rows(db, machine_id="PMA Granulator #01", limit=1)
        if rows:
            telemetry_status = {"available": True, "source": "pma_l1_or_fallback", "detail": "Latest telemetry row returned"}
    except Exception as exc:
        telemetry_status = {"available": False, "source": None, "detail": str(exc)}

    payload = {
        "checked_at": datetime.now(timezone.utc),
        "database": database_status,
        "ml_artifacts": inference_service.readiness_status(),
        "threshold": _threshold_state(db),
        "audit_chain": _verify_audit_hash_chain(db),
        "telemetry_source": telemetry_status,
    }

    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="SYSTEM_STATUS_VIEW",
        status_value="SUCCESS",
    )

    return payload


@app.get("/api/dashboard/summary", response_model=schemas.DashboardSummary)
def read_dashboard_summary(
    request: Request,
    machine_id: str = "PMA Granulator #01",
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _record_audit_log(
        db,
        request=request,
        user_email=current_user.email,
        action="DASHBOARD_SUMMARY_VIEW",
        status_value="SUCCESS",
    )

    latest_rows = _latest_telemetry_rows(db, machine_id=machine_id, limit=1)
    latest_reading = latest_rows[0] if latest_rows else None
    latest_prediction = (
        db.query(models.AnomalyEvent)
        .filter(models.AnomalyEvent.machine_id == machine_id)
        .order_by(models.AnomalyEvent.timestamp.desc())
        .first()
    )
    recent_alerts = (
        db.query(models.AnomalyEvent)
        .filter(models.AnomalyEvent.machine_id == machine_id)
        .order_by(models.AnomalyEvent.timestamp.desc())
        .limit(10)
        .all()
    )

    metadata = inference_service.metadata()
    threshold_state = _threshold_state(db)
    threshold = threshold_state["threshold"]
    threshold_policy = threshold_state["threshold_policy"]

    if latest_prediction is None:
        machine_status = "NO DATA"
    elif latest_prediction.severity == "critical":
        machine_status = "CRITICAL"
    elif latest_prediction.is_anomaly:
        machine_status = "WARNING"
    else:
        machine_status = "HEALTHY"

    return {
        "machine_id": machine_id,
        "status": machine_status,
        "latest_reading": latest_reading,
        "latest_prediction": latest_prediction,
        "threshold": threshold,
        "threshold_policy": threshold_policy,
        "threshold_source": threshold_state["threshold_source"],
        "artifact_threshold": threshold_state["artifact_threshold"],
        "valid_window_count": metadata.get("valid_window_count"),
        "skipped_window_count": metadata.get("skipped_window_count"),
        "artifact_status": inference_service.readiness_status(),
        "recent_alerts": recent_alerts,
    }

router = APIRouter(prefix="/api/rag", tags=["RAG Document Intelligence"])
class ChatRequest(BaseModel):
    question: str
    machine_filter: Optional[str] = None
    target_language: Optional[str] = "English" # Tell FastAPI to expect this!

@app.post("/api/rag/upload")
async def upload_manual(
    file: UploadFile = File(...),
    machine_type: str = Form(...),  # Receives "PMA", "Fette", etc., from the dropdown
    current_user: models.User = Depends(get_current_user),
):
    try:
        # Validate input to ensure data sanitization
        machine_type = machine_type.strip().upper()
        if not machine_type:
            raise HTTPException(status_code=400, detail="Machine type tag is required.")

        # Save the file using its real name instead of a hardcoded string
        # to prevent files from overwriting each other
        clean_filename = f"{machine_type}_{file.filename}"
        target_dir = os.path.join("storage", "manuals")
        os.makedirs(target_dir, exist_ok=True)
        
        saved_file_path = os.path.join(target_dir, clean_filename)
        with open(saved_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Run the upgraded ingestion pipeline and pass the category tag
        run_ingestion_pipeline(saved_file_path, machine_type)

        global _global_chat_engine
        _global_chat_engine = None
        
        return {"status": "success", "message": f"Successfully indexed into {machine_type} memory."}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/api/rag/chat")
async def execute_rag_query(
    payload: ChatRequest,
    current_user: models.User = Depends(get_current_user),
):
    """Answers user queries grounded securely inside engineering documentation."""
    try:
        # Ask the gatekeeper for the AI. 
        # (It will be slow on the first question, but lightning fast on all future questions).
        engine = get_chat_engine()
        
        # THE FIX: Explicitly pass target_language down to the engine!
        response_data = engine.ask(
            question=payload.question, 
            machine_filter=payload.machine_filter,
            target_language=payload.target_language  # <-- THIS IS THE MISSING WIRE!
        )
        
        return response_data
        
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            raise HTTPException(status_code=429, detail="Gemini project quota exhausted. Please retry in 60 seconds.")
        raise HTTPException(status_code=500, detail=f"Execution Error: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
