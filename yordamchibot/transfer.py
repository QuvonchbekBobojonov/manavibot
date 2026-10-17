"""Versioned JSON export/import; validation completes before any DB mutation."""
import json
import time
from datetime import datetime
from uuid import UUID

from aiogram.types import MessageEntity

MAX_BYTES = 10 * 1024 * 1024
MAX_ITEMS = 10000
KINDS = {'text', 'photo', 'video', 'document', 'voice', 'audio', 'animation'}


def export_data(store, bot_id):
    entries = store.export_items()
    if len(entries) > MAX_ITEMS:
        raise ValueError('Eksport uchun 10 000 ta yozuv chegarasi oshdi. SQLite zaxirasidan foydalaning.')
    data = json.dumps({'format': 'manavibot', 'version': 1, 'bot_id': bot_id, 'items': entries},
                      ensure_ascii=False).encode('utf-8')
    if len(data) > MAX_BYTES:
        raise ValueError('Eksport 10 MB dan oshdi. SQLite zaxirasidan foydalaning.')
    return data


def text_value(value, maximum, allow_empty=True):
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value.strip()):
        raise ValueError('Matn uzunligi yoki formati noto‘g‘ri.')
    return value


def entities(values, text):
    if not isinstance(values, list) or len(values) > 100:
        raise ValueError('Formatlash ma’lumoti noto‘g‘ri.')
    result = []
    size = len(text.encode('utf-16-le')) // 2
    for value in values:
        entity = MessageEntity.model_validate(value)
        if entity.offset < 0 or entity.length <= 0 or entity.offset + entity.length > size:
            raise ValueError('Formatlash chegarasi noto‘g‘ri.')
        result.append(entity.model_dump(exclude_none=True))
    return result


def validate_import(raw, bot_id):
    if len(raw) > MAX_BYTES:
        raise ValueError('Fayl 10 MB dan katta.')
    try:
        data = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(data, dict) or data.get('format') != 'manavibot' or data.get('version') != 1:
            raise ValueError('Manavibot eksport faylini yuboring.')
        if data.get('bot_id') != bot_id:
            raise ValueError('Fayl boshqa botniki. Telegram file_id faqat o‘z botida ishlaydi.')
        rows = data['items']
        if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
            raise ValueError('Yozuvlar soni noto‘g‘ri (eng ko‘pi 10 000).')
        validated = []
        seen = set()
        for row in rows:
            uid = str(UUID(row['uid']))
            if uid in seen:
                raise ValueError('Faylda takroriy yozuv identifikatori bor.')
            seen.add(uid)
            p = row['payload']
            kind = p['kind']
            if kind not in KINDS:
                raise ValueError('Qo‘llanmaydigan fayl turi.')
            payload = {'kind': kind}
            if kind == 'text':
                payload['text'] = text_value(p['text'], 4096, False)
                payload['entities'] = entities(p.get('entities', []), payload['text'])
            else:
                payload['file_id'] = text_value(p['file_id'], 1024, False)
                payload['caption'] = text_value(p.get('caption', ''), 1024)
                payload['caption_entities'] = entities(p.get('caption_entities', []), payload['caption'])
                mime = p.get('mime_type')
                payload['mime_type'] = text_value(mime, 100) if mime is not None else None
            tags = row.get('tags', [])
            if not isinstance(tags, list) or len(tags) > 10:
                raise ValueError('Eng ko‘pi 10 ta teg bo‘lsin.')
            tags = list(dict.fromkeys(text_value(tag, 30, False) for tag in tags))
            flags = [row.get('favorite', False), row.get('private', False)]
            if any(type(flag) not in (bool, int) or flag not in (0, 1) for flag in flags):
                raise ValueError('Maxfiylik yoki sevimli belgisi noto‘g‘ri.')
            deleted = row.get('deleted_at')
            if deleted is not None and (type(deleted) is not int or not 0 <= deleted <= time.time()):
                raise ValueError('Savat sanasi noto‘g‘ri.')
            dates = [text_value(row[k], 30, False) for k in ('created_at', 'updated_at')]
            for date in dates:
                datetime.fromisoformat(date)
            validated.append(dict(uid=uid, title=text_value(row['title'], 100, False), payload=payload,
                                  category=text_value(row.get('category', ''), 40), tags=tags,
                                  favorite=bool(flags[0]), private=bool(flags[1]), deleted_at=deleted,
                                  created_at=dates[0], updated_at=dates[1]))
        return validated
    except (KeyError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError('Eksport fayli tuzilishi noto‘g‘ri.') from exc
