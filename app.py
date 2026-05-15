"""
EcoSentinel – Human–Wildlife Conflict Management System
Flask backend with BI analytics
"""
import base64
import io
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from functools import wraps

from flask import Flask, flash, jsonify, make_response, redirect, render_template, request, session, url_for
import matplotlib
matplotlib.use('Agg')
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    CommunityReport,
    INCIDENT_COLUMNS,
    Incident,
    User,
    as_float,
    as_int,
    db,
    init_database,
    initialize_database,
    parse_date,
)

app = Flask(__name__)
app.secret_key = os.environ.get("ECOSENTINEL_SECRET_KEY", "ecosentinel-dev-secret")
init_database(app)

# ── helpers ──────────────────────────────────────────────────────────────────

def load_data():
    records = load_incident_records()
    if not records:
        return pd.DataFrame(columns=INCIDENT_COLUMNS + ["risk_category", "year", "month"])
    df = pd.DataFrame(records)
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df["verified_at"] = df["verified_at"].fillna("").astype(str)
    df["risk_score"] = pd.to_numeric(df["risk_score"], errors="coerce").fillna(0)
    df["human_casualties"] = pd.to_numeric(df["human_casualties"], errors="coerce").fillna(0).astype(int)
    df["livestock_loss"] = pd.to_numeric(df["livestock_loss"], errors="coerce").fillna(0).astype(int)
    df["crop_damage_ha"] = pd.to_numeric(df["crop_damage_ha"], errors="coerce").fillna(0.0)
    df["year"] = df["report_date"].dt.year
    df["month"] = df["report_date"].dt.month
    df["risk_category"] = df["risk_score"].apply(risk_category)
    return df

def load_incident_records():
    incidents = Incident.query.order_by(Incident.incident_id.desc()).all()
    return [incident.to_record(risk_category) for incident in incidents]

def apply_record_filters(records):
    species = request.args.get("species", "")
    district = request.args.get("district", "")
    season = request.args.get("season", "")
    risk = request.args.get("risk", "")
    status = request.args.get("status", "")
    query = request.args.get("q", "").strip().lower()

    filtered = []
    for record in records:
        if species and record.get("animal_species") != species:
            continue
        if district and record.get("district") != district:
            continue
        if season and record.get("season") != season:
            continue
        if risk and record.get("risk_category") != risk:
            continue
        if status and record.get("verification_status") != status:
            continue
        if query:
            haystack = " ".join(
                str(record.get(key, "") or "")
                for key in ["district", "forest_beat", "animal_species", "conflict_type", "officer_notes", "response_action"]
            ).lower()
            if query not in haystack:
                continue
        filtered.append(record)
    return filtered

def apply_data_filters(df):
    species = request.args.get("species", "")
    district = request.args.get("district", "")
    season = request.args.get("season", "")
    risk = request.args.get("risk", "")
    status = request.args.get("status", "")
    query = request.args.get("q", "").strip().lower()

    if species:
        df = df[df["animal_species"] == species]
    if district:
        df = df[df["district"] == district]
    if season:
        df = df[df["season"] == season]
    if risk:
        df = df[df["risk_category"] == risk]
    if status:
        df = df[df["verification_status"] == status]
    if query and not df.empty:
        haystack = df[["district", "forest_beat", "animal_species", "conflict_type", "officer_notes", "response_action"]].fillna("").astype(str)
        df = df[haystack.apply(lambda row: query in " ".join(row).lower(), axis=1)]
    return df

def risk_category(score):
    score = float(score)
    if score >= 20:
        return "High"
    if score >= 10:
        return "Medium"
    return "Low"

def current_user():
    if "username" not in session:
        return None
    return {"username": session["username"], "role": session.get("role"), "name": session.get("name", session["username"])}

def get_current_user_model():
    username = session.get("username")
    if not username:
        return None
    return User.query.filter_by(username=username).first()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("login", next=request.path))
            if user["role"] not in roles:
                flash("You do not have permission to access that page.", "error")
                if user["role"] == "community":
                    return redirect(url_for("community_dashboard"))
                return redirect(url_for("officer_dashboard" if user["role"] == "officer" else "admin_dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator

def dashboard_for_role(role):
    if role == "admin":
        return "admin_dashboard"
    if role == "officer":
        return "officer_dashboard"
    return "community_dashboard"

def google_oauth_configured():
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))

