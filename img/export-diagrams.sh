#!/usr/bin/env bash

# Map page indices to tab names
declare -A PAGE_NAMES=(
  [1]="c4-context"
  [2]="c4-container"
  [3]="c4-component"
  [4]="responsibilities-and-boundaries"
)

DRAWIO_FILE="${1:-diagrams.drawio}"
BORDER=40

if [ ! -f "$DRAWIO_FILE" ]; then
  echo "Error: File not found: $DRAWIO_FILE"
  exit 1
fi

# Export each page
for index in $(echo "${!PAGE_NAMES[@]}" | tr ' ' '\n' | sort -n); do
  name="${PAGE_NAMES[$index]}"
  output="${name}.png"

  echo "Exporting page $index: $name -> $output"
  drawio --export --format=png --border="$BORDER" --all-pages --page-index="$index" --output="$output" "$DRAWIO_FILE" 2>/dev/null

  if [ $? -ne 0 ]; then
    echo "Warning: Failed to export page $index"
  fi
done

echo "Done!"
