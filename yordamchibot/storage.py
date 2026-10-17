import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.execute('''CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            payload TEXT NOT NULL, search_text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        self.db.commit()

    def add(self, title, payload):
        with self.db:
            cur = self.db.execute('INSERT INTO items(title,payload,search_text) VALUES(?,?,?)',
                                  (title, json.dumps(payload, ensure_ascii=False), self.index(title, payload)))
        return cur.lastrowid

    @staticmethod
    def index(title, payload):
        return (title + ' ' + payload.get('text', '') + ' ' + payload.get('caption', '')).casefold()

    @staticmethod
    def decode(row):
        return dict(row, payload=json.loads(row['payload'])) if row else None

    def get(self, item_id):
        return self.decode(self.db.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone())

    def search(self, query='', offset=0, limit=21):
        rows = self.db.execute('SELECT * FROM items WHERE instr(search_text,?)>0 ORDER BY id DESC LIMIT ? OFFSET ?',
                               (query.casefold().strip(), limit, offset)).fetchall()
        return [self.decode(row) for row in rows]

    def update(self, item_id, title=None, payload=None):
        item = self.get(item_id)
        if not item:
            return False
        title = title if title is not None else item['title']
        payload = payload if payload is not None else item['payload']
        with self.db:
            self.db.execute('UPDATE items SET title=?,payload=?,search_text=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                            (title, json.dumps(payload, ensure_ascii=False), self.index(title, payload), item_id))
        return True

    def delete(self, item_id):
        with self.db:
            self.db.execute('DELETE FROM items WHERE id=?', (item_id,))

    def close(self):
        self.db.close()
