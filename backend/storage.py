"""Single-process SQLite store with owner scoping, expiry and atomic budget reservation."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date

class Store:
    def __init__(self,path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('CREATE TABLE IF NOT EXISTS resources (id TEXT PRIMARY KEY,kind TEXT,owner TEXT,expires REAL,payload TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS budget (day TEXT PRIMARY KEY,tokens INTEGER)')
        self.db.commit()
        # No resumed network call on restart: running tasks require an explicit new review.
        for row in self.db.execute("SELECT id,payload FROM resources WHERE kind='review'").fetchall():
            obj=json.loads(row[1])
            if obj['status'] in ['pending','running']:
                obj['status']='failed';obj['failure_code']='interrupted';self.save(row[0],obj)

    @contextmanager
    def atomic(self):
        with self.lock:
            try:yield;self.db.commit()
            except BaseException:self.db.rollback();raise

    def cleanup(self):
        with self.atomic():self.db.execute('DELETE FROM resources WHERE expires <= ?', (time.time(),))
        with self.lock:self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def put(self,id,kind,owner,obj,expires):
        with self.atomic():self.db.execute('INSERT INTO resources VALUES (?,?,?,?,?)',(id,kind,owner,expires,json.dumps(obj,ensure_ascii=False)))

    def get(self,id,kind,owner):
        row=self.db.execute('SELECT payload,expires FROM resources WHERE id=? AND kind=? AND owner=?',(id,kind,owner)).fetchone()
        if not row:return None
        if row[1]<=time.time():return None
        return json.loads(row[0])

    def save(self,id,obj):
        with self.atomic():return self.db.execute('UPDATE resources SET payload=? WHERE id=? AND expires>?',(json.dumps(obj,ensure_ascii=False),id,time.time())).rowcount

    def list(self,kind,owner):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM resources WHERE kind=? AND owner=? AND expires>? ORDER BY expires DESC LIMIT 100',(kind,owner,time.time()))]

    def delete(self,id,owner):
        with self.atomic():self.db.execute('DELETE FROM resources WHERE id=? AND owner=?',(id,owner))
        with self.lock:self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def reserve(self,tokens,limit):
        with self.atomic():
            day=date.today().isoformat();self.db.execute('INSERT OR IGNORE INTO budget VALUES (?,0)',(day,))
            used=self.db.execute('SELECT tokens FROM budget WHERE day=?',(day,)).fetchone()[0]
            if used+tokens>limit:return False
            self.db.execute('UPDATE budget SET tokens=tokens+? WHERE day=?',(tokens,day));return True
