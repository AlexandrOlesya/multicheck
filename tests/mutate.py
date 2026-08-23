#!/usr/bin/env python3
"""Мутационное тестирование: ломает код по одной правке и смотрит, поймают ли тесты.

Покрытие говорит, что строка выполнилась. Мутационный балл говорит, что её
поведение кому-то важно. Выживший мутант — строка, которую можно испортить
незаметно для тестов.

  tests/mutate.py [файл ...]
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = ["multicheck/panel.py", "multicheck/cli.py", "multicheck/convergence.py"]

OPERATORS = [
    (r">=", "<"),
    (r"<=", ">"),
    (r"(?<![<>=!])==", "!="),
    (r"!=", "=="),
    (r"\bnot \b", ""),
    (r"\band\b", "or"),
    (r"\bor\b", "and"),
    (r"\bTrue\b", "False"),
    (r"\bFalse\b", "True"),
    (r"\breturn None\b", "return ''"),
    (r"\.strip\(\)", ""),
]

SKIP_LINE = re.compile(r'^\s*(#|"""|\'\'\')')


def run_tests():
    done = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    return done.returncode == 0


def mutants(path):
    lines = open(os.path.join(ROOT, path), encoding="utf-8").read().split("\n")
    for index, line in enumerate(lines):
        if SKIP_LINE.match(line) or not line.strip():
            continue
        for pattern, replacement in OPERATORS:
            if not re.search(pattern, line):
                continue
            mutated = list(lines)
            mutated[index] = re.sub(pattern, replacement, line, count=1)
            if mutated[index] == line:
                continue
            yield index + 1, line.strip(), mutated[index].strip(), "\n".join(mutated)


def main():
    targets = sys.argv[1:] or TARGETS
    if not run_tests():
        print("тесты и без мутаций красные — сначала почини их")
        return 1

    killed = survived = 0
    survivors = []
    for path in targets:
        full = os.path.join(ROOT, path)
        original = open(full, encoding="utf-8").read()
        try:
            for line_no, before, after, text in mutants(path):
                open(full, "w", encoding="utf-8").write(text)
                if run_tests():
                    survived += 1
                    survivors.append(f"{path}:{line_no}  {before}  →  {after}")
                else:
                    killed += 1
        finally:
            open(full, "w", encoding="utf-8").write(original)

    total = killed + survived
    if not total:
        print("мутантов не получилось — проверь операторы")
        return 1
    print(f"\nубито {killed} из {total} = {100 * killed / total:.0f}%")
    if survivors:
        print(f"\nвыжили ({len(survivors)}) — эти правки тесты не заметили:")
        for item in survivors:
            print("  " + item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
