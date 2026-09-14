// Over-limit screening list for a soil lead survey.
// Usage: node dist/screen.js <data-dir> <output-json>
//
// The lab runs its digests in batches and each batch drifts on its own: the instrument reads a
// little high or low that day (an offset) and a little steep or shallow (a gain). That is what
// the certified reference materials in every batch are for. The two materials at the head of a
// batch pin its zero and its span where the batch starts, and the span then falls away as the
// batch runs, digest after digest, while the zero holds; the repeat of the first material at the
// end shows how far it had fallen by then. Each reading is put back on the certified scale with
// the zero and the span the batch had at that reading's position, and only then is a sample
// compared with the limit. A reading that looks over on a batch which read its controls high
// may sit well under once the batch is corrected, and one read late in a batch whose span had
// fallen a long way may sit well over.
//
// The export keeps the readings the lab rejected, with R in the flag column: a rejected control
// was run again in the next position, a rejected sample later in the run. Those rows are the
// lab's discards and take no part in anything here, so they are dropped as the file is read.
// The hottest digests were run diluted, and for those the instrument column is the reading of
// the diluted digest: the sample's level is that reading, corrected, times the dilution.
// The lab digests the soil as it arrived, wet, and its column is on that basis, while the limit,
// the certified values and the reference lab all work on dry weight. The register carries the
// water in each sample as a percentage of its as-received mass, so the dry-weight figure is the
// corrected reading divided by the dry share of the mass.
import * as fs from "fs";
import * as path from "path";

interface Row { batch: string; position: number; sampleId: string; kind: string; value: number; dilution: number; }
// The batch's scale: zero, the span at position pA (the head reading of the repeated material),
// and how much the span changes per position from there.
interface Scale { zero: number; span: number; perPosition: number; pA: number; }

function readCsv(file: string): string[][] {
  const text = fs.readFileSync(file, "utf8");
  const lines = text.split(/\r?\n/).filter((l) => l.length > 0);
  return lines.map((l) => l.split(","));
}

