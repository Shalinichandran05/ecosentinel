from datetime import date, datetime
import json
import os
import secrets

import pandas as pd
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash
from sqlalchemy import inspect, text


BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "data", "tamil_nadu_full_districts_100.csv")
USERS_PATH = os.path.join(BASE_DIR, "data", "users.json")
SQLITE_PATH = os.path.join(BASE_DIR, "ecosentinel.db")
DEFAULT_REPORT_DATE = date(2025, 1, 1)
INCIDENT_COLUMNS = [
    "incident_id",
    "report_date",
    "created_at",
    "state",
    "district",
    "forest_beat",
    "latitude",
    "longitude",
    "animal_species",
    "conflict_type",
    "season",
    "risk_score",
    "response_action",
    "officer_notes",
    "human_casualties",
    "livestock_loss",
    "crop_damage_ha",
    "verification_status",
    "verified_by",
    "verified_at",
]

db = SQLAlchemy()
migrate = Migrate()


def get_database_uri():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url
    return f"sqlite:///{SQLITE_PATH}"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="officer")
    name = db.Column(db.String(120), nullable=False)
    mobile = db.Column(db.String(30), nullable=False, default="")
    auth_provider = db.Column(db.String(30), nullable=False, default="local")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    created_incidents = db.relationship(
        "Incident",
        back_populates="created_by_user",
        foreign_keys="Incident.created_by_user_id",
        lazy=True,
    )
    verified_incidents = db.relationship(
        "Incident",
        back_populates="verified_by_user",
        foreign_keys="Incident.verified_by_user_id",
        lazy=True,
    )

    def safe_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "name": self.name,
            "mobile": self.mobile,
            "auth_provider": self.auth_provider,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class Incident(db.Model):
    __tablename__ = "incidents"

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    report_date = db.Column(db.Date, nullable=False, default=DEFAULT_REPORT_DATE)
    state = db.Column(db.String(120), nullable=False, default="India")
    district = db.Column(db.String(120), nullable=False, default="")
    forest_beat = db.Column(db.String(120), nullable=False, default="")
    latitude = db.Column(db.Float, nullable=False, default=11.0)
    longitude = db.Column(db.Float, nullable=False, default=78.0)
    animal_species = db.Column(db.String(120), nullable=False, default="")
    conflict_type = db.Column(db.String(120), nullable=False, default="")
    season = db.Column(db.String(60), nullable=False, default="")
    risk_score = db.Column(db.Float, nullable=False, default=10.0)
    response_action = db.Column(db.String(120), nullable=False, default="")
    officer_notes = db.Column(db.Text, nullable=False, default="")
    human_casualties = db.Column(db.Integer, nullable=False, default=0)
    livestock_loss = db.Column(db.Integer, nullable=False, default=0)
    crop_damage_ha = db.Column(db.Float, nullable=False, default=0.0)
    verification_status = db.Column(db.String(20), nullable=False, default="Pending")
    verified_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id], back_populates="created_incidents", lazy="joined")
    verified_by_user = db.relationship("User", foreign_keys=[verified_by_user_id], back_populates="verified_incidents", lazy="joined")

    def to_record(self, risk_category_func):
        effective_report_date = self.report_date or (self.created_at.date() if self.created_at else DEFAULT_REPORT_DATE)
        return {
            "incident_id": self.incident_id,
            "report_date": effective_report_date.isoformat() if effective_report_date else "",
            "created_at": self.created_at.isoformat(sep=" ") if self.created_at else "",
            "state": self.state,
            "district": self.district,
            "forest_beat": self.forest_beat,
            "latitude": float(self.latitude),
            "longitude": float(self.longitude),
            "animal_species": self.animal_species,
            "conflict_type": self.conflict_type,
            "season": self.season,
            "risk_score": float(self.risk_score),
            "response_action": self.response_action,
            "officer_notes": self.officer_notes or "",
            "human_casualties": int(self.human_casualties),
            "livestock_loss": int(self.livestock_loss),
            "crop_damage_ha": float(self.crop_damage_ha),
            "verification_status": self.verification_status,
            "verified_by": self.verified_by_user.username if self.verified_by_user else "",
            "verified_at": self.verified_at.isoformat(sep=" ") if self.verified_at else "",
            "risk_category": risk_category_func(self.risk_score),
        }


class CommunityReport(db.Model):
    __tablename__ = "community_reports"

    id = db.Column(db.Integer, primary_key=True)
    reporter_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reporter_name = db.Column(db.String(120), nullable=False, default="")
    reporter_email = db.Column(db.String(120), nullable=False, default="")
    reporter_mobile = db.Column(db.String(30), nullable=False, default="")
    state = db.Column(db.String(120), nullable=False, default="")
    district = db.Column(db.String(120), nullable=False, default="")
    place = db.Column(db.String(160), nullable=False, default="")
    animal_species = db.Column(db.String(120), nullable=False, default="")
    incident_date = db.Column(db.Date, nullable=False, default=DEFAULT_REPORT_DATE)
    message = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(30), nullable=False, default="New")
    officer_note = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    def safe_dict(self):
        return {
            "id": self.id,
            "reporter_name": self.reporter_name,
            "reporter_email": self.reporter_email,
            "reporter_mobile": self.reporter_mobile,
            "state": self.state,
            "district": self.district,
            "place": self.place,
            "animal_species": self.animal_species,
            "incident_date": self.incident_date.isoformat() if self.incident_date else "",
            "message": self.message,
            "status": self.status,
            "officer_note": self.officer_note,
            "created_at": self.created_at.isoformat(sep=" ") if self.created_at else "",
            "reviewed_at": self.reviewed_at.isoformat(sep=" ") if self.reviewed_at else "",
        }


