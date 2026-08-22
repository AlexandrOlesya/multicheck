"""Панель независимых моделей: параллельный опрос через OpenRouter."""
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API_URL = os.environ.get("MC_API_URL", "https://openrouter.ai/api/v1/chat/completions")
DEFAULT_PANEL = [
    "deepseek/deepseek-chat-v3-0324",
    "google/gemini-2.0-flash-001",
    "qwen/qwen-2.5-coder-32b-instruct",
]
KEY_FILES = ["~/.config/multicheck/openrouter_key", "~/.openrouter_review_key"]
MAX_INPUT_CHARS = 120000


class MissingKey(RuntimeError):
    pass


def resolve_key(env=None, files=None):
    env = os.environ if env is None else env
    key = (env.get("OPENROUTER_API_KEY") or "").strip()
    if key:
        return key
    for path in files or KEY_FILES:
        expanded = os.path.expanduser(path)
        try:
            with open(expanded, encoding="utf-8", errors="replace") as handle:
                key = handle.read().strip()
        except OSError:
            continue
        if key:
            return key
    raise MissingKey(
        "нет ключа OpenRouter: задай OPENROUTER_API_KEY "
        f"или положи его в {KEY_FILES[0]}"
    )


def panel_models(env=None):
    env = os.environ if env is None else env
    raw = (env.get("MC_PANEL") or "").strip()
    if not raw:
        return list(DEFAULT_PANEL)
    return [m.strip() for m in raw.split(",") if m.strip()]


def ask(model, system, payload, key, retries=2, timeout=120, opener=None):
    opener = opener or urllib.request.urlopen
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": payload[:MAX_INPUT_CHARS]},
        ],
        "max_tokens": 1500,
        "temperature": 0.3,
        "reasoning": {"exclude": True},
    }).encode()

    for _ in range(retries + 1):
        request = urllib.request.Request(API_URL, data=body, method="POST")
        request.add_header("Authorization", "Bearer " + key)
        request.add_header("Content-Type", "application/json")
        try:
            raw = opener(request, timeout=timeout).read()
            choices = json.loads(raw).get("choices") or []
        except Exception:
            continue
        if not choices:
            continue
        content = (choices[0].get("message") or {}).get("content") or ""
        if content.strip():
            return content.strip()
    return None


def run(system, payload, models=None, key=None, opener=None):
    models = models or panel_models()
    key = key or resolve_key()
    with ThreadPoolExecutor(max_workers=max(1, len(models))) as pool:
        return list(pool.map(lambda m: (m, ask(m, system, payload, key, opener=opener)), models))


def render(results, marker="🔴", label="red-team"):
    lines = []
    answered = False
    for model, output in results:
        short = model.split("/")[-1]
        if output:
            answered = True
            lines.append(f"### {marker} {label}: {short}\n{output}\n")
        else:
            lines.append(f"### ⚪ {short} — не ответил (лимит или таймаут)\n")
    if not answered:
        lines.append("ПАНЕЛЬ НЕДОСТУПНА — ни одна модель не ответила.")
    return "\n".join(lines)


def read_payload(argv, stdin=None):
    stdin = sys.stdin if stdin is None else stdin
    if len(argv) > 1 and argv[1] not in ("-", "--stdin"):
        with open(argv[1], encoding="utf-8", errors="replace") as handle:
            return handle.read()
    return stdin.read()
