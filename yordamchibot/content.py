from aiogram import types

ICONS = {'text': '📝', 'photo': '🖼', 'video': '🎬', 'document': '📄',
         'voice': '🎤', 'audio': '🎵', 'animation': '🎞'}
LABELS = {'text': 'Matn', 'photo': 'Rasm', 'video': 'Video', 'document': 'Hujjat',
          'voice': 'Ovoz', 'audio': 'Audio', 'animation': 'GIF'}


def extract(message):
    if message.text is not None:
        return dict(kind='text', text=message.text,
                    entities=[e.model_dump(exclude_none=True) for e in message.entities or []])
    # Telegram animations may also contain document; animation must win.
    for kind in ('photo', 'video', 'voice', 'audio', 'animation', 'document'):
        media = getattr(message, kind, None)
        if media:
            if kind == 'photo':
                media = media[-1]
            return dict(kind=kind, file_id=media.file_id, caption=message.caption or '',
                        mime_type=getattr(media, 'mime_type', None),
                        caption_entities=[e.model_dump(exclude_none=True) for e in message.caption_entities or []])
    return None


def inline_result(item):
    if item.get('private') or item.get('deleted_at') is not None:
        raise ValueError('Private or deleted items cannot be shared')
    p = item['payload']
    common = dict(id=str(item['id']), title=item['title'])
    if p['kind'] == 'text':
        return types.InlineQueryResultArticle(**common, description=p['text'][:100],
            input_message_content=types.InputTextMessageContent(message_text=p['text'], entities=p.get('entities', [])))
    kind = p['kind']
    if kind == 'animation':
        kind = 'mpeg4' if p.get('mime_type') == 'video/mp4' else 'gif'
    cls = {'photo': types.InlineQueryResultCachedPhoto, 'video': types.InlineQueryResultCachedVideo,
           'document': types.InlineQueryResultCachedDocument, 'voice': types.InlineQueryResultCachedVoice,
           'audio': types.InlineQueryResultCachedAudio, 'gif': types.InlineQueryResultCachedGif,
           'mpeg4': types.InlineQueryResultCachedMpeg4Gif}[kind]
    if kind == 'audio':
        common.pop('title')  # Telegram displays the audio's own metadata.
    return cls(**common, **{kind + '_file_id': p['file_id']},
               caption=p.get('caption', ''), caption_entities=p.get('caption_entities', []))


async def preview(message, item, markup):
    p = item['payload']
    if p['kind'] == 'text':
        await message.answer(p['text'], entities=p.get('entities', []), reply_markup=markup)
    else:
        await getattr(message, 'answer_' + p['kind'])(p['file_id'], caption=p.get('caption', ''),
            caption_entities=p.get('caption_entities', []), reply_markup=markup)
