import json
import sqlite3
import time
import uuid
from pathlib import Path

from .search import normalize, score

TRASH_SECONDS = 30 * 86400


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.execute('PRAGMA foreign_keys=ON')
        # Additive migration keeps original IDs, content and formatting intact.
        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                payload TEXT NOT NULL, search_text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            columns = {r['name'] for r in self.db.execute('PRAGMA table_info(items)')}
            for name, definition in {
                'uid': 'TEXT', 'category': "TEXT NOT NULL DEFAULT ''",
                'tags': "TEXT NOT NULL DEFAULT '[]'", 'favorite': 'INTEGER NOT NULL DEFAULT 0',
                'private': 'INTEGER NOT NULL DEFAULT 0', 'deleted_at': 'INTEGER',
            }.items():
                if name not in columns:
                    self.db.execute(f'ALTER TABLE items ADD COLUMN {name} {definition}')
            for row in self.db.execute('SELECT id FROM items WHERE uid IS NULL').fetchall():
                self.db.execute('UPDATE items SET uid=? WHERE id=?', (str(uuid.uuid4()), row['id']))
            self.db.execute('CREATE UNIQUE INDEX IF NOT EXISTS items_uid ON items(uid)')
            self.db.execute('''CREATE TABLE IF NOT EXISTS reminders (
                item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
                due_at INTEGER NOT NULL, next_attempt INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0)''')
        self.purge()

    @staticmethod
    def index(title, payload, category='', tags=()):
        return normalize(' '.join([title, payload.get('text', ''), payload.get('caption', ''), category, *tags]))

    @staticmethod
    def decode(row):
        return dict(row, payload=json.loads(row['payload']), tags=json.loads(row['tags'])) if row else None

    def add(self, title, payload, *, category='', tags=(), favorite=False, private=False):
        with self.db:
            cur = self.db.execute('''INSERT INTO items
                (uid,title,payload,search_text,category,tags,favorite,private) VALUES(?,?,?,?,?,?,?,?)''',
                (str(uuid.uuid4()), title, json.dumps(payload, ensure_ascii=False), self.index(title, payload, category, tags),
                 category, json.dumps(list(tags), ensure_ascii=False), int(favorite), int(private)))
        return cur.lastrowid

    def get(self, item_id, include_deleted=False):
        item = self.decode(self.db.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone())
        if item and item['deleted_at'] is not None:
            if item['deleted_at'] <= int(time.time()) - TRASH_SECONDS or not include_deleted:
                return None
        return item

    def search(self, query='', offset=0, limit=21, *, inline=False, favorites=False, trash=False, category=None):
        self.purge()
        where = ['deleted_at IS NOT NULL' if trash else 'deleted_at IS NULL']
        params = []
        if inline:
            where.append('private=0')
        if favorites:
            where.append('favorite=1')
        if category is not None:
            where.append('category=?')
            params.append(category)
        candidates = self.db.execute('SELECT * FROM items WHERE ' + ' AND '.join(where), params)
        query = normalize(query)
        matched = []
        for row in candidates:
            item = self.decode(row)
            rank = score(query, self.index(item['title'], item['payload'], item['category'], item['tags']))
            if rank:
                matched.append((item, rank))
        matched.sort(key=lambda pair: (pair[0]['favorite'], pair[1], pair[0]['id']), reverse=True)
        return [item for item, _ in matched[offset:offset + limit]]

    def update(self, item_id, title=None, payload=None, **metadata):
        item = self.get(item_id)
        if not item:
            return False
        item['title'] = title if title is not None else item['title']
        item['payload'] = payload if payload is not None else item['payload']
        for key in ('category', 'tags', 'favorite', 'private'):
            if key in metadata:
                item[key] = metadata[key]
        with self.db:
            self.db.execute('''UPDATE items SET title=?,payload=?,search_text=?,category=?,tags=?,
                favorite=?,private=?,updated_at=CURRENT_TIMESTAMP WHERE id=?''',
                (item['title'], json.dumps(item['payload'], ensure_ascii=False),
                 self.index(item['title'], item['payload'], item['category'], item['tags']), item['category'],
                 json.dumps(item['tags'], ensure_ascii=False), int(item['favorite']), int(item['private']), item_id))
        return True

    def delete(self, item_id):
        with self.db:
            self.db.execute('UPDATE items SET deleted_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND deleted_at IS NULL',
                            (int(time.time()), item_id))
            self.db.execute('DELETE FROM reminders WHERE item_id=?', (item_id,))

    def restore(self, item_id):
        self.purge()
        with self.db:
            return self.db.execute('UPDATE items SET deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL', (item_id,)).rowcount > 0

    def purge(self):
        with self.db:
            self.db.execute('DELETE FROM items WHERE deleted_at<=?', (int(time.time()) - TRASH_SECONDS,))

    def categories(self):
        return [dict(row) for row in self.db.execute('''SELECT category, COUNT(*) AS total, MIN(id) AS id
            FROM items WHERE deleted_at IS NULL AND category!='' GROUP BY category ORDER BY category''')]

    def stats(self):
        self.purge()
        result = dict(total=0, favorites=0, private=0, trash=0, types={}, reminders=0)
        for row in self.db.execute('SELECT payload,favorite,private,deleted_at FROM items'):
            if row['deleted_at'] is not None:
                result['trash'] += 1
                continue
            result['total'] += 1
            result['favorites'] += row['favorite']
            result['private'] += row['private']
            kind = json.loads(row['payload'])['kind']
            result['types'][kind] = result['types'].get(kind, 0) + 1
        result['reminders'] = self.db.execute('SELECT COUNT(*) FROM reminders').fetchone()[0]
        return result

    def set_reminder(self, item_id, due_at):
        if not self.get(item_id) or due_at <= time.time():
            raise ValueError('Kelajakdagi vaqtni tanlang.')
        with self.db:
            self.db.execute('''INSERT INTO reminders(item_id,due_at,next_attempt) VALUES(?,?,?)
                ON CONFLICT(item_id) DO UPDATE SET due_at=excluded.due_at,
                next_attempt=excluded.next_attempt,attempts=0''', (item_id, due_at, due_at))

    def reminders(self):
        return [dict(row) for row in self.db.execute('''SELECT r.*,i.title FROM reminders r
            JOIN items i ON i.id=r.item_id WHERE i.deleted_at IS NULL ORDER BY due_at,item_id''')]

    def cancel_reminder(self, item_id):
        with self.db:
            self.db.execute('DELETE FROM reminders WHERE item_id=?', (item_id,))

    def finish_reminder(self, item_id, due_at, retry_after=None):
        # A user may reschedule during a network request; never erase the new schedule.
        with self.db:
            if retry_after is None:
                self.db.execute('DELETE FROM reminders WHERE item_id=? AND due_at=?', (item_id, due_at))
            else:
                self.db.execute('''UPDATE reminders SET next_attempt=?,attempts=attempts+1
                    WHERE item_id=? AND due_at=?''', (int(time.time()) + retry_after, item_id, due_at))

    def export_items(self):
        self.purge()
        return [self.decode(row) for row in self.db.execute('SELECT * FROM items ORDER BY id')]

    def import_items(self, entries):
        added = 0
        with self.db:
            for item in entries:
                if self.db.execute('SELECT 1 FROM items WHERE uid=?', (item['uid'],)).fetchone():
                    continue
                self.db.execute('''INSERT INTO items(uid,title,payload,search_text,category,tags,favorite,
                    private,deleted_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (item['uid'], item['title'], json.dumps(item['payload'], ensure_ascii=False),
                     self.index(item['title'], item['payload'], item['category'], item['tags']), item['category'],
                     json.dumps(item['tags'], ensure_ascii=False), int(item['favorite']), int(item['private']),
                     item['deleted_at'], item['created_at'], item['updated_at']))
                added += 1
        return added

    def close(self):
        self.db.close()
