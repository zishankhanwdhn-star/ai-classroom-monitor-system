"""
app.py — AI Classroom Monitor v3
===================================
COMPLETE UPGRADED FLASK APPLICATION
All routes, APIs, settings, email, CSV, recording.
Python 3.11 compatible.

Run:  py -3.11 app.py
Open: http://127.0.0.1:5000
"""

import time
import json
from functools import wraps

from flask import (
    Flask, render_template, Response,
    request, redirect, url_for,
    session, jsonify, make_response
)

from database       import Database
from camera_manager import CameraManager
from alert_manager  import AlertManager
from email_service  import EmailService


# ── App ───────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "AI_MONITOR_V3_SECRET_xK9mP2025"

# ── Passwords (change before deployment) ─────────────────────────────────────
PASSWORD       = "12345"
ADMIN_PASSWORD = "admin123"

# ── Init services ─────────────────────────────────────────────────────────────
db     = Database()
cam    = CameraManager(db)
alerts = AlertManager(threshold=int(db.get_setting("overcrowd_limit", "30")))
alerts.set_db(db)
email  = EmailService(db)

# DB log throttle
_last_db_log: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH DECORATORS
# ══════════════════════════════════════════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def _w(*a, **kw):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*a, **kw)
    return _w


def admin_required(f):
    @wraps(f)
    def _w(*a, **kw):
        if not session.get("admin_in"):
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return _w


# ══════════════════════════════════════════════════════════════════════════════
#  USER AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == PASSWORD:
            session["logged_in"]  = True
            session["login_time"] = time.time()
            db.log_visitor()
            return redirect(url_for("dashboard"))
        error = "❌ Incorrect password. Try again."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN PAGES (multi-page navigation)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("index.html", active="dashboard")


@app.route("/analytics")
@login_required
def analytics():
    return render_template("analytics.html", active="analytics")


@app.route("/reports")
@login_required
def reports():
    return render_template("reports.html", active="reports")


@app.route("/logs")
@login_required
def logs_page():
    return render_template("logs.html", active="logs")


@app.route("/settings")
@login_required
def settings_page():
    sett = db.get_all_settings()
    return render_template("settings.html", active="settings", settings=sett)


