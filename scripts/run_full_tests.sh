#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DB_PORT="${POSTGRES_PORT:-5433}"
DB_HOST="${POSTGRES_HOST:-/var/run/postgresql}"
TEST_DB_NAME="cryptoalert_test_$(date +%s)_$$"

cleanup() {
    echo "Cleaning up test database: ${TEST_DB_NAME}..."
    dropdb -h "$DB_HOST" -p "$DB_PORT" "$TEST_DB_NAME" 2>/dev/null || true
}
trap cleanup EXIT

echo "Provisioning isolated test database ${TEST_DB_NAME} on port ${DB_PORT}..."
createdb -h "$DB_HOST" -p "$DB_PORT" "$TEST_DB_NAME"

export QUANT_TEST_DATABASE_URI="postgresql:///${TEST_DB_NAME}?host=${DB_HOST}&port=${DB_PORT}"
export QUANT_RISK_TEST_DATABASE_URI="$QUANT_TEST_DATABASE_URI"
export QUANT_LEGACY_TEST_DATABASE_URI="$QUANT_TEST_DATABASE_URI"
export QUANT_COMPLETION_TEST_DATABASE_URI="$QUANT_TEST_DATABASE_URI"
export QUANT_SEARCH_TEST_DATABASE_URI="$QUANT_TEST_DATABASE_URI"

PYTHON_BIN="${PYTHON_BIN:-}"
for candidate in ./venv/bin/python ./.venv/bin/python /var/www/html/csdapp/venv/bin/python; do
    if [ -z "$PYTHON_BIN" ] && [ -x "$candidate" ] && "$candidate" -c "import flask, sqlalchemy" 2>/dev/null; then
        PYTHON_BIN="$candidate"
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo "No Python environment with the app dependencies was found. Run: python3 -m venv venv && venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

echo "Running test suite with isolated PostgreSQL database configured..."
"$PYTHON_BIN" -m unittest discover -s tests "$@"
