#!/usr/bin/env bash
# Updates GuildFM on the office machine: the latest code, its dependencies and the front end,
# a backup in case the update changes the database, then a restart. Run it as the guildfm user
# from the checkout. Restarting asks for sudo.
set -euo pipefail
cd "$(dirname "$0")/.."
# uv's installer puts it here, which only login shells have on their PATH.
export PATH="$HOME/.local/bin:$PATH"

git pull --ff-only
uv sync --no-dev --frozen
(cd web && npm ci && npm run build)
.venv/bin/guildfm backup
sudo systemctl restart guildfm
echo "GuildFM is updated and restarting."
