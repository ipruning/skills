#!/usr/bin/env bash
set -euo pipefail

# Analyze an exported Amp thread for knowledge extraction.
# Usage: ./main.sh /tmp/T-xxx.md

THREAD_FILE="${1:-}"

if [[ -z "$THREAD_FILE" || ! -f "$THREAD_FILE" ]]; then
    echo "Error: Thread file not found: $THREAD_FILE" >&2
    echo "Usage: $0 <thread_file>" >&2
    echo "  First export: amp threads markdown T-xxx > /tmp/T-xxx.md" >&2
    exit 1
fi

echo "=== Thread Analysis: $THREAD_FILE ==="
echo ""

# 1. Basic stats
echo ">>> 1. Basic Stats"
TOTAL_LINES=$(wc -l < "$THREAD_FILE" | tr -d ' ')
USER_TURNS=$(grep -c "^## User" "$THREAD_FILE" || true)
ASSISTANT_TURNS=$(grep -c "^## Assistant" "$THREAD_FILE" || true)
TOOL_CALLS=$(grep -c "Tool Use:" "$THREAD_FILE" || true)
echo "  Lines: $TOTAL_LINES | User turns: $USER_TURNS | Assistant turns: $ASSISTANT_TURNS | Tool calls: $TOOL_CALLS"
echo ""

# 2. Failed tool calls (high-value signal)
echo ">>> 2. Failed Tool Calls (exitCode != 0)"
FAILED=$(rg -n '"exitCode": [^0]' "$THREAD_FILE" 2>/dev/null || true)
if [[ -n "$FAILED" ]]; then
    echo "$FAILED"
else
    echo "  (none)"
fi
echo ""

# 3. Errors in output
echo ">>> 3. Errors Found"
ERRORS=$(rg -n -i "error|failed|not found|no such file" "$THREAD_FILE" 2>/dev/null | head -20 || true)
if [[ -n "$ERRORS" ]]; then
    echo "$ERRORS"
    ERROR_COUNT=$(rg -c -i "error|failed|not found|no such file" "$THREAD_FILE" 2>/dev/null || echo "0")
    if [[ "$ERROR_COUNT" -gt 20 ]]; then
        echo "  ... ($ERROR_COUNT total, showing first 20)"
    fi
else
    echo "  (none)"
fi
echo ""

# 4. Human feedback (User messages that are NOT Tool Results)
echo ">>> 4. Human Feedback (non-Tool-Result user messages)"
awk '/^## User/{getline; getline; if(!/Tool Result/ && !/^\*\*Tool Result/) print NR": "$0}' "$THREAD_FILE" | head -20
echo ""

# 5. Skills loaded
echo ">>> 5. Skills Loaded"
SKILLS=$(rg -o 'name": "([^"]+)' --replace '$1' "$THREAD_FILE" 2>/dev/null | grep -v "tool" | sort -u || true)
if [[ -n "$SKILLS" ]]; then
    echo "$SKILLS"
else
    rg -o '<loaded_skill name="[^"]+"' "$THREAD_FILE" 2>/dev/null | sort -u || echo "  (none)"
fi
echo ""

echo "=== Analysis Complete ==="
echo "Next: Review findings above, identify patterns, update relevant skills/docs."
