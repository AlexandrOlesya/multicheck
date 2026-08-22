#!/bin/bash
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
python3 -m unittest discover -s tests -q || exit 1
bash tests/test_hook.sh || exit 1
echo "все тесты зелёные"
