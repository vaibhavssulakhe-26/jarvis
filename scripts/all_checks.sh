#!/usr/bin/env bash
# Runs every scripts/*_check.py that needs no microphone and prints one line each.
# Each check gets its own empty data, runtime, state, workspace and outbox folders (a check that sets its own keeps them),
# and HANDCTL_DIR points nowhere so no check can start the real hologram viewer. Nothing is shared between checks.
cd "$(dirname "$0")/.." || exit 1
fail=0
for f in scripts/*_check.py; do
    name=$(basename "$f" .py)
    [ "$name" = "mic_check" ] && continue
    iso=$(mktemp -d "/tmp/jarvis-iso-$name.XXXXXX")
    mkdir -p -m 700 "$iso/run"
    extra=""
    [ "$name" = "core_check" ] && extra="--scratch"
    if JARVIS_DATA="$iso/data" XDG_RUNTIME_DIR="$iso/run" XDG_STATE_HOME="$iso/state" CODE_WORKSPACE="$iso/work" HANDOFF_DIR="$iso/outbox" \
       NOTES_DIR="$iso/notes" HANDCTL_DIR="$iso/no-handctl" JARVIS_PROFILE= \
       timeout 180 python "$f" $extra >/tmp/jarvis-$name.log 2>&1; then
        echo "pass  $name"
    else
        echo "FAIL  $name  (see /tmp/jarvis-$name.log)"
        fail=1
    fi
    rm -rf "$iso"
done
exit $fail
