#!/bin/bash
set -euo pipefail

: "${WORK_DIR:?WORK_DIR is required}"
: "${OUT:?OUT is required}"

RESULT="${WORK_DIR}/review-result.md"
LOG="${WORK_DIR}/oracle.log"

rm -f "$RESULT" "$LOG"

PROMPT="请完整通读所附文件，文件中同时包含 Review 指令和待审查的代码。通读完成后，执行指令。"

set +e
bunx @steipete/oracle --engine browser --force --wait --verbose \
  --write-output "$RESULT" \
  --prompt "$PROMPT" \
  --file "$OUT" 2>&1 | tee "$LOG"
BROWSER_CODE=${PIPESTATUS[0]}
set -e

if [ "$BROWSER_CODE" -ne 0 ] || [ ! -s "$RESULT" ]; then
  if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "Browser failed and OPENAI_API_KEY is missing; API fallback is disabled." | tee -a "$LOG"
    exit 1
  fi
  echo "Browser failed (code=$BROWSER_CODE); fallback to API model" | tee -a "$LOG"
  rm -f "$RESULT"
  bunx @steipete/oracle --engine api --model gpt-5.2-pro --force --wait --verbose \
    --write-output "$RESULT" \
    --prompt "$PROMPT" \
    --file "$OUT" 2>&1 | tee -a "$LOG"
fi
