"""SQLite checkpoint persistence for the candidate-observation stage."""
from contextlib import closing, contextmanager
import json
import sqlite3
import threading
import time


class ObservationStore:
    """Persist observations by scope, mode and date for a later analysis."""

    def __init__(self, path, scope, mode):
        self.path = path
        self.scope = scope
        self.mode = mode
        self.lock = threading.RLock()
        with self.db() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS ai_observations (
                    scope TEXT, mode TEXT, day TEXT, review_id TEXT, data TEXT,
                    PRIMARY KEY(scope, mode, day)
                )
            """)

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            with db:
                yield db

    def save_observations(self, day, checkpoint):
        with self.lock, self.db() as db:
            db.execute('INSERT OR REPLACE INTO ai_observations VALUES (?,?,?,?,?)',
                       (self.scope, self.mode, day, checkpoint['review_id'],
                        json.dumps(checkpoint, ensure_ascii=False, allow_nan=False)))

    def load_observations(self, day, reference_hash, max_age):
        with self.lock, self.db() as db:
            row = db.execute('SELECT data FROM ai_observations WHERE scope=? AND mode=? AND day=?',
                             (self.scope, self.mode, day)).fetchone()
        if row:
            checkpoint = json.loads(row[0])
            if checkpoint['reference_hash'] == reference_hash and 0 <= time.time() - checkpoint['created_at'] <= max_age:
                return checkpoint
        return None

    def consume_observations(self, day, review_id):
        """Remove only the checkpoint used by the completed decision."""
        with self.lock, self.db() as db:
            db.execute(
                'DELETE FROM ai_observations WHERE scope=? AND mode=? AND day=? AND review_id=?',
                (self.scope, self.mode, day, review_id),
            )
