#!/usr/bin/env bash
# Runs the checks listed in scripts/ci_checks.txt. Linux-only ones are skipped (with a message) on macOS. Exits 1 if any check fails.
cd "$(dirname "$0")/.." || exit 1
export QT_QPA_PLATFORM=offscreen
os="$(uname -s)"
failed=0
while read -r name flag; do
  case "$name" in ''|'#'*) continue ;; esac
  if [ "$flag" = "linux" ] && [ "$os" != "Linux" ]; then
    echo "skip  $name (Linux only, skipped on $os)"
    continue
  fi
  if python "scripts/$name.py" > "/tmp/ci-$name.log" 2>&1; then
    echo "pass  $name"
  else
    echo "FAIL  $name"
    tail -n 25 "/tmp/ci-$name.log"
    failed=1
  fi
done < scripts/ci_checks.txt
exit $failed
