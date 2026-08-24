"""Точка входа для трёх режимов: mc-review, mc-refute, mc-grill."""
import os
import subprocess
import sys

from . import context, panel, prompts, verify

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


def context_wanted(env=None):
    """Контекст файлов кратно увеличивает запрос и цену прогона. В хуке на пуше
    он выключен: там нужна быстрая дешёвая проверка. Глубокий разбор — когда
    человек запускает сам."""
    env = os.environ if env is None else env
    return (env.get("MC_NO_CONTEXT") or "").strip() != "1"


def context_root(argv=None, env=None):
    """Откуда брать содержимое изменённых файлов: --repo, MC_REPO или текущая
    директория, если это git-репозиторий."""
    argv = sys.argv if argv is None else argv
    env = os.environ if env is None else env
    if "--repo" in argv:
        index = argv.index("--repo")
        if index + 1 < len(argv):
            return os.path.expanduser(argv[index + 1])
    from_env = (env.get("MC_REPO") or "").strip()
    if from_env:
        return os.path.expanduser(from_env)
    cwd = os.getcwd()
    return cwd if os.path.isdir(os.path.join(cwd, ".git")) else ""


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

    if mode == "review" and context_wanted():
        payload = context.with_context(payload, context.collect(payload, context_root(argv)))
    payload = with_static(payload, static_findings())

    dump = (os.environ.get("MC_DUMP_PAYLOAD") or "").strip()
    if dump:
        try:
            with open(os.path.expanduser(dump), "w", encoding="utf-8") as handle:
                handle.write(system + "\n\n===== PAYLOAD =====\n" + payload)
        except OSError:
            pass

    if "--finder" in argv and argv[argv.index("--finder") + 1:argv.index("--finder") + 2] == ["cursor"]:
        found = run_cursor(payload)
        spent = 0.0
    else:
        results = panel.run(system, payload, models=models_for(mode), key=key, opener=opener)
        found = panel.render(results, marker=marker, label=label)
        spent = sum(float(r[2]) for r in results if len(r) > 2)

    if "--verify" in argv:
        code = context.collect(payload, context_root(argv)) or payload
        found, _ = verify.annotate(found, code, key=key, opener=opener)
        if "--confirmed-only" in argv:
            found = verify.confirmed_only(found)

    print(found)
    if spent:
        print(f"— прогон стоил ${spent:.4f} —")
    return 0


def run_cursor(payload):
    binary = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "mc-cursor")
    try:
        done = subprocess.run([binary, "-"], input=payload, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"### ⚪ Cursor недоступен: {exc}"
    return done.stdout.strip()
