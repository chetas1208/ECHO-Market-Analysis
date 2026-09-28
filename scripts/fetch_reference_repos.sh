#!/usr/bin/env bash
# Fetch read-only reference repositories into <repo-root>/.reference-repos/.
#
# These clones are for STUDY ONLY: they are gitignored, never vendored, never
# added as submodules, and never imported by ECHO code. See references/REPOS.md.
#
# Usage:
#   scripts/fetch_reference_repos.sh                 # clone all missing repos
#   scripts/fetch_reference_repos.sh alpaca-py lean  # clone only the named subset
#   scripts/fetch_reference_repos.sh --update        # also `git pull --ff-only` existing clones
#   scripts/fetch_reference_repos.sh --list          # print known names and exit
#
# This script is never invoked by application startup.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEST_ROOT="${REPO_ROOT}/.reference-repos"

# name|url|extra clone flags
REPOS=(
  "worldmonitor|https://github.com/koala73/worldmonitor|"
  "massive-client-python|https://github.com/massive-com/client-python|"
  "alpaca-py|https://github.com/alpacahq/alpaca-py|"
  "nautilus-trader|https://github.com/nautechsystems/nautilus_trader|--filter=blob:none"
  "lean|https://github.com/QuantConnect/Lean|--filter=blob:none"
  "ib-async|https://github.com/ib-api-reloaded/ib_async|"
  "ibind|https://github.com/Voyz/ibind|"
)

UPDATE=0
SELECTED=()

usage() { sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "$arg" in
    --update) UPDATE=1 ;;
    --list)
      for entry in "${REPOS[@]}"; do IFS='|' read -r n u _ <<<"$entry"; echo "$n  $u"; done
      exit 0 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; usage >&2; exit 2 ;;
    *) SELECTED+=("$arg") ;;
  esac
done

is_selected() {
  local name="$1"
  [ "${#SELECTED[@]}" -eq 0 ] && return 0
  local s
  for s in "${SELECTED[@]}"; do [ "$s" = "$name" ] && return 0; done
  return 1
}

# Validate requested names up front.
for s in ${SELECTED[@]+"${SELECTED[@]}"}; do
  found=0
  for entry in "${REPOS[@]}"; do IFS='|' read -r n _ _ <<<"$entry"; [ "$n" = "$s" ] && found=1; done
  if [ "$found" -eq 0 ]; then
    echo "unknown repo name: $s (try --list)" >&2
    exit 2
  fi
done

mkdir -p "${DEST_ROOT}"
failed=0

for entry in "${REPOS[@]}"; do
  IFS='|' read -r name url flags <<<"$entry"
  is_selected "$name" || continue
  dest="${DEST_ROOT}/${name}"

  if [ -d "${dest}/.git" ]; then
    if [ "$UPDATE" -eq 1 ]; then
      echo "[update] ${name}"
      git -C "${dest}" pull --ff-only || { echo "[warn] update failed for ${name}" >&2; failed=1; }
    else
      echo "[skip]   ${name} already present (use --update to refresh)"
    fi
  else
    echo "[clone]  ${name} <- ${url}"
    # shellcheck disable=SC2086
    if ! git clone --quiet --depth 1 --single-branch ${flags} "${url}" "${dest}"; then
      echo "[warn] clone failed for ${name}" >&2
      rm -rf "${dest}"
      failed=1
      continue
    fi
  fi
  echo "         $(git -C "${dest}" log -1 --format='%h %cs %s' 2>/dev/null || echo '?')"
done

exit "$failed"
