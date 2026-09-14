#!/usr/bin/env bash
# Compile the screening tool. Run it afterwards as: node /app/screen/dist/screen.js <data-dir> <output-json>
set -euo pipefail
cd /app/screen
tsc -p /app/screen
