#!/usr/bin/env bash
# Pre-registered held-out validation for RepoGraph.
#
# This script clones three repositories never used in development,
# applies the same file-selection rule (top-5 inbound + 5 random, seed=42),
# and collects raw repograph impact results.
#
# Run BEFORE reading benchmarks/compare/HELD_OUT_RESULTS.md.
# Do not adjust the repos, commits, or selection rule after running.
#
# Registration date: 2026-11-14
# Repos chosen before any queries were run on them.
# NOT previously indexed, sampled, or used to fix the resolver.

set -euo pipefail

WORKDIR="${1:-/tmp/opencode/held_out}"
REPOGRAPH_SRC="$(cd "$(dirname "$0")/../../.." && pwd)"
RAW_OUT="$REPOGRAPH_SRC/benchmarks/compare/raw/held_out"

mkdir -p "$WORKDIR" "$RAW_OUT"

echo "=== Cloning held-out repos ==="

# Repos and pinned SHAs (selected 2026-11-14, never used in development)
declare -A REPOS=(
  ["babel"]="https://github.com/babel/babel.git"
  ["boto3"]="https://github.com/boto/boto3.git"
  ["expressjs_router"]="https://github.com/expressjs/router.git"
)

declare -A SHAS  # filled after clone

for name in "${!REPOS[@]}"; do
  url="${REPOS[$name]}"
  dest="$WORKDIR/$name"
  if [ -d "$dest/.git" ]; then
    echo "  $name: already cloned"
  else
    git clone --depth 50 -q "$url" "$dest"
    echo "  $name: cloned"
  fi
  sha=$(git -C "$dest" rev-parse HEAD)
  SHAS[$name]="$sha"
  echo "  $name SHA: $sha"
done

echo ""
echo "=== Indexing with repograph ==="
REPOGRAPH="$REPOGRAPH_SRC/.venv/bin/python -m repograph.cli"
for name in "${!REPOS[@]}"; do
  dest="$WORKDIR/$name"
  echo "  Indexing $name..."
  $REPOGRAPH index "$dest" 2>&1 | tail -1
done

echo ""
echo "=== Applying selection rule (top-5 + random-5, seed=42) ==="
python3 "$REPOGRAPH_SRC/benchmarks/compare/scripts/select_files_held_out.py" \
  --repos "$WORKDIR/babel=$WORKDIR/babel" \
         "$WORKDIR/boto3=$WORKDIR/boto3" \
         "$WORKDIR/expressjs_router=$WORKDIR/expressjs_router" \
  --out "$RAW_OUT/held_out_selected.json"

echo ""
echo "=== Querying repograph ==="
python3 "$REPOGRAPH_SRC/benchmarks/compare/scripts/query_repograph_held_out.py" \
  --selected "$RAW_OUT/held_out_selected.json" \
  --workdir "$WORKDIR" \
  --out "$RAW_OUT"

echo ""
echo "=== Done. ==="
echo "Commit SHAs used:"
for name in "${!SHAS[@]}"; do
  echo "  $name: ${SHAS[$name]}"
done
echo ""
echo "Next: build ground truth and score."
echo "  python3 benchmarks/compare/scripts/build_gt2.py --mode held_out --repos ..."
echo "  python3 benchmarks/compare/scripts/score.py --run held_out --raw $RAW_OUT"
echo ""
echo "IMPORTANT: Do not modify the selection or ground truth after reading any results."
