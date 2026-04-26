"""
email_service.py — AI Classroom Monitor v3
============================================
SMTP email notifications using smtplib (built-in, no extra install).
Gmail support with App Password.
"""

import smtplib
import time
from email.mime.text   import MIMEText
from email.mime.multipart import MIMEMultipart


class EmailService:

    def __init__(self, db):
        self.db = db

    def _get_config(self) -> dict:
        return {
            "enabled":  self.db.get_setting("email_enabled", "0") == "1",
            "to":       self.db.get_setting("email_address", ""),
            "smtp":     self.db.get_setting("email_smtp", "smtp.gmail.com"),
            "port":     int(self.db.get_setting("email_port", "587")),
            "user":     self.db.get_setting("email_user", ""),
            "password": self.db.get_setting("email_pass", ""),
        }

    def send_alert(self, count: int, level: str) -> tuple[bool, str]:
        """Send overcrowding alert email. Returns (success, message)."""
        cfg = self._get_config()

        if not cfg["enabled"]:
            return False, "Email notifications are disabled."
        if not cfg["to"] or not cfg["user"] or not cfg["password"]:
            return False, "Email settings incomplete. Check Settings page."

        subject = f"[AI Monitor] {'🚨 CRITICAL' if level == 'critical' else '⚠️ WARNING'} — Overcrowding Alert"
        ts      = time.strftime("%Y-%m-%d %H:%M:%S")

        body = f"""
AI Classroom Monitoring System — ALERT
=======================================
Time       : {ts}
Level      : {level.upper()}
Students   : {count}
Threshold  : {self.db.get_setting('overcrowd_limit', '30')}

This is an automated alert from your AI Classroom Monitor.
Please check the dashboard immediately.

Dashboard  : http://127.0.0.1:5000/dashboard
Admin Panel: http://127.0.0.1:5000/admin
"""

        try:
            msg = MIMEMultipart()
            msg["From"]    = cfg["user"]
            msg["To"]      = cfg["to"]
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(cfg["smtp"], cfg["port"], timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["user"], cfg["to"], msg.as_string())

            return True, f"Alert email sent to {cfg['to']}"

        except smtplib.SMTPAuthenticationError:
            return False, "Gmail auth failed. Use an App Password (not your Gmail password)."
        except smtplib.SMTPException as e:
            return False, f"SMTP error: {e}"
        except Exception as e:
            return False, f"Email error: {e}"

    def send_report(self, report_data: dict) -> tuple[bool, str]:
        """Send daily report email."""
        cfg = self._get_config()
        if not cfg["enabled"]:
            return False, "Email notifications are disabled."
        if not cfg["to"] or not cfg["user"] or not cfg["password"]:
            return False, "Email settings incomplete."

        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        body = f"""
AI Classroom Monitor — Daily Report
=====================================
Generated : {ts}
Total Logs: {report_data.get('total_logs', 0)}
Peak Count: {report_data.get('peak_count', 0)}
Avg Count : {report_data.get('avg_count', 0)}
Captures  : {report_data.get('total_captures', 0)}
Visitors  : {report_data.get('total_visitors', 0)}

Today     : Peak={report_data.get('today', {}).get('peak', 0)}, Avg={report_data.get('today', {}).get('avg', 0)}
Yesterday : Peak={report_data.get('yesterday', {}).get('peak', 0)}, Avg={report_data.get('yesterday', {}).get('avg', 0)}

Dashboard : http://127.0.0.1:5000/dashboard
"""
        try:
            msg            = MIMEMultipart()
            msg["From"]    = cfg["user"]
            msg["To"]      = cfg["to"]
            msg["Subject"] = f"[AI Monitor] Daily Report — {ts[:10]}"
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(cfg["smtp"], cfg["port"], timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["user"], cfg["to"], msg.as_string())

            return True, f"Report sent to {cfg['to']}"
        except Exception as e:
            return False, f"Email error: {e}"

    def test_connection(self) -> tuple[bool, str]:
        """Test SMTP credentials without sending a full email."""
        cfg = self._get_config()
        if not cfg["user"] or not cfg["password"]:
            return False, "Email user / password not set."
        try:
            with smtplib.SMTP(cfg["smtp"], cfg["port"], timeout=8) as server:
                server.ehlo()
                server.starttls()
                server.login(cfg["user"], cfg["password"])
            return True, "SMTP connection successful ✅"
        except smtplib.SMTPAuthenticationError:
            return False, "Authentication failed. Use Gmail App Password."
        except Exception as e:
            return False, f"Connection error: {e}"
