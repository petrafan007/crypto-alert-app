#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root to install the dedicated strategy system unit." >&2
  exit 1
fi
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_GROUP="${QUANT_APP_GROUP:-jcavallarojr}"
if ! getent group "${APP_GROUP}" >/dev/null; then
  echo "App socket group ${APP_GROUP} does not exist." >&2
  exit 1
fi
if ! id crypto-quant >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin --gid "${APP_GROUP}" crypto-quant
fi
install -d -o root -g root -m 0755 /opt/crypto-quant-strategy /opt/crypto-quant-strategy/rules
install -o root -g root -m 0644 "${SOURCE_DIR}/server.py" /opt/crypto-quant-strategy/server.py
for module in equities options crypto events; do
  install -o root -g root -m 0644 "${SOURCE_DIR}/rules/${module}.py" "/opt/crypto-quant-strategy/rules/${module}.py"
done
install -o root -g root -m 0644 "${SOURCE_DIR}/crypto-quant-strategy.service" /etc/systemd/system/crypto-quant-strategy.service
systemctl daemon-reload
systemctl enable --now crypto-quant-strategy.service
systemctl restart crypto-quant-strategy.service
systemctl is-active --quiet crypto-quant-strategy.service
echo "Strategy source service is active; versioned state remains in /var/lib/crypto-quant-strategy."