def google_redirect_uri():
    return url_for("community_google_callback", _external=True)

def exchange_google_code(code):
    token_payload = urllib.parse.urlencode({
        "code": code,
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": google_redirect_uri(),
        "grant_type": "authorization_code",
    }).encode("utf-8")
    token_request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=token_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(token_request, timeout=10) as response:
        token_data = json.loads(response.read().decode("utf-8"))
    access_token = token_data.get("access_token")
    if not access_token:
        raise ValueError("Google did not return an access token")
    user_request = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(user_request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))

def login_user_model(user):
    session.clear()
    session["username"] = user.username
    session["role"] = user.role
    session["name"] = user.name or user.username

def create_or_update_google_community_user(profile, mobile):
    email = (profile.get("email") or "").strip().lower()
    if not email:
        raise ValueError("Google account did not provide an email address")
    user = User.query.filter_by(username=email).first()
    if user and user.role != "community":
        raise ValueError("This email is already used by a system access account")
    if not user:
        user = User(
            username=email,
            password_hash=generate_password_hash(secrets.token_urlsafe(32)),
            role="community",
            name=(profile.get("name") or email).strip(),
            mobile=mobile,
            auth_provider="google",
            active=True,
        )
        db.session.add(user)
    else:
        user.name = (profile.get("name") or user.name or email).strip()
        user.mobile = mobile
        user.auth_provider = "google"
        user.active = True
    db.session.commit()
    return user

@app.context_processor
def inject_user():
    return {"current_user": current_user()}

def fig_to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110, facecolor=fig.get_facecolor())
    buf.seek(0)
    img = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return img

def empty_chart(title="No data for selected filters"):
    fig, ax = plt.subplots(figsize=(5, 3.5))
    style_fig(fig, [ax])
    ax.set_xticks([])
    ax.set_yticks([])
    ax.text(0.5, 0.5, "No data for selected filters", ha="center", va="center",
            color="#94a3b8", fontsize=10, transform=ax.transAxes)
    ax.set_title(title, fontsize=10)
    return jsonify({"img": fig_to_b64(fig)})

PALETTE = {
    "Elephant":  "#4E7AC7",
    "Wild Boar": "#E07B39",
    "Leopard":   "#5BAD72",
    "Monkey":    "#A855C8",
    "Deer":      "#D4B844",
    "Tiger":     "#F97316",
    "Gaur":      "#14B8A6",
    "Sloth Bear": "#8B5A2B",
    "Black Bear": "#64748B",
    "Hyena":     "#D97706",
    "Rhinoceros": "#7C8A92",
    "Wild Buffalo": "#475569",
}

SEASON_COLORS = {"Summer":"#E07B39","Monsoon":"#4E7AC7","Post-Monsoon":"#5BAD72","Winter":"#A855C8"}
CONFLICT_COLORS = {"Human Attack":"#E05252","Crop Damage":"#E0B052","Livestock Predation":"#5271E0","Property Damage":"#52B88A"}
ACTION_COLORS = {"Awareness Campaign":"#4E7AC7","Patrol Increased":"#E07B39","Compensation Provided":"#5BAD72","Animal Relocated":"#A855C8"}

def style_fig(fig, ax_list=None):
    fig.patch.set_facecolor("#0f172a")
    for ax in (ax_list or fig.axes):
        ax.set_facecolor("#1e293b")
        ax.tick_params(colors="#94a3b8", labelsize=8)
        ax.xaxis.label.set_color("#94a3b8")
        ax.yaxis.label.set_color("#94a3b8")
        ax.title.set_color("#e2e8f0")
        for spine in ax.spines.values():
            spine.set_edgecolor("#334155")
    return fig

def serialize_incident_records(df):
    chunk = df.copy()
    if "report_date" in chunk.columns:
        report_dates = pd.to_datetime(chunk["report_date"], errors="coerce")
        chunk["report_date"] = report_dates.dt.strftime("%Y-%m-%d").fillna("")
    if "created_at" in chunk.columns:
        created_at = pd.to_datetime(chunk["created_at"], errors="coerce")
        chunk["created_at"] = created_at.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
    if "verified_at" in chunk.columns:
        verified_at = pd.to_datetime(chunk["verified_at"], errors="coerce")
        chunk["verified_at"] = verified_at.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
    return chunk.where(pd.notnull(chunk), "").to_dict(orient="records")

# ── routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.active and check_password_hash(user.password_hash, password):
            login_user_model(user)
            target = request.args.get("next")
            if target:
                return redirect(target)
            return redirect(url_for(dashboard_for_role(user.role)))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/community-login", methods=["GET", "POST"])
def community_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=email, role="community").first()
        if user and user.active and check_password_hash(user.password_hash, password):
            login_user_model(user)
            return redirect(url_for("community_dashboard"))
        flash("Invalid community login details.", "error")
    return render_template("community_auth.html", mode="login", google_enabled=google_oauth_configured())

@app.route("/community-signup", methods=["GET", "POST"])
def community_signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        mobile = request.form.get("mobile", "").strip()
        password = request.form.get("password", "")
        if not name or not email or not mobile or not password:
            flash("Name, email, mobile number, and password are required.", "error")
        elif User.query.filter_by(username=email).first():
            flash("An account already exists for this email.", "error")
        else:
            db.session.add(User(
                username=email,
                password_hash=generate_password_hash(password),
                role="community",
                name=name,
                mobile=mobile,
                auth_provider="local",
                active=True,
            ))
            db.session.commit()
            flash("Community account created. Please log in.", "success")
            return redirect(url_for("community_login"))
    return render_template("community_auth.html", mode="signup", google_enabled=google_oauth_configured())

@app.route("/community-google")
def community_google_start():
    if not google_oauth_configured():
        flash("Google sign-in is not configured yet. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET before deployment.", "error")
        return redirect(url_for("community_login"))
    state = secrets.token_urlsafe(24)
    session["google_oauth_state"] = state
    params = urllib.parse.urlencode({
        "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
        "redirect_uri": google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + params)

@app.route("/community-google/callback")
def community_google_callback():
    if request.args.get("state") != session.get("google_oauth_state"):
        flash("Google sign-in could not be verified. Please try again.", "error")
        return redirect(url_for("community_login"))
    code = request.args.get("code", "")
    if not code:
        flash("Google sign-in was cancelled.", "error")
        return redirect(url_for("community_login"))
    try:
        profile = exchange_google_code(code)
    except (ValueError, urllib.error.URLError, TimeoutError):
        flash("Unable to complete Google sign-in right now.", "error")
        return redirect(url_for("community_login"))
    if not profile.get("email_verified", False):
        flash("Please use a verified Google email address.", "error")
        return redirect(url_for("community_login"))
    session.pop("google_oauth_state", None)
    session["pending_google_community"] = {
        "email": (profile.get("email") or "").strip().lower(),
        "name": (profile.get("name") or "").strip(),
    }
    return redirect(url_for("community_google_mobile"))

@app.route("/community-google/mobile", methods=["GET", "POST"])
def community_google_mobile():
    profile = session.get("pending_google_community")
    if not profile:
        return redirect(url_for("community_login"))
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        if not mobile:
            flash("Mobile number is required to continue.", "error")
        else:
            try:
                user = create_or_update_google_community_user(profile, mobile)
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("community_login"))
            session.pop("pending_google_community", None)
            login_user_model(user)
            return redirect(url_for("community_dashboard"))
    return render_template("community_google_mobile.html", profile=profile)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    return redirect(url_for(dashboard_for_role(user["role"])))

@app.route("/admin-dashboard")
@role_required("admin")
def admin_dashboard():
    return render_template("admin_dashboard.html")

@app.route("/officer-dashboard")
@role_required("officer")
def officer_dashboard():
    return render_template("officer_dashboard.html")

@app.route("/community-dashboard")
@role_required("community")
def community_dashboard():
    return render_template("community_dashboard.html")

@app.route("/incidents")
@role_required("admin", "officer", "community")
def incidents_page():
    return render_template("incidents.html")

@app.route("/admin/incidents")
@role_required("admin")
def admin_incidents_page():
    return render_template("admin_incidents.html")

@app.route("/admin/users")
@role_required("admin")
def users_page():
    return render_template("users.html")

@app.route("/bi")
@role_required("admin", "officer", "community")
def bi_page():
    return render_template("bi.html")

@app.route("/map")
@role_required("admin", "officer", "community")
def map_page():
    return render_template("map.html")

@app.route("/community-report")
@role_required("community")
def community_report_page():
    return render_template("community_report.html")

# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/summary")
def api_summary():
    df = apply_data_filters(load_data())
    avg_risk = round(float(df["risk_score"].mean()), 2) if len(df) else 0
    return jsonify({
        "total_incidents": int(len(df)),
        "states_affected": int(df["state"].nunique()) if "state" in df.columns else 0,
        "districts_affected": int(df["district"].nunique()),
        "total_casualties": int(df["human_casualties"].sum()),
        "total_livestock": int(df["livestock_loss"].sum()),
        "total_crop_ha": round(float(df["crop_damage_ha"].sum()), 2),
        "avg_risk_score": avg_risk,
        "high_risk_incidents": int((df["risk_score"] >= 20).sum()),
        "medium_risk_incidents": int(((df["risk_score"] >= 10) & (df["risk_score"] < 20)).sum()),
        "low_risk_incidents": int((df["risk_score"] < 10).sum()),
        "pending_verification": int((df["verification_status"] == "Pending").sum()),
        "verified_incidents": int((df["verification_status"] == "Verified").sum()),
        "species_count": int(df["animal_species"].nunique()),
    })

@app.route("/api/incidents")
@login_required
def api_incidents():
    page = as_int(request.args.get("page", 1), 1)
    per_page = as_int(request.args.get("per_page", 10), 10)
    records = apply_record_filters(load_incident_records())
    records.sort(
        key=lambda record: (
            record.get("report_date") or "",
            record.get("created_at") or "",
            int(record.get("incident_id", 0)),
        ),
        reverse=True,
    )
    total = len(records)
    start = (page-1)*per_page
    records = records[start:start+per_page]
    return jsonify({"total": total, "page": page, "per_page": per_page, "data": records})

