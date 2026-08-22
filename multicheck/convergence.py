"""Правило остановки цикла: идеал, зацикливание или бэкстоп.

Цикл ломает код, чинит и повторяет. Без правила остановки он молотит впустую,
когда находки перестают меняться — а именно это и происходит, когда дефект
требует редизайна, а не правки.
"""

IDEAL = "ideal"
LOOPING = "looping"
BACKSTOP = "backstop"
CONTINUE = "continue"

MAX_ROUNDS = 5


def signature(findings):
    """Отпечаток раунда: множество (файл, суть) без учёта порядка и регистра."""
    return frozenset(
        (str(f.get("file", "")).strip().lower(), str(f.get("issue", "")).strip().lower())
        for f in findings
    )


def decide(history, findings, max_rounds=MAX_ROUNDS):
    """history — сигнатуры прошлых раундов, findings — подтверждённые сейчас."""
    if not findings:
        return IDEAL, "подтверждённых дефектов нет"

    current = signature(findings)
    if current in history:
        return LOOPING, "тот же набор находок уже был — нужен редизайн, а не правка"
    if history and len(findings) >= len(history[-1]):
        return LOOPING, "число подтверждённых не уменьшилось после фикса"
    if len(history) + 1 >= max_rounds:
        return BACKSTOP, f"исчерпан лимит в {max_rounds} раундов"
    return CONTINUE, "находки убывают — чиним дальше"
