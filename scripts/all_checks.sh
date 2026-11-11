#!/usr/bin/env bash
# Runs every scripts/*_check.py that needs no microphone and prints one line each.
cd "$(dirname "$0")/.." || exit 1
fail=0
for f in scripts/*_check.py; do
    name=$(basename "$f" .py)
    [ "$name" = "mic_check" ] && continue
    if timeout 180 python "$f" >/tmp/jarvis-$name.log 2>&1; then
        echo "pass  $name"
    else
        echo "FAIL  $name  (see /tmp/jarvis-$name.log)"
        fail=1
    fi
done
exit $fail
