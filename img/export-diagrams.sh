#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Map page indices to tab names
declare -A PAGE_NAMES=(
  [1]="c4-context"
  [2]="c4-container"
  [3]="c4-component"
  [4]="responsibilities-and-boundaries"
)

INPUT_FILE="${1:-diagrams.drawio}"
BORDER=40

if [ "${INPUT_FILE:0:1}" = "/" ]; then
  DRAWIO_FILE="$INPUT_FILE"
elif [ -f "$INPUT_FILE" ]; then
  DRAWIO_FILE="$(cd -- "$(dirname -- "$INPUT_FILE")" && pwd)/$(basename -- "$INPUT_FILE")"
else
  DRAWIO_FILE="$SCRIPT_DIR/$INPUT_FILE"
fi

if [ ! -f "$DRAWIO_FILE" ]; then
  echo "Error: File not found: $INPUT_FILE"
  exit 1
fi

OUTPUT_DIR="$(dirname -- "$DRAWIO_FILE")"

# Export each page
for index in $(echo "${!PAGE_NAMES[@]}" | tr ' ' '\n' | sort -n); do
  name="${PAGE_NAMES[$index]}"
  output="$OUTPUT_DIR/${name}.png"

  echo "Exporting page $index: $name -> $output"
  drawio --export --format=png --border="$BORDER" --all-pages --page-index="$index" --output="$output" "$DRAWIO_FILE" 2>/dev/null

  if [ $? -ne 0 ]; then
    echo "Warning: Failed to export page $index"
  fi
done

echo "Done!"
