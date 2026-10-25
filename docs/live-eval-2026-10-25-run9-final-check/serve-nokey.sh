#!/bin/bash
# serve.sh NAME PORT MOCKURL SIMULATOR(0|1) SMS(0|1)
cd /workspace/agrireach/eval-live
D=/tmp/apprun9/$1; rm -rf $D; mkdir -p $D
export DATABASE_URL=sqlite:///$D/t.db AGRIREACH_OUTBOX=$D/outbox AGRIREACH_MEDIA_DIR=$D/media AGRIREACH_CONSENT=0 \
  AGRIREACH_STT=none TOKEN_FILE=$D/token SMS_ENABLED=$5 AT_USERNAME=sandbox AT_API_KEY=mock-not-a-key \
  SMS_WEBHOOK_TOKEN=evalwebhooktoken-0123456789abcdef PYTHONUNBUFFERED=1 \
  \
  FETCH_MCP_ARGS=--allow-private-ips
[ "$4" = "1" ] && export AGRIREACH_SIMULATOR=1
exec env -u AGRIREACH_OPENROUTER_API_KEY -u LLM_API_KEY -u LLM_BASE_URL -u LLM_MODEL /workspace/agrireach/final/agrireach-fixes/.venv/bin/python /tmp/apprun9/serve.py $2 $3 > $D/server.log 2>&1