def init_database(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    migrate.init_app(app, db)


def default_users():
    admin_password = os.environ.get("ECOSENTINEL_ADMIN_PASSWORD") or secrets.token_urlsafe(18)
    officer_password = os.environ.get("ECOSENTINEL_OFFICER_PASSWORD") or secrets.token_urlsafe(18)
    return [
        {"username": "admin", "password_hash": generate_password_hash(admin_password), "role": "admin", "name": "System Admin", "active": True},
        {"username": "officer", "password_hash": generate_password_hash(officer_password), "role": "officer", "name": "Field Officer", "active": True},
    ]


def parse_date(value):
    text = str(value or "").strip()
    if not text:
        return DEFAULT_REPORT_DATE
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return DEFAULT_REPORT_DATE


def parse_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def as_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def seed_users_if_needed():
    if User.query.count() > 0:
        return
    users_payload = []
    if os.path.exists(USERS_PATH):
        with open(USERS_PATH, "r", encoding="utf-8") as fh:
            users_payload = json.load(fh)
    if not users_payload:
        users_payload = default_users()
    for item in users_payload:
        db.session.add(User(
            username=item["username"],
            password_hash=item["password_hash"],
            role=item.get("role", "officer"),
            name=item.get("name") or item["username"],
            mobile=item.get("mobile", ""),
            auth_provider=item.get("auth_provider", "local"),
            active=bool(item.get("active", True)),
        ))
    db.session.commit()


def sync_builtin_passwords_from_env():
    password_envs = {
        "admin": os.environ.get("ECOSENTINEL_ADMIN_PASSWORD"),
        "officer": os.environ.get("ECOSENTINEL_OFFICER_PASSWORD"),
    }
    updated = False
    for username, password in password_envs.items():
        if not password:
            continue
        user = User.query.filter_by(username=username).first()
        if user:
            user.password_hash = generate_password_hash(password)
            updated = True
    if updated:
        db.session.commit()


def ensure_schema():
    inspector = inspect(db.engine)
    if not inspector.has_table("users"):
        return
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "mobile" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN mobile VARCHAR(30) NOT NULL DEFAULT ''"))
    if "auth_provider" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN auth_provider VARCHAR(30) NOT NULL DEFAULT 'local'"))
    if inspector.has_table("community_reports"):
        report_columns = {column["name"] for column in inspector.get_columns("community_reports")}
        if "reporter_mobile" not in report_columns:
            db.session.execute(text("ALTER TABLE community_reports ADD COLUMN reporter_mobile VARCHAR(30) NOT NULL DEFAULT ''"))
    db.session.commit()


def seed_incidents_if_needed():
    if Incident.query.count() > 0 or not os.path.exists(DATA_PATH):
        return
    user_map = {user.username: user.id for user in User.query.all()}
    legacy_df = pd.read_csv(DATA_PATH)
    for _, row in legacy_df.iterrows():
        verified_by = str(row.get("verified_by", "") or "").strip()
        district = str(row.get("district", "") or "")
        db.session.add(Incident(
            incident_id=as_int(row.get("incident_id"), 0),
            report_date=parse_date(row.get("report_date")),
            state=str(row.get("state", "India") or "India"),
            district=district,
            forest_beat=str(row.get("forest_beat", "") or ""),
            latitude=as_float(row.get("latitude"), 11.0),
            longitude=as_float(row.get("longitude"), 78.0),
            animal_species=str(row.get("animal_species", "") or ""),
            conflict_type=str(row.get("conflict_type", "") or ""),
            season=str(row.get("season", "") or ""),
            risk_score=as_float(row.get("risk_score"), 10.0),
            response_action=str(row.get("response_action", "") or ""),
            officer_notes=str(row.get("officer_notes", "") or ""),
            human_casualties=as_int(row.get("human_casualties"), 0),
            livestock_loss=as_int(row.get("livestock_loss"), 0),
            crop_damage_ha=as_float(row.get("crop_damage_ha"), 0.0),
            verification_status=str(row.get("verification_status", "Pending") or "Pending"),
            verified_by_user_id=user_map.get(verified_by),
            verified_at=parse_datetime(row.get("verified_at")),
        ))
    db.session.commit()


def repair_incident_dates():
    updated = False
    for incident in Incident.query.filter(Incident.report_date.is_(None)).all():
        incident.report_date = incident.created_at.date() if incident.created_at else DEFAULT_REPORT_DATE
        updated = True
    if updated:
        db.session.commit()


def initialize_database():
    db.create_all()
    ensure_schema()
    seed_users_if_needed()
    sync_builtin_passwords_from_env()
    seed_incidents_if_needed()
    repair_incident_dates()