@app.route("/api/filters")
@login_required
def api_filters():
    df = load_data()
    location_cols = ["state", "forest_beat", "district", "latitude", "longitude"]
    locations = []
    if not df.empty:
        location_df = (
            df[location_cols]
            .dropna(subset=["forest_beat"])
            .groupby(["state", "district", "forest_beat"], as_index=False)
            .agg(latitude=("latitude", "mean"), longitude=("longitude", "mean"))
            .sort_values(["state", "district", "forest_beat"])
        )
        locations = [
            {
                "state": row["state"],
                "name": row["forest_beat"],
                "district": row["district"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
            }
            for _, row in location_df.iterrows()
        ]
    return jsonify({
        "states": sorted([value for value in df["state"].dropna().unique().tolist() if value]),
        "species": sorted([value for value in df["animal_species"].dropna().unique().tolist() if value]),
        "districts": sorted([value for value in df["district"].dropna().unique().tolist() if value]),
        "locations": locations,
        "seasons": sorted([value for value in df["season"].dropna().unique().tolist() if value]),
        "conflict_types": sorted([value for value in df["conflict_type"].dropna().unique().tolist() if value]),
        "risk_categories": ["Low", "Medium", "High"],
        "verification_statuses": ["Pending", "Verified", "Rejected"],
    })

@app.route("/api/incidents/add", methods=["POST"])
@role_required("admin", "officer")
def add_incident():
    data = request.json or {}
    next_incident_id = db.session.query(func.max(Incident.incident_id)).scalar() or 0
    current_model_user = get_current_user_model()
    report_date = parse_date(data.get("report_date"))
    incident = Incident(
        incident_id=int(next_incident_id) + 1,
        report_date=report_date,
        state=(data.get("state") or "India").strip() or "India",
        district=(data.get("district") or "").strip(),
        forest_beat=(data.get("forest_beat") or "").strip(),
        latitude=as_float(data.get("latitude"), 11.0),
        longitude=as_float(data.get("longitude"), 78.0),
        animal_species=(data.get("animal_species") or "").strip(),
        conflict_type=(data.get("conflict_type") or "").strip(),
        season=(data.get("season") or "").strip(),
        risk_score=as_float(data.get("risk_score"), 10.0),
        response_action=(data.get("response_action") or "").strip(),
        officer_notes=(data.get("officer_notes") or "").strip(),
        human_casualties=as_int(data.get("human_casualties"), 0),
        livestock_loss=as_int(data.get("livestock_loss"), 0),
        crop_damage_ha=as_float(data.get("crop_damage_ha"), 0.0),
        verification_status="Pending",
        created_by_user_id=current_model_user.id if current_model_user else None,
    )
    db.session.add(incident)
    db.session.commit()
    if incident.report_date is None:
        incident.report_date = incident.created_at.date() if incident.created_at else datetime.utcnow().date()
        db.session.commit()
    return jsonify({
        "success": True,
        "incident_id": incident.incident_id,
        "risk_category": risk_category(incident.risk_score),
        "report_date": incident.report_date.isoformat() if incident.report_date else "",
    })

@app.route("/api/incidents/<int:incident_id>/verify", methods=["POST"])
@role_required("admin")
def verify_incident(incident_id):
    payload = request.json or {}
    status = payload.get("status", "Verified")
    if status not in {"Pending", "Verified", "Rejected"}:
        return jsonify({"success": False, "error": "Invalid status"}), 400
    incident = Incident.query.filter_by(incident_id=incident_id).first()
    if not incident:
        return jsonify({"success": False, "error": "Incident not found"}), 404
    if status == "Pending":
        incident.verified_by_user_id = None
        incident.verified_at = None
    else:
        current_model_user = get_current_user_model()
        incident.verified_by_user_id = current_model_user.id if current_model_user else None
        incident.verified_at = datetime.utcnow()
    incident.verification_status = status
    db.session.commit()
    return jsonify({"success": True, "incident_id": incident_id, "status": status})

@app.route("/api/community_reports", methods=["GET"])
@role_required("officer", "admin")
def api_community_reports():
    reports = CommunityReport.query.order_by(CommunityReport.created_at.desc()).limit(50).all()
    return jsonify({"reports": [report.safe_dict() for report in reports]})

@app.route("/api/community_reports/add", methods=["POST"])
@role_required("community")
def add_community_report():
    data = request.json or {}
    current_model_user = get_current_user_model()
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400
    report = CommunityReport(
        reporter_user_id=current_model_user.id if current_model_user else None,
        reporter_name=current_model_user.name if current_model_user else session.get("name", ""),
        reporter_email=current_model_user.username if current_model_user else session.get("username", ""),
        reporter_mobile=current_model_user.mobile if current_model_user else "",
        state=(data.get("state") or "").strip(),
        district=(data.get("district") or "").strip(),
        place=(data.get("place") or "").strip(),
        animal_species=(data.get("animal_species") or "").strip(),
        incident_date=parse_date(data.get("incident_date")),
        message=message,
    )
    db.session.add(report)
    db.session.commit()
    return jsonify({"success": True, "report_id": report.id})

@app.route("/api/community_reports/<int:report_id>/status", methods=["POST"])
@role_required("officer", "admin")
def update_community_report(report_id):
    report = CommunityReport.query.get(report_id)
    if not report:
        return jsonify({"success": False, "error": "Report not found"}), 404
    payload = request.json or {}
    status = payload.get("status", "Reviewed")
    if status not in {"New", "Reviewed", "Converted", "Closed"}:
        return jsonify({"success": False, "error": "Invalid status"}), 400
    current_model_user = get_current_user_model()
    report.status = status
    report.officer_note = (payload.get("officer_note") or report.officer_note or "").strip()
    report.reviewed_by_user_id = current_model_user.id if current_model_user else None
    report.reviewed_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True, "report": report.safe_dict()})

@app.route("/api/users")
@role_required("admin")
def api_users():
    users = User.query.order_by(User.created_at.asc(), User.username.asc()).all()
    return jsonify({"users": [user.safe_dict() for user in users]})

@app.route("/api/users/add", methods=["POST"])
@role_required("admin")
def add_user():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "officer").strip()
    name = (data.get("name") or username).strip() or username
    if not username or not password or role not in {"admin", "officer"}:
        return jsonify({"success": False, "error": "Username, password, and valid role are required"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"success": False, "error": "Username already exists"}), 400
    db.session.add(User(username=username, password_hash=generate_password_hash(password), role=role, name=name, active=True))
    db.session.commit()
    return jsonify({"success": True})

