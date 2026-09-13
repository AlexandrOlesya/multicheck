"""Разметка находок дешёвой моделью. Ничего не удаляет.

Замер показал разделение труда: сильная модель находит больше настоящих дефектов,
но выдаёт вдвое больше мусора. Проверить находку против кода дешевле, чем найти её.

Но решение об удалении дешёвой модели не доверяется: она ошибается в обе стороны и
может тихо срезать настоящий дефект. Поэтому её дело — пометить и объяснить, а
выбрасывать или нет, решает оркестратор, у которого есть весь контекст задачи.
"""
import os
import re

from . import panel

VERIFIER = os.environ.get("MC_VERIFIER", "deepseek/deepseek-chat-v3-0324")

SYSTEM = (
    "You are a fact-checker for code review findings. You do NOT decide what to discard — "
    "you mark each finding so a human reviewer can decide fast.\n\n"
    "For every finding, output exactly one line:\n"
    "CONFIRMED | <finding> | <which code supports it>\n"
    "DOUBTFUL | <finding> | <what is missing to confirm>\n"
    "UNSUPPORTED | <finding> | <why the code does not support it>\n\n"
    "Mark UNSUPPORTED when the finding references a function, class, field or behaviour "
    "that is not in the code shown, or misreads what the code does. Mark DOUBTFUL when "
    "the code shown is not enough to tell. Keep the finding text intact. Output nothing else."
)

VERDICT = re.compile(r"^\s*(CONFIRMED|DOUBTFUL|UNSUPPORTED)\s*\|\s*(.+?)\s*\|\s*(.*)$", re.M)
MARKS = {"CONFIRMED": "✓ подтверждено", "DOUBTFUL": "? нужен контекст", "UNSUPPORTED": "✗ код не подтверждает"}


def annotate(findings, code, key=None, opener=None):
    """Возвращает (размеченный текст, счётчик по вердиктам). При сбое проверяющего —
    исходный текст без разметки: терять находки нельзя."""
    if not (findings or "").strip():
        return findings, {}

    payload = (
        "=== CODE ===\n" + (code or "(файлы не приложены)") +
        "\n=== FINDINGS TO CHECK ===\n" + findings
    )
    try:
        answer, _ = panel.ask(VERIFIER, SYSTEM, payload, key or panel.resolve_key(), opener=opener)
    except panel.MissingKey:
        return findings, {}
    if not answer:
        return findings, {}

    rows = VERDICT.findall(answer)
    if not rows:
        return findings, {}

    counts = {}
    lines = []
    for verdict, finding, reason in rows:
        counts[verdict] = counts.get(verdict, 0) + 1
        mark = MARKS.get(verdict, verdict)
        lines.append(f"[{mark}] {finding}" + (f"\n    почему: {reason}" if reason else ""))

    summary = ", ".join(f"{MARKS[v]}: {counts[v]}" for v in ("CONFIRMED", "DOUBTFUL", "UNSUPPORTED") if v in counts)
    lines.append(f"\n— разметка проверяющего ({summary}). Решение об отсеве за тобой: "
                 "сверь помеченное как не подтверждённое с кодом, прежде чем выбрасывать —")
    return "\n".join(lines), counts


def confirmed_only(annotated):
    """Подмножество подтверждённого — для замеров, не для показа человеку."""
    return "\n".join(
        line for line in (annotated or "").split("\n") if line.startswith(f"[{MARKS['CONFIRMED']}]")
    )
