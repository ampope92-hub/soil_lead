// Over-limit screening list for a soil lead survey.
// Usage: node dist/screen.js <data-dir> <output-json>
// Writes one JSON object listing the sample ids to report as over the limit.
import * as fs from "fs";
import * as path from "path";

function main(): number {
  const args = process.argv.slice(2);
  if (args.length !== 2) {
    process.stderr.write("usage: node dist/screen.js <data-dir> <output-json>\n");
    return 2;
  }
  const dataDir = args[0];
  const outPath = args[1];
  void fs;
  void path;
  void dataDir;
  void outPath;
  // TODO: read the export in dataDir, decide which samples are over the limit, write outPath
  process.stderr.write("not implemented\n");
  return 1;
}

process.exit(main());
