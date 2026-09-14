#!/usr/bin/env bash
set -euo pipefail

# Builds the screening list the council gets.
#
# Every batch on the instrument reads with its own offset and gain, which is why the lab runs
# two certified reference materials at the head of each batch, and its span falls away as the
# batch runs, which is why one of them is run again at the end. The list is built by putting
# each reading back on the certified scale the batch had at that reading's position, from its
# own three control readings, then comparing the corrected sample results with the limit in
# policy.json. The raw results, and a single correction fitted across the whole run, both leave
# the list a tenth wrong in each direction. Implementation: screen.ts in this directory.
install -m 644 "$(dirname "$0")/screen.ts" /app/screen/src/screen.ts
bash /app/screen/build.sh
mkdir -p /app/out
node /app/screen/dist/screen.js /app/data /app/out/over_limit.json