# ══════════════════════════════════════════════════════════════════════════════
#  VIDEO STREAM
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/video")
@login_required
def video():
    return Response(cam.generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


# ══════════════════════════════════════════════════════════════════════════════
#  LIVE STATS API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/stats")
@login_required
def api_stats():
    global _last_db_log

    st     = cam.status()
    count  = st["count"]
    now    = time.time()

    # Auto-log every 30 min
    if now - _last_db_log >= 1800:
        db.log_count(0, count)
        _last_db_log = now

    # Read settings
    alerts_on = db.get_setting("alerts_enabled", "1") == "1"
    limit     = int(db.get_setting("overcrowd_limit", "30"))
    alerts.update_threshold(limit)

    alert = alerts.check(count, alerts_enabled=alerts_on)

    return jsonify({
        "count":     count,
        "online":    st["online"],
        "enabled":   st["enabled"],
        "recording": st["recording"],
        "behavior":  st["behavior"],
        "alert":     alert,
        "logs":      db.get_recent_logs(15),
        "time":      time.strftime("%H:%M:%S"),
        "auto_refresh": db.get_setting("auto_refresh", "1") == "1",
    })


# ══════════════════════════════════════════════════════════════════════════════
#  CAMERA CONTROL APIs
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/capture")
@login_required
def api_capture():
    path = cam.capture_now(camera_id=0)
    if path:
        return jsonify({"status": "ok", "file": path, "count": cam.student_count})
    return jsonify({"status": "error", "message": "Camera offline"}), 400


@app.route("/api/camera/toggle")
@login_required
def api_camera_toggle():
    state = cam.toggle_camera()
    return jsonify({"status": "ok", "enabled": state})


@app.route("/api/camera/reconnect")
@login_required
def api_camera_reconnect():
    cam.reconnect()
    return jsonify({"status": "ok", "message": "Reconnect triggered"})


@app.route("/api/camera/record/start")
@login_required
def api_record_start():
    if cam.recording:
        return jsonify({"status": "error", "message": "Already recording"})
    fname = cam.start_recording()
    return jsonify({"status": "ok", "file": fname})


@app.route("/api/camera/record/stop")
@login_required
def api_record_stop():
    cam.stop_recording()
    return jsonify({"status": "ok"})


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYTICS API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/analytics")
@login_required
def api_analytics():
    return jsonify({
        "hourly":    db.get_hourly_counts(24),
        "today":     db.get_today_stats(),
        "yesterday": db.get_yesterday_stats(),
        "camera":    db.get_camera_stats(),
        "peak":      db.get_peak_count(),
        "avg":       db.get_avg_count(),
        "generated": time.strftime("%H:%M:%S"),
    })


# ══════════════════════════════════════════════════════════════════════════════
#  REPORTS APIs
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/report")
@login_required
def api_report():
    camera_id   = request.args.get("camera", None, type=int)
    date_filter = request.args.get("date", None)
    data        = db.get_full_report(camera_id=camera_id, date_filter=date_filter)
    return jsonify(data)


@app.route("/api/report/csv")
@login_required
def api_report_csv():
    camera_id   = request.args.get("camera", None, type=int)
    date_filter = request.args.get("date", None)
    csv_data    = db.export_csv(camera_id=camera_id, date_filter=date_filter)

    resp = make_response(csv_data)
    fname = f"report_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    resp.headers["Content-Disposition"] = f"attachment; filename={fname}"
    resp.headers["Content-Type"]        = "text/csv"
    return resp


@app.route("/api/report/email", methods=["POST"])
@login_required
def api_report_email():
    data = db.get_full_report()
    ok, msg = email.send_report(data)
    return jsonify({"status": "ok" if ok else "error", "message": msg})


# ══════════════════════════════════════════════════════════════════════════════
#  LOGS API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/logs")
@login_required
def api_logs():
    camera_id   = request.args.get("camera", None, type=int)
    date_filter = request.args.get("date", None)
    search      = request.args.get("search", None)
    limit       = request.args.get("limit", 100, type=int)
    logs        = db.get_recent_logs(limit=limit, camera_id=camera_id,
                                     date_filter=date_filter, search=search)
    return jsonify({"logs": logs, "count": len(logs)})


@app.route("/api/logs/clear", methods=["POST"])
@login_required
def api_logs_clear():
    db.manual_clear_logs()
    return jsonify({"status": "ok", "message": "All logs cleared."})


@app.route("/api/alerts/history")
@login_required
def api_alert_history():
    return jsonify({"alerts": db.get_alert_history(50)})


# ══════════════════════════════════════════════════════════════════════════════
#  SETTINGS API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/settings", methods=["POST"])
@login_required
def api_save_settings():
    data = request.get_json(force=True) or {}
    allowed = {
        "overcrowd_limit", "auto_capture", "alerts_enabled",
        "auto_refresh", "email_enabled", "email_address",
        "email_smtp", "email_port", "email_user", "email_pass",
        "auto_delete_days",
    }
    for k, v in data.items():
        if k in allowed:
            db.set_setting(k, str(v))

    # Update alert threshold live
    limit = int(db.get_setting("overcrowd_limit", "30"))
    alerts.update_threshold(limit)

    return jsonify({"status": "ok", "message": "Settings saved successfully."})


@app.route("/api/settings/email/test", methods=["POST"])
@login_required
def api_email_test():
    ok, msg = email.test_connection()
    return jsonify({"status": "ok" if ok else "error", "message": msg})


@app.route("/api/alert/email", methods=["POST"])
@login_required
def api_alert_email():
    data  = request.get_json(force=True) or {}
    count = data.get("count", cam.student_count)
    level = data.get("level", "warning")
    ok, msg = email.send_alert(count, level)
    return jsonify({"status": "ok" if ok else "error", "message": msg})


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_in"):
        return redirect(url_for("admin_panel"))
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["admin_in"] = True
            return redirect(url_for("admin_panel"))
        error = "❌ Invalid admin credentials."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_in", None)
    return redirect(url_for("admin_login"))


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin")
@admin_required
def admin_panel():
    return render_template("admin.html", active="admin")


@app.route("/api/admin/stats")
@admin_required
def api_admin_stats():
    return jsonify({
        "visitors":      db.get_total_visitors(),
        "captures":      db.get_total_captures(),
        "peak":          db.get_peak_count(),
        "avg":           db.get_avg_count(),
        "total_logs":    db.get_total_logs(),
        "total_alerts":  db.get_total_alerts(),
        "camera_stats":  db.get_camera_stats(),
        "hourly":        db.get_hourly_counts(24),
        "recent_logs":   db.get_recent_logs(30),
        "alert_history": db.get_alert_history(10),
        "today":         db.get_today_stats(),
        "yesterday":     db.get_yesterday_stats(),
        "alert_active":  alerts.is_active,
        "current_count": cam.student_count,
        "camera_online": cam.online,
        "camera_enabled":cam.enabled,
        "recording":     cam.recording,
        "behavior":      cam.behavior_label,
        "settings":      db.get_all_settings(),
        "generated":     time.strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/admin/report")
@admin_required
def api_admin_report():
    return jsonify(db.get_full_report())


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  🎓  AI Classroom Monitor v3 — STARTING")
    print("  📡  Dashboard  →  http://127.0.0.1:5000")
    print("  🔑  Password   →  12345")
    print("  🛡️   Admin      →  http://127.0.0.1:5000/admin/login")
    print("  🔑  Admin Pass →  admin123")
    print("  📊  Analytics  →  http://127.0.0.1:5000/analytics")
    print("  📋  Reports    →  http://127.0.0.1:5000/reports")
    print("  📝  Logs       →  http://127.0.0.1:5000/logs")
    print("  ⚙️   Settings   →  http://127.0.0.1:5000/settings")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
