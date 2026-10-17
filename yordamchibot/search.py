"""Uzbek Cyrillic/Latin matching, with conservative typo tolerance."""
import re
import unicodedata
from difflib import SequenceMatcher

CYRILLIC = dict(zip(
    'абвгдеёжзийклмнопрстуфхцчшщъыьэюяўғқҳ',
    ['a','b','v','g','d','e','yo','j','z','i','y','k','l','m','n','o','p','r','s','t','u',
     'f','x','ts','ch','sh','sh','','i','','e','yu','ya','o','g','q','h']))


def normalize(value):
    text = unicodedata.normalize('NFKC', value).casefold()
    text = ''.join(CYRILLIC.get(char, char) for char in text)
    text = re.sub("['‘’ʻʼ`ʹ]", '', text)
    return ' '.join(re.findall(r'\w+', text))


def score(query, document):
    if not query:
        return 1
    if query in document:
        return 3
    words = document.split()
    terms = query.split()
    if all(any(term in word for word in words) for term in terms):
        return 2
    def similar(term, word):
        return (len(term) >= 4 and abs(len(term) - len(word)) <= 2
                and SequenceMatcher(None, term, word).ratio() >= 0.78)
    if all(any(term in word or similar(term, word) for word in words) for term in terms):
        return 1
    return 0
