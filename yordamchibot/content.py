from aiogram import types


def extract(message):
    if message.text is not None:
        return dict(kind='text', text=message.text,
                    entities=[e.model_dump(exclude_none=True) for e in message.entities or []])
    for kind in ('photo', 'video', 'document'):
        media = getattr(message, kind, None)
        if media:
            if kind == 'photo':
                media = media[-1]
            return dict(kind=kind, file_id=media.file_id, caption=message.caption or '',
                        caption_entities=[e.model_dump(exclude_none=True) for e in message.caption_entities or []])
    return None


def inline_result(item):
    p = item['payload']
    common = dict(id=str(item['id']), title=item['title'])
    if p['kind'] == 'text':
        return types.InlineQueryResultArticle(**common, description=p['text'][:100],
            input_message_content=types.InputTextMessageContent(message_text=p['text'], entities=p.get('entities', [])))
    cls = {'photo': types.InlineQueryResultCachedPhoto, 'video': types.InlineQueryResultCachedVideo,
           'document': types.InlineQueryResultCachedDocument}[p['kind']]
    return cls(**common, **{p['kind'] + '_file_id': p['file_id']},
               caption=p.get('caption', ''), caption_entities=p.get('caption_entities', []))


async def preview(message, item, markup):
    p = item['payload']
    if p['kind'] == 'text':
        await message.answer(p['text'], entities=p.get('entities', []), reply_markup=markup)
    else:
        await getattr(message, 'answer_' + p['kind'])(p['file_id'], caption=p.get('caption', ''),
            caption_entities=p.get('caption_entities', []), reply_markup=markup)