@app.route("/api/users/<username>/toggle", methods=["POST"])
@role_required("admin")
def toggle_user(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404
    if username == session.get("username"):
        return jsonify({"success": False, "error": "You cannot disable your own account"}), 400
    if user.role == "admin":
        return jsonify({"success": False, "error": "Admin accounts cannot be disabled"}), 400
    user.active = not user.active
    db.session.commit()
    return jsonify({"success": True, "active": user.active})

@app.route("/api/map_data")
@login_required
def map_data():
    df = apply_data_filters(load_data())
    records = df[["incident_id","district","forest_beat","latitude","longitude","animal_species",
                  "conflict_type","risk_score","risk_category","human_casualties","season",
                  "verification_status","report_date"]].copy()
    records["report_date"] = records["report_date"].astype(str)
    response = make_response(jsonify(json.loads(records.to_json(orient="records"))))
    response.headers["Cache-Control"] = "no-store"
    return response

# ── BI chart endpoints ────────────────────────────────────────────────────────

@app.route("/api/patrol_plan")
@role_required("admin", "officer")
def api_patrol_plan():
    df = apply_data_filters(load_data())
    if df.empty:
        return jsonify({"plan": []})

    grouped = df.groupby(["district", "forest_beat"], dropna=False).agg(
        incidents=("incident_id", "count"),
        avg_risk=("risk_score", "mean"),
        max_risk=("risk_score", "max"),
        high_risk=("risk_score", lambda scores: int((scores >= 20).sum())),
        casualties=("human_casualties", "sum"),
        livestock=("livestock_loss", "sum"),
        crop=("crop_damage_ha", "sum"),
        latest_report=("report_date", "max"),
    ).reset_index()
    grouped["priority_score"] = (
        grouped["max_risk"] * 1.6
        + grouped["avg_risk"]
        + grouped["high_risk"] * 4
        + grouped["casualties"] * 3
        + grouped["livestock"] * 0.5
        + grouped["crop"] * 0.4
    )

    plan = []
    for _, row in grouped.sort_values("priority_score", ascending=False).head(5).iterrows():
        beat_df = df[(df["district"] == row["district"]) & (df["forest_beat"] == row["forest_beat"])]
        species = beat_df["animal_species"].mode()
        conflict = beat_df["conflict_type"].mode()

        if row["max_risk"] >= 20 or row["casualties"] > 0:
            priority = "Immediate"
            patrol_window = "Dawn and dusk patrol"
            recommended_action = "Increase patrol presence and alert rapid response"
        elif row["avg_risk"] >= 10:
            priority = "Scheduled"
            patrol_window = "Evening patrol"
            recommended_action = "Run route check and community warning"
        else:
            priority = "Monitor"
            patrol_window = "Routine daytime patrol"
            recommended_action = "Maintain observation and verify local reports"

        plan.append({
            "district": row["district"],
            "forest_beat": row["forest_beat"],
            "priority": priority,
            "patrol_window": patrol_window,
            "recommended_action": recommended_action,
            "incidents": int(row["incidents"]),
            "avg_risk": round(float(row["avg_risk"]), 1),
            "max_risk": round(float(row["max_risk"]), 1),
            "high_risk": int(row["high_risk"]),
            "dominant_species": species.iloc[0] if not species.empty else "Unknown",
            "common_conflict": conflict.iloc[0] if not conflict.empty else "Unknown",
            "latest_report": row["latest_report"].strftime("%Y-%m-%d") if pd.notna(row["latest_report"]) else "",
        })

    return jsonify({"plan": plan})

@app.route("/api/charts/species_donut")
@login_required
def chart_species_donut():
    df = apply_data_filters(load_data())
    counts = df["animal_species"].value_counts()
    if counts.empty:
        return empty_chart("Incidents by Species")
    counts = counts.sort_values(ascending=True)
    total = int(counts.sum())
    colors = [PALETTE.get(species, "#64748b") for species in counts.index]
    fig_height = max(3.8, min(6.2, 0.38 * len(counts) + 1.6))
    fig, ax = plt.subplots(figsize=(6.2, fig_height))
    bars = ax.barh(counts.index, counts.values, color=colors, edgecolor="#0f172a", linewidth=0.7)
    ax.set_title("Incidents by Species", color="#e2e8f0", fontsize=10, pad=10)
    ax.set_xlabel("Number of Incidents")
    ax.set_ylabel("")
    ax.grid(axis="x", color="#334155", alpha=0.55, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(counts.values) * 1.22)
    for bar, value in zip(bars, counts.values):
        pct = (int(value) / total) * 100 if total else 0
        ax.text(
            bar.get_width() + max(counts.values) * 0.02,
            bar.get_y() + bar.get_height() / 2,
            f"{int(value)} ({pct:.1f}%)",
            va="center",
            color="#cbd5e1",
            fontsize=8,
            fontweight="600",
        )
    style_fig(fig)
    ax.tick_params(axis="y", labelsize=8.5)
    return jsonify({"img": fig_to_b64(fig)})

@app.route("/api/charts/conflict_bar")
@login_required
def chart_conflict_bar():
    df = apply_data_filters(load_data())
    counts = df["conflict_type"].value_counts()
    if counts.empty:
        return empty_chart("Conflict Types")
    colors = [CONFLICT_COLORS.get(c, "#4E7AC7") for c in counts.index]
    fig, ax = plt.subplots(figsize=(5,3.5))
    bars = ax.barh(counts.index, counts.values, color=colors, edgecolor="#0f172a", linewidth=0.5)
    ax.set_xlabel("Number of Incidents")
    ax.set_title("Conflict Types", color="#e2e8f0", fontsize=10)
    for bar in bars:
        ax.text(bar.get_width()+0.3, bar.get_y()+bar.get_height()/2,
                str(int(bar.get_width())), va="center", color="#94a3b8", fontsize=8)
    style_fig(fig)
    return jsonify({"img": fig_to_b64(fig)})

@app.route("/api/charts/season_risk")
@login_required
def chart_season_risk():
    df = apply_data_filters(load_data())
    if df.empty:
        return empty_chart("Avg Risk Score by Season")
    season_order = ["Summer","Monsoon","Post-Monsoon","Winter"]
    avg = df.groupby("season")["risk_score"].mean().reindex(season_order)
    colors = [SEASON_COLORS.get(s,"#4E7AC7") for s in avg.index]
    fig, ax = plt.subplots(figsize=(5,3.5))
    bars = ax.bar(avg.index, avg.values, color=colors, edgecolor="#0f172a", linewidth=0.5, width=0.55)
    ax.set_ylabel("Avg Risk Score"); ax.set_title("Avg Risk Score by Season", fontsize=10)
    for bar in bars:
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.2,
                f"{bar.get_height():.1f}", ha="center", color="#94a3b8", fontsize=8)
    style_fig(fig)
    return jsonify({"img": fig_to_b64(fig)})

