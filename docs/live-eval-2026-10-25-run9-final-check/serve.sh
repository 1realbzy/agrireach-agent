#!/bin/bash
# serve.sh NAME PORT MOCKURL SIMULATOR(0|1) SMS(0|1)
cd /workspace/agrireach/eval-live
D=/tmp/apprun9/$1; rm -rf $D; mkdir -p $D
export DATABASE_URL=sqlite:///$D/t.db AGRIREACH_OUTBOX=$D/outbox AGRIREACH_MEDIA_DIR=$D/media AGRIREACH_CONSENT=0 \
  AGRIREACH_STT=none TOKEN_FILE=$D/token SMS_ENABLED=$5 AT_USERNAME=sandbox AT_API_KEY=mock-not-a-key \
  SMS_WEBHOOK_TOKEN=evalwebhooktoken-0123456789abcdef PYTHONUNBUFFERED=1 \
  LLM_BASE_URL=https://openrouter.ai/api/v1 LLM_MODEL=mistralai/mistral-small-3.2-24b-instruct \
  AGRIREACH_JUDGE_MODEL=meta-llama/llama-3.3-70b-instruct FETCH_MCP_ARGS=--allow-private-ips
[ "$4" = "1" ] && export AGRIREACH_SIMULATOR=1
LLM_API_KEY="$AGRIREACH_OPENROUTER_API_KEY" exec /workspace/agrireach/final/agrireach-fixes/.venv/bin/python /tmp/apprun9/serve.py $2 $3 > $D/server.log 2>&1
