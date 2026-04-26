"""
alert_manager.py — AI Classroom Monitor v3
============================================
Upgraded: history tracking, sound/popup flags, cooldown.
"""
import time


class AlertManager:

    COOLDOWN_SEC = 120   # 2 min between DB writes

    def __init__(self, threshold: int = 30):
        self.threshold    = threshold
        self._last_ts     = 0.0
        self._active      = False
        self._last_count  = 0
        self._db          = None    # injected after init

    def set_db(self, db):
        """Inject database after construction (avoids circular import)."""
        self._db = db

    def update_threshold(self, t: int):
        self.threshold = t

    def check(self, total: int, alerts_enabled: bool = True) -> dict | None:
        """Returns alert dict or None."""
        if not alerts_enabled:
            self._active = False
            return None

        if total > self.threshold:
            self._active      = True
            self._last_count  = total
            now               = time.time()
            level             = "critical" if total > self.threshold * 1.5 else "warning"
            msg               = (f"Overcrowding: {total} students detected "
                                 f"(limit: {self.threshold})")

            # Log to DB (throttled)
            if self._db and now - self._last_ts >= self.COOLDOWN_SEC:
                self._db.log_alert(level, msg, total)
                self._last_ts = now

            return {
                "level":   level,
                "message": f"⚠️ {msg}",
                "count":   total,
                "sound":   True,    # JS will play beep
                "popup":   True,    # JS will show popup
            }

        self._active = False
        return None

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def last_count(self) -> int:
        return self._last_count
