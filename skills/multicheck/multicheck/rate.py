"""Adversarial rating: severity назначает НЕ тот, кто нашёл.

Два независимых rater'а оценивают каждую находку по tier × precondition × radius,
скептик-supervisor консолидирует и выдаёт `severity · verdict · why`
(KEEP / HARDENING / DROP). Ловит раздутые находки, прошедшие verify."""
import os

from . import panel, prompts

# раторы — разные вендоры для независимости; supervisor — цепочка фолбэка,
# третий вендор впереди, чтобы не совпадать с раторами.
RATERS = ["deepseek/deepseek-chat-v3-0324", "qwen/qwen-2.5-coder-32b-instruct"]
SUPERVISORS = [
    # 2.0-flash снят с раздачи и отвечает 404 — линия молча выпадала, а свод читался
    # как «претензий нет»
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3-0324",
    "qwen/qwen-2.5-coder-32b-instruct",
]


def _raters(env=None):
    env = os.environ if env is None else env
    raw = (env.get("MC_RATERS") or "").strip()
    return [m.strip() for m in raw.split(",") if m.strip()] or list(RATERS)


def _supervisors(env=None):
    env = os.environ if env is None else env
    raw = (env.get("MC_SUPERVISOR") or "").strip()
    return [m.strip() for m in raw.split(",") if m.strip()] or list(SUPERVISORS)


def rate(findings, key=None, opener=None, raters=None, supervisors=None, sources=None):
    """sources — состав панели, который реально отработал («2 из 3, выпал: агент»).

    Передаётся фактом, а не выводится из находок: по ним не понять, промолчал источник
    или не запускался. Без этого supervisor считает прогон деградировавшим и не
    отбрасывает ничего — так безопаснее, чем молча потерять находку.
    """
    findings = (findings or "").strip()
    if not findings:
        return "нет находок для рейтинга"
    key = key or panel.resolve_key()
    raters = raters or _raters()
    supervisors = supervisors or _supervisors()

    positions = []
    results = panel.run(prompts.RATE, "Rate these findings:\n\n" + findings,
                        models=raters, key=key, opener=opener)
    for model, output, *_ in results:
        if output:
            positions.append(f"### rater {model.split('/')[-1]}\n{output}")
    if not positions:
        return "раторы недоступны — рейтинг пропущен, оцени находки вручную по tier × precondition × radius"

    header = ("SOURCES THAT RAN: " + sources.strip() + "\n\n") if (sources or "").strip() else (
        "SOURCES THAT RAN: not reported — treat the run as possibly degraded and drop nothing.\n\n")
    payload = (
        header + "FINDINGS:\n" + findings
        + "\n\nRATER POSITIONS:\n" + "\n\n".join(positions)
        + "\n\nConsolidate into the final rated list."
    )
    for sup in supervisors:
        final, _ = panel.ask(sup, prompts.SUPERVISE, payload, key, opener=opener)
        if final:
            return "### Рейтинг (adversarial: 2 rater + скептик-supervisor)\n\n" + final
    return ("### Рейтинг — supervisor недоступен, сырые позиции раторов:\n\n"
            + "\n\n".join(positions))


def main(argv=None, stdin=None):
    import sys
    argv = list(sys.argv if argv is None else argv)
    sources = None
    if "--sources" in argv:
        index = argv.index("--sources")
        sources = argv[index + 1] if index + 1 < len(argv) else ""
        del argv[index:index + 2]
    findings = panel.read_payload(argv, stdin=stdin)
    print(rate(findings, sources=sources))


if __name__ == "__main__":
    main()
