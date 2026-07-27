#!/usr/bin/env bash
set -euo pipefail

# Resolve to the repo root regardless of where this script is invoked from
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cd "$REPO_ROOT" && poetry version --short)"
OUTPUT_DIR="$REPO_ROOT/dist"
BINARY_NAME="archcare"

echo "Building archcare v${VERSION}..."
mkdir -p "$OUTPUT_DIR"

cd "$REPO_ROOT/src/archcare"

poetry run python -m nuitka cli/app.py \
  --output-filename="$BINARY_NAME" \
  --output-dir="$OUTPUT_DIR" \
  --product-version="$VERSION" \
  --remove-output

BINARY_PATH="$OUTPUT_DIR/$BINARY_NAME"
sha256sum "$BINARY_PATH" > "$BINARY_PATH.sha256"

echo "Built: $BINARY_PATH"
echo "Checksum: $(cat "$BINARY_PATH.sha256")"
