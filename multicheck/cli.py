"""Точка входа для трёх режимов: mc-review, mc-refute, mc-grill."""
import os
import sys

from . import panel, prompts

MAX_RULES_CHARS = 20000
MAX_STATIC_CHARS = 20000

MODES = {
    "review": (prompts.BREAK, "🔴", "red-team"),
    "refute": (prompts.REFUTE, "🟠", "скептик"),
    "grill": (prompts.GRILL, "⚡", "допрос"),
}


def project_rules(env=None):
    env = os.environ if env is None else env
    path = (env.get("MC_PROJECT_RULES") or "").strip()
    if not path:
        return ""
    try:
        with open(os.path.expanduser(path), encoding="utf-8", errors="replace") as handle:
            return handle.read(MAX_RULES_CHARS)
    except OSError:
        return ""


def static_findings(env=None):
    """Вывод линтеров/типизатора, если он есть. Панель получает его как
    «уже известно» — иначе модели переоткрывают то, что детерминированный
    анализ и так ловит, и топят настоящие находки в шуме."""
    env = os.environ if env is None else env
    path = (env.get("MC_STATIC") or "").strip()
    if not path:
        return ""
    try:
        with open(os.path.expanduser(path), encoding="utf-8", errors="replace") as handle:
            return handle.read(MAX_STATIC_CHARS).strip()
    except OSError:
        return ""


def with_static(payload, static):
    static = (static or "").strip()
    if not static:
        return payload
    return (
        "Static analysis has ALREADY reported the issues listed below. Do NOT repeat them. "
        "Look for what static analysis cannot see: wrong logic, races, data leaks, "
        "broken invariants, edge cases.\n\n"
        "=== ALREADY REPORTED ===\n" + static + "\n=== END ===\n\n" + payload
    )


def models_for(mode, env=None):
    env = os.environ if env is None else env
    models = panel.panel_models(env)
    if mode == "grill" and (env.get("GRILL_FAST") or "").strip() == "1":
        return models[:1]
    return models


def main(mode, argv=None, stdin=None, opener=None):
    argv = sys.argv if argv is None else argv
    system, marker, label = MODES[mode]
    system = prompts.with_project_rules(system, project_rules())

    payload = panel.read_payload(argv, stdin)
    if not payload.strip():
        print("пустой вход — нечего проверять")
        return 0

    try:
        key = panel.resolve_key()
    except panel.MissingKey as exc:
        print(exc, file=sys.stderr)
        return 2

    payload = with_static(payload, static_findings())

    results = panel.run(system, payload, models=models_for(mode), key=key, opener=opener)
    print(panel.render(results, marker=marker, label=label))
    return 0
