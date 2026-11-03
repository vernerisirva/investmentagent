#!/usr/bin/env bash
# Commit the staged files and push them to main and the scheduler branch.
# A staged file GitHub would reject stops the commit with a clear error instead of a
# rejected push; files above GitHub's recommended size are reported as warnings.
set -euo pipefail

message="$1"
warn_bytes=$((50 * 1024 * 1024))
limit_bytes=$((100 * 1024 * 1024))

oversized=0
while IFS= read -r -d '' path; do
  [ -f "$path" ] || continue
  size=$(wc -c < "$path" | tr -d '[:space:]')
  if [ "$size" -gt "$limit_bytes" ]; then
    echo "::error file=${path}::${path} is ${size} bytes; GitHub rejects files over 100 MiB."
    oversized=1
  elif [ "$size" -gt "$warn_bytes" ]; then
    echo "::warning file=${path}::${path} is ${size} bytes; above GitHub's 50 MiB recommendation."
  fi
done < <(git diff --cached --name-only -z)

if [ "$oversized" -ne 0 ]; then
  exit 1
fi
if git diff --cached --quiet; then
  echo "No changes to commit for: ${message}"
  exit 0
fi
git commit -m "$message"
git push origin HEAD:main
git push origin HEAD:codex/investmentagent-live-data
