#!/usr/bin/env bash
set -euo pipefail

# Resolve to the repo root regardless of where this script is invoked from
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cd "$REPO_ROOT" && poetry version --short)"
OUTPUT_DIR="$REPO_ROOT/dist"
BINARY_NAME="archcare"

echo "Building archcare v${VERSION}..."

# Detect compiler: prefer Clang, fallback to GCC
if command -v clang &> /dev/null; then
    COMPILER="--clang"
    echo "Using Clang compiler"
else
    COMPILER=""
    echo "Clang not found, using default compiler (GCC)"
fi

# Ensure output directory exists and is clean
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

cd "$REPO_ROOT/src/archcare"

# Build with Nuitka (project options in app.py handle most flags)
poetry run python -m nuitka cli/app.py \
  --output-filename="$BINARY_NAME" \
  --output-dir="$OUTPUT_DIR" \
  --product-version="$VERSION" \
  --jobs="$(nproc)" \
  --remove-output \
  $COMPILER

BINARY_PATH="$OUTPUT_DIR/$BINARY_NAME"

# Verify binary was created
if [[ ! -f "$BINARY_PATH" ]]; then
    echo "ERROR: Binary not found at $BINARY_PATH"
    exit 1
fi

# Generate checksum with relative filename (so it works anywhere)
cd "$OUTPUT_DIR"
sha256sum "$BINARY_NAME" > "$BINARY_NAME.sha256"
cd - > /dev/null

echo "Built: $BINARY_PATH ($(du -h "$BINARY_PATH" | cut -f1))"
echo "Checksum: $(awk '{print $1}' "$BINARY_PATH.sha256")"