@app.route("/api/charts/top_districts")
@login_required
def chart_top_districts():
    df = apply_data_filters(load_data())
    top = df["district"].value_counts().head(10)
    if top.empty:
        return empty_chart("Top 10 Districts by Incidents")
    fig, ax = plt.subplots(figsize=(5,4))
    colors = ["#E05252" if v >= 4 else "#E07B39" if v >= 3 else "#4E7AC7" for v in top.values]
    ax.barh(top.index[::-1], top.values[::-1], color=colors[::-1], edgecolor="#0f172a")
    ax.set_xlabel("Incidents"); ax.set_title("Top 10 Districts by Incidents", fontsize=10)
    patches = [mpatches.Patch(color="#E05252",label="High (≥4)"),
               mpatches.Patch(color="#E07B39",label="Medium (3)"),
               mpatches.Patch(color="#4E7AC7",label="Low (<3)")]
    ax.legend(handles=patches, fontsize=7, facecolor="#1e293b", edgecolor="#334155",
              labelcolor="#94a3b8", loc="lower right")
    style_fig(fig)
    return jsonify({"img": fig_to_b64(fig)})

@app.route("/api/charts/response_pie")
@login_required
def chart_response_pie():
    df = apply_data_filters(load_data())
    counts = df["response_action"].value_counts()
    if counts.empty:
        return empty_chart("Response Actions Distribution")
    colors = [ACTION_COLORS.get(c,"#888") for c in counts.index]
    fig, ax = plt.subplots(figsize=(5,4))
    ax.pie(counts.values, labels=counts.index, colors=colors, autopct="%1.1f%%",
           startangle=90, wedgeprops=dict(edgecolor="#0f172a",linewidth=2),
           textprops=dict(color="#e2e8f0", fontsize=8))
    ax.set_title("Response Actions Distribution", fontsize=10)
    style_fig(fig); ax.set_facecolor("#0f172a")
    return jsonify({"img": fig_to_b64(fig)})