function main(): number {
  const args = process.argv.slice(2);
  if (args.length !== 2) {
    process.stderr.write("usage: node dist/screen.js <data-dir> <output-json>\n");
    return 2;
  }
  const dataDir = args[0];
  const outPath = args[1];

  const policy = JSON.parse(fs.readFileSync(path.join(dataDir, "policy.json"), "utf8"));
  const limit: number = Number(policy.limit_mg_kg);

  // certified values, by material name
  const certified = new Map<string, number>();
  const crm = readCsv(path.join(dataDir, "reference_materials.csv"));
  const ch = crm[0];
  const iMat = ch.indexOf("material");
  const iCert = ch.indexOf("certified_lead_mg_kg");
  for (const r of crm.slice(1)) certified.set(r[iMat], Number(r[iCert]));

  // dry share of each sample's as-received mass, from the register
  const dryShare = new Map<string, number>();
  {
    const sm = readCsv(path.join(dataDir, "samples.csv"));
    const smh = sm[0];
    const iRid = smh.indexOf("sample_id");
    const iWet = smh.indexOf("moisture_pct");
    for (const r of sm.slice(1)) {
      const pct = iWet < 0 || (r[iWet] ?? "").trim() === "" ? 0 : Number(r[iWet]);
      dryShare.set(r[iRid], 1 - pct / 100);
    }
  }

  const res = readCsv(path.join(dataDir, "results.csv"));
  const h = res[0];
  const iBatch = h.indexOf("batch");
  const iPos = h.indexOf("position");
  const iId = h.indexOf("sample_id");
  const iType = h.indexOf("type");
  const iVal = h.indexOf("lead_mg_kg");
  const iFlag = h.indexOf("flag");
  const iDil = h.indexOf("dilution");
  const rows: Row[] = res.slice(1)
    .filter((r) => iFlag < 0 || r[iFlag].trim() !== "R")
    .map((r) => ({
      batch: r[iBatch], position: Number(r[iPos]), sampleId: r[iId], kind: r[iType], value: Number(r[iVal]),
      dilution: iDil < 0 || r[iDil].trim() === "" ? 1 : Number(r[iDil]),
    }));

  // One scale per batch. In run order, the first accepted reading of each material is its head
  // reading, and the last control row of the batch is the repeat at the end. The head pair
  // would pin the zero and the span on their own if the span held; it does not, so the three
  // readings are solved together: the fall per position from the two readings of the repeated
  // material, then the span at the head from the other material with that fall taken out of
  // the few positions between the two head cups, then the zero.
  const fit = new Map<string, Scale>();
  const byBatch = new Map<string, Row[]>();
  for (const r of rows) {
    if (!byBatch.has(r.batch)) byBatch.set(r.batch, []);
    byBatch.get(r.batch)!.push(r);
  }
  for (const [batch, brows] of byBatch) {
    const head = new Map<string, { p: number; y: number }>();
    let end: { name: string; p: number; y: number } | null = null;
    for (const r of brows) {
      if (r.kind !== "control" || !certified.has(r.sampleId)) continue;
      if (!head.has(r.sampleId)) head.set(r.sampleId, { p: r.position, y: r.value });
      end = { name: r.sampleId, p: r.position, y: r.value };
    }
    if (head.size < 2 || end === null) {
      process.stderr.write(`batch ${batch} has fewer than two control materials\n`);
      return 1;
    }
    const a = head.get(end.name)!;
    const cA = certified.get(end.name)!;
    let other = "";
    for (const name of head.keys()) if (name !== end.name) other = name;
    const b = head.get(other)!;
    const cB = certified.get(other)!;
    // Two materials at the SAME certified value leave no spread to pin a span with.
    if (cB === cA) {
      process.stderr.write(`batch ${batch} has no spread between its control materials\n`);
      return 1;
    }
    // The repeat is the same material as its head reading, so the difference between the two
    // readings is the fall in span over the positions between them, in the material's units.
    const perPosition = end.p > a.p ? (end.y - a.y) / (cA * (end.p - a.p)) : 0;
    const span = (b.y - a.y - cB * perPosition * (b.p - a.p)) / (cB - cA);
    fit.set(batch, { zero: a.y - cA * span, span, perPosition, pA: a.p });
  }

  // Every sample's corrected figure, so the split-sample checks can be reported alongside the
  // list. The survey ships a dozen samples a second portion of which went to the reference lab,
  // and the contract asks for our corrected figure for each so the correction can be held against
  // a number that did not come off this instrument.
  // Keyed by batch and sample together. A sample the lab ran again was read in two batches, each
  // with its own zero and span, so the figure depends on which run it came off; the split rows
  // name the batch for exactly that reason. Only the accepted row is still here by now.
  const corrected = new Map<string, number>();
  const lastForSample = new Map<string, number>();
  for (const r of rows) {
    if (r.kind !== "sample") continue;
    const f = fit.get(r.batch)!;
    // put the reading on the certified scale the batch had at this position first, then undo
    // the dilution: the zero belongs to the reading in the cup, not to the soil. Then from the
    // soil as received to dry soil.
    const spanHere = f.span + f.perPosition * (r.position - f.pA);
    const v = (((r.value - f.zero) / spanHere) * r.dilution) / (dryShare.get(r.sampleId) ?? 1);
    corrected.set(`${r.batch} ${r.sampleId}`, v);
    lastForSample.set(r.sampleId, v);
  }

  // The split rows name the batch each sample was run in, so the figure is the corrected value
  // of that sample's accepted row in that batch. The reading in the split row is the same number
  // the results file carries, and where the digest was diluted only the results row says so.
  const splitRows: Array<{ sid: string; batch: string }> = [];
  {
    const sc = readCsv(path.join(dataDir, "split_checks.csv"));
    const sh = sc[0];
    const iSid = sh.indexOf("sample_id");
    const iBat = sh.indexOf("batch");
    for (const r of sc.slice(1)) splitRows.push({ sid: r[iSid], batch: iBat >= 0 ? r[iBat] : "" });
  }
  const splitCheck: Record<string, number> = Object.create(null);
  for (const { sid, batch } of splitRows) {
    const v = corrected.get(`${batch} ${sid}`) ?? lastForSample.get(sid);
    if (v === undefined) {
      process.stderr.write(`split check names ${sid}, which is not a sample in results.csv\n`);
      return 1;
    }
    splitCheck[sid] = v;
  }

  // A sample is listed once. The rejected rows are gone, so each id has one reading left, but the
  // contract says no id twice and this holds to it whatever the file carried.
  const over: string[] = [];
  const listed = new Set<string>();
  for (const r of rows) {
    if (r.kind !== "sample") continue;
    if (corrected.get(`${r.batch} ${r.sampleId}`)! > limit && !listed.has(r.sampleId)) {
      listed.add(r.sampleId);
      over.push(r.sampleId);
    }
  }

  // The contract asks for the same corrected figure behind every id on the list, not only the
  // split ones, so it is reported for every sample in results.csv here too.
  const correctedOut: Record<string, number> = Object.create(null);
  for (const [sid, v] of lastForSample) correctedOut[sid] = v;

  fs.writeFileSync(
    outPath,
    JSON.stringify({ over_limit: over, split_check: splitCheck, corrected_mg_kg: correctedOut }) + "\n",
  );
  return 0;
}

process.exit(main());
