#!/bin/bash
# Проверка хука и установщика без сети: панель подменяется заглушкой.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0

check() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  ok   $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL $name - ждали [$expected], получили [$actual]"
    FAIL=$((FAIL + 1))
  fi
}

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

git init -q "$SANDBOX/repo"
cd "$SANDBOX/repo"
git config user.email t@t; git config user.name t
echo "первая строка" > file.py
git add file.py && git commit -qm init

echo "хук:"

MC_SKIP=1 "$ROOT/bin/mc-hook" </dev/null >/dev/null 2>&1
check "MC_SKIP пропускает прогон" "0" "$?"

"$ROOT/bin/mc-hook" </dev/null >/dev/null 2>&1
check "без upstream и без дифа выходит чисто" "0" "$?"

printf 'x %s y %s\n' "$(git rev-parse HEAD)" "0000000000000000000000000000000000000000" \
  | MC_MIN_LINES=99999 "$ROOT/bin/mc-hook" >/dev/null 2>&1
check "тривиальный диф не тратит прогон" "0" "$?"

git checkout -qb feature
printf 'вторая строка\nтретья\n' >> file.py
git commit -qam "вторая правка"
printf 'x %s y %s\n' "$(git rev-parse HEAD)" "0000000000000000000000000000000000000000" \
  | MC_MIN_LINES=1 MC_PANEL="" OPENROUTER_API_KEY="" "$ROOT/bin/mc-hook" >/dev/null 2>&1
check "новая ветка без базы не падает" "0" "$?"

git init -q --bare "$SANDBOX/origin"
git remote add origin "$SANDBOX/origin"
git push -q origin feature 2>/dev/null
git checkout -qb trunk
printf 'четвёртая\nпятая\nшестая\n' >> file.py
git commit -qam "первый непушенный"
printf 'седьмая\n' >> file.py
git commit -qam "второй непушенный"
RANGE_DIFF=$(printf 'x %s y %s\n' "$(git rev-parse HEAD)" "0000000000000000000000000000000000000000" \
  | MC_MIN_LINES=1 MC_PANEL="" OPENROUTER_API_KEY="" "$ROOT/bin/mc-hook" 2>&1 \
  | grep -c "проверка пушимого дифа")
check "ветка с нестандартным именем даёт диапазон" "1" "$RANGE_DIFF"

printf 'строка\n%.0s' {1..50} >> file.py
git commit -qam "большой диф"
OUT=$(printf 'x %s y %s\n' "$(git rev-parse HEAD)" "0000000000000000000000000000000000000000" \
  | MC_MIN_LINES=1 MC_MAX_LINES=5 OPENROUTER_API_KEY="" "$ROOT/bin/mc-hook" 2>&1)
check "слишком большой диф не тратит бюджет" "1" "$(printf '%s' "$OUT" | grep -c 'больше порога')"

echo "установщик:"

"$ROOT/bin/mc-install-hook" "$SANDBOX/repo" >/dev/null 2>&1
check "ставится в репозиторий" "0" "$?"
check "хук исполняемый" "yes" "$([[ -x .git/hooks/pre-push ]] && echo yes || echo no)"
check "хук не попадает в индекс" "" "$(git status --porcelain)"
check "уступает lefthook" "yes" "$(grep -q 'lefthook run pre-push' .git/hooks/pre-push && echo yes || echo no)"

"$ROOT/bin/mc-install-hook" "$SANDBOX/repo" >/dev/null 2>&1
check "повторная установка не ломает" "0" "$?"

echo '#!/bin/bash' > .git/hooks/pre-push
echo 'echo чужой хук' >> .git/hooks/pre-push
"$ROOT/bin/mc-install-hook" "$SANDBOX/repo" >/dev/null 2>&1
check "чужой pre-push не затирается" "чужой хук" "$(grep -o 'чужой хук' .git/hooks/pre-push | head -1)"

"$ROOT/bin/mc-install-hook" "$SANDBOX/not-a-repo" >/dev/null 2>&1
check "не git-репозиторий отвергается" "1" "$?"

echo
echo "итого: $PASS ok, $FAIL fail"
[[ "$FAIL" -eq 0 ]]
