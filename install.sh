#!/usr/bin/env sh
# One-line install for repograph (https://github.com/INDEX0-RESEARCH-LABS/repograph)
set -eu

if ! command -v uv >/dev/null 2>&1; then
    echo "installing uv (Astral)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

uv tool install --upgrade repograph-codeintel

echo
echo "repograph installed. Next:"
echo "  repograph index ."
echo "  repograph impact <file>"
