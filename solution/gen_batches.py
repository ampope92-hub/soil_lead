#!/usr/bin/env python3
"""Generate a contract lab's results file for a soil lead survey, the certified reference
materials it ran with every batch, the register of sample locations, the policy, and the key.

Samples are digested and measured in batches. Each batch carries its own offset and gain, which
is why every batch also runs two certified reference materials. The results file reports the
raw instrument result for everything, controls included. The key is which samples truly exceed
the limit, which is what the confirmatory re-analysis at the reference lab found.

The instrument's response falls away as a batch runs, digest after digest through the
nebuliser, so the span at the end of a batch is short of the span at its head while the zero
holds. The span falls in a straight line with position from the head of the batch to its end,
and the repeat of the first material at the end is what shows how far it fell. The fall is drawn
from its own random stream, so the true concentrations and the key are the same with or without
it. Readings are computed in a final pass, once every position is settled, so the span a row was
read at is the span at the position the export gives it.

The export also carries what a real one does: readings the lab rejected. A rejected reading stays
in the file with R in its flag column. A rejected control was run again in the next position; a
rejected sample was run again later, in a later batch, so its id appears twice. Rejected readings
are drawn from their own random stream, so the accepted readings and the key are the same with or
without them. The hottest digests were run diluted, and the dilution column carries the factor:
the instrument column is the reading of the diluted digest, so the sample's own level is that
reading, corrected, times the factor. The lab digests the soil as it arrived and reports on that
basis, wet, and measures the water in each sample separately; the register carries it as
moisture_pct, a percentage of the as-received mass. The limit, the certified values and the
reference lab's figures are all dry weight, so the dry-weight figure is the corrected reading
divided by the dry share of the mass. The moisture is drawn from its own stream, so the true
concentrations and the key are the same with or without it. The csv files end their lines with
CRLF, which is how the lab's system writes them.

    gen_batches.py <out-dir> <key-dir> [--seed N] [--hidden]

Standard library only.
"""
import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import random


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("key_dir")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--hidden", action="store_true")
    a = ap.parse_args()
    if a.seed is None:
        a.seed = 33 if a.hidden else 21
    rng = random.Random(a.seed)

    if a.hidden:
        site, n_samples, batch_size, limit = "Former gasworks, Salford", 520, 20, 300.0   # mg/kg
        crm = {"SRM-2586": 450.0, "SRM-2711a": 120.0}
        crm_order = ("SRM-2711a", "SRM-2586")
        off_sd, gain_sd, noise_cv = 40.0, 0.09, 0.02
        conc_mu, conc_sig = math.log(240), 0.55
        prec_bar, rec_bar, split_tol = 0.88, 0.92, 0.22
        first_day = dt.date(2025, 5, 12)
        fall_lo, fall_hi = 0.66, 0.92
    else:
        site, n_samples, batch_size, limit = "Allotments, Bristol east", 480, 24, 200.0
        crm = {"CRM-A": 85.0, "CRM-B": 320.0}
        crm_order = ("CRM-A", "CRM-B")
        off_sd, gain_sd, noise_cv = 25.0, 0.08, 0.02
        conc_mu, conc_sig = math.log(170), 0.5
        prec_bar, rec_bar, split_tol = 0.90, 0.90, 0.15
        first_day = dt.date(2025, 3, 3)
        fall_lo, fall_hi = 0.90, 0.99

    samples = []
    for i in range(n_samples):
        sid = f"BS{i + 1:04d}"
        true = rng.lognormvariate(conc_mu, conc_sig)
        samples.append((sid, true))
    # The lab digests the soil as it arrives and reports the result on that basis, and measures
    # the water in a sub-sample separately. Its own stream, so the true concentrations and the
    # key are the same with or without it. The allotment samples were air-dried at the depot
    # before dispatch; the gasworks samples went to the lab as dug.
    wet_rng = random.Random(a.seed + 4242)
    w_lo, w_hi = (0.10, 0.30) if a.hidden else (0.01, 0.04)
    water = {sid: wet_rng.uniform(w_lo, w_hi) for sid, _ in samples}
    moisture_pct = {sid: round(w * 100, 1) for sid, w in water.items()}
    # The span falls through every batch. Its own stream, so nothing else moves. fall is the
    # span at the end of the batch as a share of the span at its head.
    drift_rng = random.Random(a.seed + 5151)
    order = list(range(n_samples))
    rng.shuffle(order)
    # A row is [batch, day, position, id, type, reading, flag, dilution, level, mult, noise]:
    # the reading is computed in the final pass from the level the cup held (certified value, or
    # the sample's concentration on the soil as received, over the dilution), a multiplier for the
    # incidents (1 for a reading the lab accepted), and the noise draw for that cup.
    rows, batches, truth = [], [], {}
    day = first_day
    b = 0
    for start in range(0, n_samples, batch_size):
        b += 1
        batch = f"B{b:03d}"
        off = rng.gauss(0, off_sd)
        gain = 1.0 + rng.gauss(0, gain_sd)
        fall = drift_rng.uniform(fall_lo, fall_hi)
        batches.append((batch, day.isoformat(), off, gain, fall))
        # both reference materials at the head of the batch, the first of them again at the end
        seq = 0
        for name in crm_order:
            seq += 1
            rows.append([batch, day, seq, name, "control", None, "", 1, crm[name], 1.0, rng.gauss(0, noise_cv)])
        for idx in order[start:start + batch_size]:
            sid, true = samples[idx]
            seq += 1
            rows.append([batch, day, seq, sid, "sample", None, "", 1, true * (1 - water[sid]), 1.0, rng.gauss(0, noise_cv)])
            truth[sid] = round(true, 2)
        seq += 1
        rows.append([batch, day, seq, crm_order[0], "control", None, "", 1, crm[crm_order[0]], 1.0, rng.gauss(0, noise_cv)])
        day = day + dt.timedelta(days=rng.choice([1, 1, 2, 3]))

    batch_ids = [bb for bb, _, _, _, _ in batches]
    scale = {bb: (o, g, f) for bb, _, o, g, f in batches}
    day_of = {r[0]: r[1] for r in rows}

    def settle():
        """Number the positions in file order and compute every reading at the span of its
        position: the span at position p of a batch whose end repeat sits at position n is
        gain * (1 - (1 - fall) * (p - 1) / (n - 1))."""
        seq = {}
        for r in rows:
            seq[r[0]] = seq.get(r[0], 0) + 1
            r[2] = seq[r[0]]
        last = {}
        for r in rows:
            if r[4] == "control" and r[6] == "":
                last[r[0]] = r[2]
        for r in rows:
            off, gain, fall = scale[r[0]]
            span = gain * (1 - (1 - fall) * (r[2] - 1) / (last[r[0]] - 1))
            r[5] = round(off + span * r[8] * r[9] / r[7] * (1 + r[10]), 1)

    settle()

    # A dozen samples were split and a second portion sent to the reference lab, the way a survey
    # of this size normally carries an external check. They are spread across the run so more than
    # one batch is covered, and the reference lab's figure is reported beside our own reading.
    split_rng = random.Random(a.seed + 7717)
    sample_rows = [r for r in rows if r[4] == "sample"]
    step = max(1, len(sample_rows) // 12)
    checks = [sample_rows[i] for i in range(0, len(sample_rows), step)][:12]
    # A sample whose reading came back at or below zero belongs in this set. Dropping such a
    # reading is an easy thing for a parser to do by accident, and one sample on its own cannot
    # move the precision or recall bars, so without it here nothing would catch that.
    low = [r for r in sample_rows if r[5] <= 0]
    if low and not any(r[3] == low[0][3] for r in checks):
        checks[-1] = low[0]
    checks = sorted(checks, key=lambda r: r[3])
    check_ids = [r[3] for r in checks]

    # Rejected readings. Their own stream, so nothing above changes when they are added.
    rej = random.Random(a.seed + 9191)

    # The hottest digests were too strong for the instrument's range and were run at a 1 in 5
    # dilution. The instrument column is the reading of the diluted digest; the dilution column
    # carries the factor, 1 for everything else. Their noise is redrawn here, from the same
    # stream as the rejections, so nothing else moves.
    n_dil, d_factor = (18, 5) if a.hidden else (3, 5)
    hottest = sorted((r for r in rows if r[4] == "sample"), key=lambda r: -truth[r[3]])[:n_dil]
    for r in hottest:
        r[7] = d_factor
        r[10] = rej.gauss(0, noise_cv)
    diluted_ids = {r[3] for r in hottest}
    n_rerun = 10 if a.hidden else 2
    # A rejected sample: a short pour reads well short, a contaminated or mixed-up cup reads well
    # high. The sample was run again in a later batch, before that batch's end control. On the
    # other survey two of the split samples are among them, one truly under the limit whose
    # rejected reading came back high and one truly over whose rejected reading came back short,
    # so a program that keeps the wrong row cannot land them.
    n_b = len(batch_ids)
    bidx = {bb: k for k, bb in enumerate(batch_ids)}

    def rerun(row, direction):
        m = rej.uniform(2.5, 4.0) if direction == "high" else rej.uniform(0.25, 0.42)
        row[9] = m
        row[10] = rej.gauss(0, noise_cv)
        row[6] = "R"
        tb = batch_ids[rej.randint(bidx[row[0]] + 1, n_b - 1)]
        noise = rej.gauss(0, noise_cv)
        end = max(i for i, r in enumerate(rows) if r[0] == tb)
        rows.insert(end, [tb, day_of[tb], 0, row[3], "sample", None, "", 1, row[8], 1.0, noise])

    def eligible(pred):
        return [r for r in rows if r[4] == "sample" and r[6] == "" and r[7] == 1 and bidx[r[0]] <= n_b - 3
                and r[3] not in check_ids and pred(truth[r[3]])]

    forced = []
    if a.hidden:
        under = rej.choice(eligible(lambda t: limit / 2.2 < t < 0.85 * limit))
        over = rej.choice(eligible(lambda t: 1.1 * limit < t < 2.0 * limit))
        forced = [(under, "high"), (over, "low")]
        keep = [r for r in checks if not low or r[3] != low[0][3]]
        drop = {keep[3][3], keep[7][3]}
        added = [under, over]
        # and one diluted sample, so a program that reads the diluted digest's reading as the
        # sample's level cannot land it
        if not any(r[3] in diluted_ids for r in checks if r[3] not in drop):
            drop.add(keep[5][3])
            added.append(min(hottest, key=lambda r: truth[r[3]]))
        # and one sample late in the batch where the zero is the largest share of the first
        # material's reading, since a program that takes the ratio of that material's two readings
        # as the ratio of the spans is furthest off there, on exactly that sample
        first_c = crm[crm_order[0]]
        def ratio_miss(bb):
            o, g, f = scale[bb]
            return abs(math.log(f * (o + first_c * g) / (o + first_c * g * f))) if o + first_c * g * f > 0 else 9.0
        wb = max(batch_ids, key=ratio_miss)
        late = [r for r in rows if r[0] == wb and r[4] == "sample" and r[6] == "" and r[7] == 1
                and r[3] not in check_ids and r[3] not in {x[3] for x in added} and r[2] >= batch_size * 0.7]
        drop.add(keep[9][3])
        added.append(max(late, key=lambda r: r[2]))
        checks = [r for r in checks if r[3] not in drop] + added
        check_ids = [r[3] for r in checks]
    picks = rej.sample(eligible(lambda t: True), n_rerun - len(forced))
    for row in picks:
        rerun(row, rej.choice(["high", "low"]))
    for row, direction in forced:
        rerun(row, direction)
    accepted = {r[3]: r for r in rows if r[4] == "sample" and r[6] == ""}
    check_batches = {accepted[sid][0] for sid in check_ids}

    # Rejected controls. Two kinds of incident. The two cups at the head of a batch the wrong way
    # round: each material read at the other's level, each was rejected and run again straight
    # after, so the head of that batch is four control rows. And a short pour: one control read
    # well short and was run again in the next position. On the other survey one of the swapped
    # heads sits in a batch that carries a split sample, so a fit through every control row,
    # rejected ones included, cannot land that sample. The shipped survey carries one short pour,
    # in a batch with no split sample in it.
    incidents = [("swap", True), ("swap", False), ("short", False), ("short", False)] if a.hidden else [("short", False)]
    used = set()
    for mode, in_split_batch in incidents:
        if in_split_batch:
            pool = [bb for bb in batch_ids if bb in check_batches and bb not in used]
        else:
            pool = [bb for bb in batch_ids if bb not in used and (a.hidden or bb not in check_batches)]
        bb = rej.choice(pool)
        used.add(bb)
        if mode == "swap":
            for name in crm_order:
                i = next(i for i, r in enumerate(rows) if r[0] == bb and r[4] == "control" and r[3] == name)
                other = next(m for m in crm if m != name)
                rows.insert(i, [bb, rows[i][1], 0, name, "control", None, "R", 1, crm[other], 1.0, rej.gauss(0, noise_cv)])
        else:
            ctrl_idx = [i for i, r in enumerate(rows) if r[0] == bb and r[4] == "control"]
            i = rej.choice(ctrl_idx)
            name = rows[i][3]
            rows.insert(i, [bb, rows[i][1], 0, name, "control", None, "R", 1, crm[name], rej.uniform(0.3, 0.55), rej.gauss(0, noise_cv)])
    settle()
    accepted = {r[3]: r for r in rows if r[4] == "sample" and r[6] == ""}
    checks = sorted((accepted[sid] for sid in check_ids), key=lambda r: r[3])
    # Four of the twelve are still with the reference lab, so their column is blank in the export.
    # Their figures live in the key only. That is what stops a program copying the lab column back
    # out instead of correcting the reading: the blank rows have nothing to copy.
    pending = {checks[i][3] for i in (2, 5, 8, 11)}
    split_lab = {r[3]: round(truth[r[3]] * (1 + split_rng.gauss(0, 0.01)), 2) for r in checks}

    out = pathlib.Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "results.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["batch", "run_date", "position", "sample_id", "type", "lead_mg_kg", "dilution", "flag"])
        for r in rows:
            w.writerow([r[0], r[1].isoformat(), r[2], r[3], r[4], r[5], r[7], r[6]])
    with open(out / "reference_materials.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["material", "certified_lead_mg_kg", "uncertainty_mg_kg"])
        for name in crm_order:
            v = crm[name]
            w.writerow([name, v, round(v * 0.02, 1)])
    with open(out / "samples.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sample_id", "plot", "depth_cm", "moisture_pct"])
        for i, (sid, true) in enumerate(samples):
            w.writerow([sid, f"P{i // 8 + 1:03d}", rng.choice([10, 20, 30]), moisture_pct[sid]])
    with open(out / "split_checks.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sample_id", "batch", "our_reading_mg_kg", "reference_lab_mg_kg"])
        for r in checks:
            lab = "" if r[3] in pending else split_lab[r[3]]
            w.writerow([r[3], r[0], r[5], lab])

    accepted_rows = [r for r in rows if r[6] == ""]
    raw_over = sorted(r[3] for r in accepted_rows if r[4] == "sample" and r[5] * r[7] > limit)
    policy = {
        "site": site,
        "limit_mg_kg": limit,
        "minimum_precision": prec_bar,
        "minimum_recall": rec_bar,
        "split_check_tolerance": split_tol,
        "corrected_tolerance": round(split_tol * 2, 2),
        "samples_over_limit_as_reported": len(raw_over),
    }
    with open(out / "policy.json", "w") as fh:
        json.dump(policy, fh, indent=2)
        fh.write("\n")
    kd = pathlib.Path(a.key_dir)
    kd.mkdir(parents=True, exist_ok=True)
    over = sorted(s for s, t in truth.items() if t > limit)
    with open(kd / "key.json", "w") as fh:
        json.dump({"over_limit": over, "minimum_precision": prec_bar, "minimum_recall": rec_bar,
                   "split_check_tolerance": split_tol,
                   "split_lab_mg_kg": split_lab, "split_pending": sorted(pending),
                   "truth_mg_kg": truth,
                   "batches": {b: {"offset": round(o, 2), "gain": round(g, 4), "span_at_end": round(f, 4)} for b, _, o, g, f in batches},
                   "rejected_controls": [[r[0], r[2], r[3]] for r in rows if r[4] == "control" and r[6] == "R"],
                   "rerun_samples": sorted(r[3] for r in rows if r[4] == "sample" and r[6] == "R"),
                   "diluted": sorted(diluted_ids)}, fh, indent=2)
        fh.write("\n")
    n_rc = sum(1 for r in rows if r[4] == "control" and r[6] == "R")
    n_rs = sum(1 for r in rows if r[4] == "sample" and r[6] == "R")
    print(f"{site}: {n_samples} samples in {b} batches; {len(raw_over)} over the limit as reported, {len(over)} truly over; "
          f"{n_rc} rejected controls, {n_rs} rejected sample readings run again, {len(diluted_ids)} diluted digests")


if __name__ == "__main__":
    main()
