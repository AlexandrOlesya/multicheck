"""Контекст вокруг дифа: содержимое изменённых файлов.

Половина настоящих дефектов не видна в самих хунках — нужно знать, что за класс
рядом, какие импорты, как метод вызывается. Без этого панель обсуждает синтаксис,
а не поведение.
"""
import os
import re

FILE_LINE = re.compile(r"^\+\+\+ b/(.+)$", re.M)
MAX_FILE_CHARS = 24000
MAX_TOTAL_CHARS = 90000


def changed_files(diff):
    seen = []
    for path in FILE_LINE.findall(diff or ""):
        path = path.strip()
        if path and path != "/dev/null" and path not in seen:
            seen.append(path)
    return seen


def read_file(root, path, limit=MAX_FILE_CHARS):
    full = os.path.join(root, path)
    if not os.path.isfile(full):
        return None
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            text = handle.read(limit + 1)
    except OSError:
        return None
    if len(text) > limit:
        text = text[:limit] + "\n… (файл обрезан)"
    return text


def collect(diff, root, budget=MAX_TOTAL_CHARS):
    """Возвращает текст с содержимым изменённых файлов, сколько влезло в бюджет."""
    if not root or not os.path.isdir(root):
        return ""
    blocks = []
    spent = 0
    for path in changed_files(diff):
        text = read_file(root, path)
        if text is None:
            continue
        block = f"--- FILE: {path} ---\n{text}\n"
        if spent + len(block) > budget:
            blocks.append(f"--- (остальные файлы не поместились в бюджет контекста) ---\n")
            break
        blocks.append(block)
        spent += len(block)
    return "".join(blocks)


def with_context(payload, context):
    context = (context or "").strip()
    if not context:
        return payload
    return (
        "Full content of the files touched by this diff is given first, so you can "
        "reason about behaviour, not just about the changed lines. Use it to spot "
        "references to things that do not exist, broken invariants, and callers that "
        "the change breaks.\n\n"
        "=== FILES ===\n" + context + "\n=== DIFF ===\n" + payload
    )
