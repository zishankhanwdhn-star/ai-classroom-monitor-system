"""
database.py — AI Classroom Monitor v3
======================================
Upgraded SQLite layer with:
- Settings storage
- Alert history
- Email config
- Advanced filtering & search
- Auto-delete old data
- CSV export
- Today vs yesterday comparison
Python 3.11 compatible.
"""

import sqlite3
import time
import csv
import io
import os
from contextlib import contextmanager


DB_PATH = "classroom.db"


class Database:

    def __init__(self):
        self._init_schema()
        self._auto_delete_old_data()   # Clean >1 day old on startup

    # ── Connection ────────────────────────────────────────────────────────────
    @contextmanager
    def _conn(self):
        con = sqlite3.connect(DB_PATH, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # ── Schema ────────────────────────────────────────────────────────────────
    def _init_schema(self):
        with self._conn() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS count_logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id  INTEGER NOT NULL DEFAULT 0,
                    count      INTEGER NOT NULL DEFAULT 0,
                    timestamp  REAL    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS captures (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id    INTEGER NOT NULL DEFAULT 0,
                    filepath     TEXT    NOT NULL,
                    count        INTEGER NOT NULL DEFAULT 0,
                    capture_type TEXT    NOT NULL DEFAULT 'manual',
                    timestamp    REAL    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS visitors (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alert_history (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    level     TEXT NOT NULL,
                    message   TEXT NOT NULL,
                    count     INTEGER NOT NULL DEFAULT 0,
                    timestamp REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_logs_ts  ON count_logs(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_cap_ts   ON captures(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_alert_ts ON alert_history(timestamp DESC);
            """)

        # Insert default settings if not present
        defaults = {
            "overcrowd_limit":    "30",
            "auto_capture":       "1",
            "alerts_enabled":     "1",
            "auto_refresh":       "1",
            "email_enabled":      "0",
            "email_address":      "",
            "email_smtp":         "smtp.gmail.com",
            "email_port":         "587",
            "email_user":         "",
            "email_pass":         "",
            "auto_delete_days":   "1",
        }
        with self._conn() as con:
            for k, v in defaults.items():
                con.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)",
                    (k, v)
                )

    # ── Settings ──────────────────────────────────────────────────────────────
    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as con:
            r = con.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
        return r["value"] if r else default

    def set_setting(self, key: str, value: str):
        with self._conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                (key, value)
            )

    def get_all_settings(self) -> dict:
        with self._conn() as con:
            rows = con.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ── Count Logs ────────────────────────────────────────────────────────────
    def log_count(self, camera_id: int, count: int):
        with self._conn() as con:
            con.execute(
                "INSERT INTO count_logs (camera_id, count, timestamp) VALUES (?,?,?)",
                (camera_id, count, time.time())
            )

    def get_recent_logs(self, limit: int = 25, camera_id: int = None,
                        search: str = None, date_filter: str = None) -> list:
        sql  = "SELECT camera_id, count, timestamp FROM count_logs WHERE 1=1"
        args = []
        if camera_id is not None:
            sql += " AND camera_id=?"; args.append(camera_id)
        if date_filter:
            # date_filter = "YYYY-MM-DD"
            day_start = time.mktime(time.strptime(date_filter, "%Y-%m-%d"))
            day_end   = day_start + 86400
            sql += " AND timestamp>=? AND timestamp<?"; args += [day_start, day_end]
        if search:
            try:
                n = int(search)
                sql += " AND count=?"; args.append(n)
            except ValueError:
                pass

        sql += " ORDER BY timestamp DESC LIMIT ?"; args.append(limit)

        with self._conn() as con:
            rows = con.execute(sql, args).fetchall()
        return [
            {
                "id":     r["id"] if "id" in r.keys() else 0,
                "camera": r["camera_id"] + 1,
                "count":  r["count"],
                "time":   time.strftime("%H:%M:%S", time.localtime(r["timestamp"])),
                "date":   time.strftime("%Y-%m-%d", time.localtime(r["timestamp"])),
                "ts":     r["timestamp"],
            }
            for r in rows
        ]

    def get_all_logs_raw(self, camera_id=None, date_filter=None) -> list:
        """For CSV/JSON export — returns all matching records."""
        return self.get_recent_logs(limit=10000, camera_id=camera_id,
                                    date_filter=date_filter)

    def clear_all_logs(self):
        with self._conn() as con:
            con.execute("DELETE FROM count_logs")
            con.execute("DELETE FROM alert_history")

    # ── Captures ──────────────────────────────────────────────────────────────
    def log_capture(self, camera_id: int, filepath: str,
                    count: int, ctype: str = "manual"):
        with self._conn() as con:
            con.execute(
                """INSERT INTO captures (camera_id,filepath,count,capture_type,timestamp)
                   VALUES (?,?,?,?,?)""",
                (camera_id, filepath, count, ctype, time.time())
            )

    def get_total_captures(self) -> int:
        with self._conn() as con:
            r = con.execute("SELECT COUNT(*) AS n FROM captures").fetchone()
        return r["n"] if r else 0

    # ── Visitors ──────────────────────────────────────────────────────────────
    def log_visitor(self):
        with self._conn() as con:
            con.execute("INSERT INTO visitors (timestamp) VALUES (?)", (time.time(),))

    def get_total_visitors(self) -> int:
        with self._conn() as con:
            r = con.execute("SELECT COUNT(*) AS n FROM visitors").fetchone()
        return r["n"] if r else 0

    # ── Alert History ─────────────────────────────────────────────────────────
    def log_alert(self, level: str, message: str, count: int):
        with self._conn() as con:
            con.execute(
                "INSERT INTO alert_history (level,message,count,timestamp) VALUES (?,?,?,?)",
                (level, message, count, time.time())
            )

    def get_alert_history(self, limit: int = 30) -> list:
        with self._conn() as con:
            rows = con.execute(
                "SELECT level,message,count,timestamp FROM alert_history ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [
            {
                "level":   r["level"],
                "message": r["message"],
                "count":   r["count"],
                "time":    time.strftime("%H:%M:%S", time.localtime(r["timestamp"])),
                "date":    time.strftime("%Y-%m-%d", time.localtime(r["timestamp"])),
            }
            for r in rows
        ]

    def get_total_alerts(self) -> int:
        with self._conn() as con:
            r = con.execute("SELECT COUNT(*) AS n FROM alert_history").fetchone()
        return r["n"] if r else 0

    # ── Aggregates ────────────────────────────────────────────────────────────
    def get_peak_count(self) -> int:
        with self._conn() as con:
            r = con.execute("SELECT MAX(count) AS pk FROM count_logs").fetchone()
        return r["pk"] or 0

    def get_avg_count(self) -> float:
        with self._conn() as con:
            r = con.execute("SELECT AVG(count) AS av FROM count_logs").fetchone()
        return round(r["av"] or 0, 1)

    def get_total_logs(self) -> int:
        with self._conn() as con:
            r = con.execute("SELECT COUNT(*) AS n FROM count_logs").fetchone()
        return r["n"] if r else 0

    def get_today_stats(self) -> dict:
        """Today's peak, avg, total for comparison widget."""
        today = time.strftime("%Y-%m-%d")
        start = time.mktime(time.strptime(today, "%Y-%m-%d"))
        with self._conn() as con:
            r = con.execute(
                """SELECT COUNT(*) AS recs, AVG(count) AS avg, MAX(count) AS peak
                   FROM count_logs WHERE timestamp>=?""",
                (start,)
            ).fetchone()
        return {
            "records": r["recs"] or 0,
            "avg":     round(r["avg"] or 0, 1),
            "peak":    r["peak"] or 0,
        }

    def get_yesterday_stats(self) -> dict:
        """Yesterday's peak, avg, total."""
        today     = time.strftime("%Y-%m-%d")
        today_ts  = time.mktime(time.strptime(today, "%Y-%m-%d"))
        yest_ts   = today_ts - 86400
        with self._conn() as con:
            r = con.execute(
                """SELECT COUNT(*) AS recs, AVG(count) AS avg, MAX(count) AS peak
                   FROM count_logs WHERE timestamp>=? AND timestamp<?""",
                (yest_ts, today_ts)
            ).fetchone()
        return {
            "records": r["recs"] or 0,
            "avg":     round(r["avg"] or 0, 1),
            "peak":    r["peak"] or 0,
        }

    def get_hourly_counts(self, hours: int = 24) -> list:
        since = time.time() - hours * 3600
        with self._conn() as con:
            rows = con.execute(
                """SELECT
                       strftime('%H:00', datetime(timestamp,'unixepoch','localtime')) AS hour,
                       AVG(count) AS avg_count, MAX(count) AS max_count
                   FROM count_logs WHERE timestamp>?
                   GROUP BY hour ORDER BY hour""",
                (since,)
            ).fetchall()
        return [{"hour": r["hour"], "avg": round(r["avg_count"],1), "max": r["max_count"]}
                for r in rows]

    def get_camera_stats(self) -> list:
        with self._conn() as con:
            rows = con.execute(
                """SELECT camera_id, COUNT(*) AS records,
                          AVG(count) AS avg_count, MAX(count) AS max_count
                   FROM count_logs GROUP BY camera_id"""
            ).fetchall()
        return [
            {"camera": r["camera_id"]+1, "records": r["records"],
             "avg": round(r["avg_count"] or 0,1), "peak": r["max_count"] or 0}
            for r in rows
        ]

    # ── Auto-delete old data ──────────────────────────────────────────────────
    def _auto_delete_old_data(self):
        days = int(self.get_setting("auto_delete_days", "1"))
        cutoff = time.time() - days * 86400
        with self._conn() as con:
            con.execute("DELETE FROM count_logs  WHERE timestamp<?", (cutoff,))
            con.execute("DELETE FROM alert_history WHERE timestamp<?", (cutoff,))
        print(f"🧹  Auto-deleted records older than {days} day(s).")

    def manual_clear_logs(self):
        """Clear all count logs and alert history."""
        with self._conn() as con:
            con.execute("DELETE FROM count_logs")
            con.execute("DELETE FROM alert_history")

    # ── CSV export ────────────────────────────────────────────────────────────
    def export_csv(self, camera_id=None, date_filter=None) -> str:
        """Returns CSV string of filtered logs."""
        logs = self.get_all_logs_raw(camera_id=camera_id, date_filter=date_filter)
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["date", "time", "camera", "count"])
        writer.writeheader()
        for row in logs:
            writer.writerow({
                "date":   row["date"],
                "time":   row["time"],
                "camera": row["camera"],
                "count":  row["count"],
            })
        return output.getvalue()

    # ── Full report ───────────────────────────────────────────────────────────
    def get_full_report(self, camera_id=None, date_filter=None) -> dict:
        return {
            "generated":      time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_logs":     self.get_total_logs(),
            "total_captures": self.get_total_captures(),
            "total_visitors": self.get_total_visitors(),
            "total_alerts":   self.get_total_alerts(),
            "peak_count":     self.get_peak_count(),
            "avg_count":      self.get_avg_count(),
            "today":          self.get_today_stats(),
            "yesterday":      self.get_yesterday_stats(),
            "camera_stats":   self.get_camera_stats(),
            "hourly_24h":     self.get_hourly_counts(24),
            "recent_logs":    self.get_all_logs_raw(camera_id=camera_id,
                                                     date_filter=date_filter),
        }
