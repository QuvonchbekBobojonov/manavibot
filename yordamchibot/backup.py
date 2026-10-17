"""Online SQLite backup; run with python -m yordamchibot.backup."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def backup(db_path):
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError('Database does not exist')
    folder = path.parent / 'backups'
    folder.mkdir(exist_ok=True)
    target = folder / (datetime.now(timezone.utc).strftime('backup-%Y%m%dT%H%M%S%f.db'))
    source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    temporary = target.with_suffix('.tmp')
    dest = sqlite3.connect(temporary)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    temporary.replace(target)
    for old in sorted(folder.glob('backup-*.db'), reverse=True)[7:]:
        old.unlink()
    return target


if __name__ == '__main__':
    backup(os.environ.get('DB_PATH', '/var/lib/yordamchibot/bot.db'))
