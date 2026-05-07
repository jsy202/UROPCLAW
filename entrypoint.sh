#!/bin/sh
set -eu

required_vars="
OPENCLAW_MODEL
DISCORD_BOT_TOKEN_UROPCLAW1
DISCORD_BOT_TOKEN_UROPCLAW2
DISCORD_BOT_TOKEN_UROPCLAW3
DISCORD_BOT_TOKEN_UROPCLAW4
"

for var in $required_vars; do
  value=$(printenv "$var" || true)
  if [ -z "$value" ] || [ "$value" = "replace_me" ]; then
    echo "Missing required environment variable: $var" >&2
    exit 1
  fi
done

mkdir -p /data/.openclaw
mkdir -p /workspaces/uropclaw1 /workspaces/uropclaw2 /workspaces/uropclaw3 /workspaces/uropclaw4

if [ ! -f /data/.openclaw/openclaw.json ]; then
  sed "s|__OPENCLAW_MODEL__|${OPENCLAW_MODEL}|g" /app/openclaw.json > /data/.openclaw/openclaw.json
fi

exec openclaw gateway --port 18789 --verbose