@app.route("/api/charts/risk_histogram")
@login_required
def chart_risk_histogram():
    df = apply_data_filters(load_data())
    if df.empty:
        return empty_chart("Risk Score Distribution")
    fig, ax = plt.subplots(figsize=(5,3.5))
    n, bins, patches = ax.hist(df["risk_score"], bins=15, edgecolor="#0f172a", linewidth=0.5)
    for patch, left in zip(patches, bins[:-1]):
        if left >= 20: patch.set_facecolor("#E05252")
        elif left >= 10: patch.set_facecolor("#E07B39")
        else: patch.set_facecolor("#5BAD72")
    ax.set_xlabel("Risk Score"); ax.set_ylabel("Frequency")
    ax.set_title("Risk Score Distribution", fontsize=10)
    patches_legend = [
        mpatches.Patch(color="#5BAD72",label="Low (<10)"),
        mpatches.Patch(color="#E07B39",label="Medium (10-20)"),
        mpatches.Patch(color="#E05252",label="High (≥20)"),
    ]
    ax.legend(handles=patches_legend, fontsize=7, facecolor="#1e293b",
              edgecolor="#334155", labelcolor="#94a3b8")
    style_fig(fig)
    return jsonify({"img": fig_to_b64(fig)})

@app.route("/api/charts/monthly_trend")
@login_required
def chart_monthly_trend():
    df = apply_data_filters(load_data())
    if df.empty:
        return empty_chart("Monthly Incident Trend")
    monthly = df.groupby(["year","month"]).size().reset_index(name="count")
    monthly["date"] = pd.to_datetime(monthly[["year","month"]].assign(day=1))
    monthly = monthly.sort_values("date")
    fig, ax = plt.subplots(figsize=(7,3.5))
    ax.plot(monthly["date"], monthly["count"], color="#4E7AC7", linewidth=2, marker="o",
            markersize=4, markerfacecolor="#E07B39")
    ax.fill_between(monthly["date"], monthly["count"], alpha=0.15, color="#4E7AC7")
    ax.set_xlabel("Date"); ax.set_ylabel("Incidents")
    ax.set_title("Monthly Incident Trend", fontsize=10)
    plt.xticks(rotation=35)
    style_fig(fig)
    return jsonify({"img": fig_to_b64(fig)})

@app.route("/api/charts/species_conflict_heatmap")
@login_required
def chart_species_conflict_heatmap():
    df = apply_data_filters(load_data())
    if df.empty:
        return empty_chart("Species x Conflict Type Heatmap")
    pivot = df.pivot_table(index="animal_species", columns="conflict_type", aggfunc="size", fill_value=0)
    fig, ax = plt.subplots(figsize=(6,4))
    sns.heatmap(pivot, annot=True, fmt="d", cmap="YlOrRd", ax=ax,
                linewidths=0.5, linecolor="#0f172a",
                cbar_kws={"shrink":0.7})
    ax.set_title("Species × Conflict Type Heatmap", fontsize=10)
    ax.set_xlabel(""); ax.set_ylabel("")
    plt.xticks(rotation=20, ha="right")
    style_fig(fig)
    ax.collections[0].colorbar.ax.tick_params(colors="#94a3b8")
    return jsonify({"img": fig_to_b64(fig)})

@app.route("/api/charts/damage_comparison")
@login_required
def chart_damage_comparison():
    df = apply_data_filters(load_data())
    if df.empty:
        return empty_chart("Damage Breakdown by Species")
    species_dmg = df.groupby("animal_species").agg(
        casualties=("human_casualties","sum"),
        livestock=("livestock_loss","sum"),
        crop=("crop_damage_ha","sum")
    ).reset_index()
    x = range(len(species_dmg))
    w = 0.28
    fig, ax = plt.subplots(figsize=(6,4))
    ax.bar([i-w for i in x], species_dmg["casualties"], width=w, label="Human Casualties",
           color="#E05252", edgecolor="#0f172a")
    ax.bar([i for i in x], species_dmg["livestock"], width=w, label="Livestock Loss",
           color="#E07B39", edgecolor="#0f172a")
    ax.bar([i+w for i in x], species_dmg["crop"], width=w, label="Crop Damage (ha)",
           color="#5BAD72", edgecolor="#0f172a")
    ax.set_xticks(list(x)); ax.set_xticklabels(species_dmg["animal_species"], rotation=15)
    ax.set_title("Damage Breakdown by Species", fontsize=10)
    ax.legend(fontsize=7, facecolor="#1e293b", edgecolor="#334155", labelcolor="#94a3b8")
    style_fig(fig)
    return jsonify({"img": fig_to_b64(fig)})

with app.app_context():
    initialize_database()

if __name__ == "__main__":
    app.run(debug=True, port=5050)
