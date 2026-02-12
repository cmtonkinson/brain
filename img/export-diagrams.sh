#!/bin/bash

# Usage: ./export-drawio.sh diagram.drawio

DRAWIO_FILE="$1"
BORDER=40

if [ ! -f "$DRAWIO_FILE" ]; then
  echo "Error: File not found: $DRAWIO_FILE"
  exit 1
fi

# Get list of page names
PAGES=$(drawio --export --format png --list-pages "$DRAWIO_FILE" 2>/dev/null)

if [ -z "$PAGES" ]; then
  echo "Error: Could not read pages from file"
  exit 1
fi

# Export each page
echo "$PAGES" | while IFS= read -r page; do
  if [ -n "$page" ]; then
    OUTPUT="${page// /_}.png"
    echo "Exporting: $page -> $OUTPUT"
    drawio --export --format png --border "$BORDER" --page-index "$page" --output "$OUTPUT" "$DRAWIO_FILE"
  fi
done
