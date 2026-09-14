#!/usr/bin/env python3
"""Where the bars sit, measured rather than chosen.

Generates surveys with gen_batches.py across seeds and scores, on each, what the likely routes
produce against the reference lab's confirmation, on every check the verifier runs: precision
and recall of the over-limit list, the worst split-sample error against the tolerance (the four
pending rows included), and whether the split figures agree with the list.

Routes. raw_results takes the instrument column as the concentration, which is the lab's own
count. one_line_whole_run fits one straight line through every accepted control reading in the
run and applies it to every batch. batch_offset_only shifts each batch by its offset on the first
material alone. reference_span_drift is the reference: the zero and the head span from the two
accepted head controls, the span at the end from the repeat of the first material, the span
falling in a straight line with position between them, rejected rows dropped. Then the readings
of the end repeat that miss: head_pair_only pins each batch on its head pair and never looks at
the repeat, so the fall in span goes uncorrected; three_point_line fits one least-squares line
through all three control readings of a batch, which splits the fall between the head and the
end; drift_ratio takes the ratio of the two readings of the first material as the ratio of the
spans, which forgets that both readings carry the zero. Then the hurried readings of the rest of
the export: ignores_flag keeps every row, rejected or not; flag_controls_only drops rejected
controls but keeps rejected sample readings and lists a sample if any of its readings is over;
flag_samples_only drops rejected sample readings but pins each batch on control rows whether
rejected or not; first_reading drops rejected controls and takes the first row for each sample
id. ignores_dilution handles the rejected rows and never reads the dilution column, so a diluted
digest's reading stands as the sample's level. ignores_moisture handles everything in results.csv
and never opens the register, so the as-received reading stands as the dry-weight figure. Every
route but raw_results, which is the lab's own count, applies the moisture, so each fails for its
own reason and not for that one.

    calibrate.py [--seeds N] [--dump]
"""
import argparse
import csv
import json
import pathlib
import statistics as st
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def line(xs, ys):
    mx, my = st.mean(xs), st.mean(ys)
    g = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - g * mx, g


def head_and_end(rows, crm, first):
    """Per batch, the head reading of each material (first row in run order) and the end reading
    of the first material (last row in run order), as (position, reading), from the control rows
    given, whether or not those include rejected ones."""
    ctl = {}
    for r in rows:
        if r["type"] != "control":
            continue
        b = ctl.setdefault(r["batch"], {})
        p, v = int(r["position"]), float(r["lead_mg_kg"])
        b.setdefault(("head", r["sample_id"]), (p, v))
        if r["sample_id"] == first:
            b[("end", first)] = (p, v)
    return ctl


def span_fit(ctl, crm, first, second):
    """The reference: zero and head span from the head pair, the span at the end from the end
    repeat, falling in a straight line with position. Returns per batch (zero, span_at_pA, slope, pA)."""
    fit = {}
    for b, m in ctl.items():
        pA, yA = m[("head", first)]
        pB, yB = m[("head", second)]
        pE, yE = m[("end", first)]
        cA, cB = crm[first], crm[second]
        s = (yE - yA) / (cA * (pE - pA))
        gA = (yB - yA - cB * s * (pB - pA)) / (cB - cA)
        z = yA - cA * gA
        fit[b] = (z, gA, s, pA)
    return fit


def head_pair_fit(ctl, crm, first, second):
    fit = {}
    for b, m in ctl.items():
        pA, yA = m[("head", first)]
        _pB, yB = m[("head", second)]
        g = (yB - yA) / (crm[second] - crm[first])
        fit[b] = (yA - crm[first] * g, g, 0.0, pA)
    return fit


def ratio_fit(ctl, crm, first, second):
    """The hurried reading: the head pair as head_pair_fit, then the span at the end taken as the
    head span times the end reading over the head reading of the first material."""
    fit = {}
    for b, m in ctl.items():
        pA, yA = m[("head", first)]
        _pB, yB = m[("head", second)]
        pE, yE = m[("end", first)]
        g = (yB - yA) / (crm[second] - crm[first])
        gE = g * yE / yA
        fit[b] = (yA - crm[first] * g, g, (gE - g) / (pE - pA), pA)
    return fit


def lsq_fit(rows, crm):
    """One least-squares line per batch through every (certified, reading) control point given."""
    pts = {}
    for r in rows:
        if r["type"] == "control":
            pts.setdefault(r["batch"], []).append((crm[r["sample_id"]], float(r["lead_mg_kg"])))
    fit = {}
    for b, p in pts.items():
        o, g = line([x for x, _ in p], [y for _, y in p])
        fit[b] = (o, g, 0.0, 0)
    return fit


def routes(d):
    with open(d / "policy.json") as fh:
        limit = json.load(fh)["limit_mg_kg"]
    with open(d / "reference_materials.csv", newline="") as fh:
        mats = list(csv.DictReader(fh))
    crm = {r["material"]: float(r["certified_lead_mg_kg"]) for r in mats}
    first, second = mats[0]["material"], mats[1]["material"]
    with open(d / "results.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with open(d / "split_checks.csv", newline="") as fh:
        splits = list(csv.DictReader(fh))
    with open(d / "samples.csv", newline="") as fh:
        dry = {r["sample_id"]: 1.0 / (1.0 - float(r["moisture_pct"]) / 100.0) for r in csv.DictReader(fh)}
    accepted = [r for r in rows if r["flag"] != "R"]
    ctl_acc = head_and_end(accepted, crm, first)
    ctl_all = head_and_end(rows, crm, first)
    fit_ref = span_fit(ctl_acc, crm, first, second)
    fit_all = span_fit(ctl_all, crm, first, second)
    fit_head = head_pair_fit(ctl_acc, crm, first, second)
    fit_ratio = ratio_fit(ctl_acc, crm, first, second)
    fit_lsq = lsq_fit(accepted, crm)
    xs, ys = [], []
    for r in accepted:
        if r["type"] == "control":
            xs.append(crm[r["sample_id"]]); ys.append(float(r["lead_mg_kg"]))
    goff, ggain = line(xs, ys)
    headA = {b: m[("head", first)][1] for b, m in ctl_acc.items()}

    def dil(r):
        return float(r.get("dilution") or 1)

    def corr(fit, r, use_dilution=True, use_moisture=True):
        z, g, s, pA = fit[r["batch"]]
        span = g + s * (int(r["position"]) - pA)
        return (float(r["lead_mg_kg"]) - z) / span * (dil(r) if use_dilution else 1.0) * (dry[r["sample_id"]] if use_moisture else 1.0)

    def any_over(fit, sample_rows, use_dilution=True, use_moisture=True):
        out, seen = [], set()
        for r in sample_rows:
            if corr(fit, r, use_dilution, use_moisture) > limit and r["sample_id"] not in seen:
                seen.add(r["sample_id"]); out.append(r["sample_id"])
        return out

    def split_from_rows(fit, sample_rows, use_dilution=True, use_moisture=True):
        # the reference's way: the corrected value of the sample's accepted row in the batch the split row names
        by_key = {(r["batch"], r["sample_id"]): r for r in sample_rows}
        return {s["sample_id"]: corr(fit, by_key[(s["batch"], s["sample_id"])], use_dilution, use_moisture) for s in splits}

    samp_acc = [r for r in accepted if r["type"] == "sample"]
    samp_all = [r for r in rows if r["type"] == "sample"]
    first_rows = {}
    for r in samp_all:
        first_rows.setdefault(r["sample_id"], r)
    raw = lambda r: float(r["lead_mg_kg"]) * dil(r)
    acc_by_key = {(r["batch"], r["sample_id"]): r for r in samp_acc}
    out = {
        "raw_results": ([r["sample_id"] for r in samp_acc if raw(r) > limit],
                        {s["sample_id"]: raw(acc_by_key[(s["batch"], s["sample_id"])]) for s in splits}),
        "one_line_whole_run": ([r["sample_id"] for r in samp_acc if (float(r["lead_mg_kg"]) - goff) / ggain * dil(r) * dry[r["sample_id"]] > limit],
                               {s["sample_id"]: (float(s["our_reading_mg_kg"]) - goff) / ggain * dil(acc_by_key[(s["batch"], s["sample_id"])]) * dry[s["sample_id"]] for s in splits}),
        "batch_offset_only": ([r["sample_id"] for r in samp_acc
                               if (float(r["lead_mg_kg"]) - (headA[r["batch"]] - crm[first])) * dil(r) * dry[r["sample_id"]] > limit],
                              {s["sample_id"]: (float(s["our_reading_mg_kg"]) - (headA[s["batch"]] - crm[first])) * dil(acc_by_key[(s["batch"], s["sample_id"])]) * dry[s["sample_id"]] for s in splits}),
        "reference_span_drift": (any_over(fit_ref, samp_acc), split_from_rows(fit_ref, samp_acc)),
        "head_pair_only": (any_over(fit_head, samp_acc), split_from_rows(fit_head, samp_acc)),
        "three_point_line": (any_over(fit_lsq, samp_acc), split_from_rows(fit_lsq, samp_acc)),
        "drift_ratio": (any_over(fit_ratio, samp_acc), split_from_rows(fit_ratio, samp_acc)),
        "ignores_flag": (any_over(fit_all, samp_all), split_from_rows(fit_all, samp_all)),
        "flag_controls_only": (any_over(fit_ref, samp_all), split_from_rows(fit_ref, samp_acc)),
        "flag_samples_only": (any_over(fit_all, samp_acc), split_from_rows(fit_all, samp_acc)),
        "first_reading": (any_over(fit_ref, list(first_rows.values())),
                          {s["sample_id"]: corr(fit_ref, first_rows[s["sample_id"]]) for s in splits}),
        "ignores_dilution": (any_over(fit_ref, samp_acc, False), split_from_rows(fit_ref, samp_acc, False)),
        "ignores_moisture": (any_over(fit_ref, samp_acc, True, False), split_from_rows(fit_ref, samp_acc, True, False)),
    }
    return out, limit


def corrected_vs_truth(d, key):
    """The reference's own corrected_mg_kg, sample by sample, against the key's true
    concentration -- the same figure corrected_mg_kg is now held to for every sample
    split_checks.csv does not name. Returns the worst relative error among the non-split
    samples, and its id, so the tolerance in tests/test_outputs.py can be checked against real
    margin rather than picked by feel."""
    with open(d / "results.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with open(d / "reference_materials.csv", newline="") as fh:
        mats = list(csv.DictReader(fh))
    with open(d / "split_checks.csv", newline="") as fh:
        split_ids = {r["sample_id"] for r in csv.DictReader(fh)}
    with open(d / "samples.csv", newline="") as fh:
        dryshare = {r["sample_id"]: 1.0 - float(r["moisture_pct"]) / 100.0 for r in csv.DictReader(fh)}
    crm = {r["material"]: float(r["certified_lead_mg_kg"]) for r in mats}
    first, second = mats[0]["material"], mats[1]["material"]
    accepted = [r for r in rows if r["flag"] != "R"]
    fit = span_fit(head_and_end(accepted, crm, first), crm, first, second)
    truth = key["truth_mg_kg"]
    worst, worst_id = 0.0, None
    for r in accepted:
        if r["type"] != "sample" or r["sample_id"] in split_ids:
            continue
        z, g, s, pA = fit[r["batch"]]
        span = g + s * (int(r["position"]) - pA)
        v = (float(r["lead_mg_kg"]) - z) / span * float(r.get("dilution") or 1) / dryshare[r["sample_id"]]
        err = abs(v - float(truth[r["sample_id"]])) / float(truth[r["sample_id"]])
        if err > worst:
            worst, worst_id = err, r["sample_id"]
    return worst, worst_id


def score(listed, split, key, pol, limit):
    over, lset = set(key["over_limit"]), set(listed)
    hits = len(over & lset)
    p = hits / len(lset) if lset else 0.0
    r = hits / len(over)
    worst = max(abs(v - float(key["split_lab_mg_kg"][sid])) / float(key["split_lab_mg_kg"][sid]) for sid, v in split.items())
    agree = all((v > limit) == (sid in lset) for sid, v in split.items())
    ok = p >= pol["minimum_precision"] and r >= pol["minimum_recall"] and worst <= pol["split_check_tolerance"] and agree
    return p, r, worst, agree, ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--dump", action="store_true", help="also score the shipped seeds (21 and 33) and print each route's figures")
    a = ap.parse_args()
    fmt = lambda v: f"{st.mean(v):5.3f} [{min(v):5.3f},{max(v):5.3f}]"
    for label, extra, shipped_seed in [("Bristol allotments, limit 200, batches of 24, bars 0.90/0.90, tolerance 0.15", [], 21),
                                       ("Salford gasworks, limit 300, batches of 20, bars 0.88/0.92, tolerance 0.22", ["--hidden"], 33)]:
        res = {}
        with tempfile.TemporaryDirectory() as tmp:
            seeds = list(range(a.seeds)) + ([shipped_seed] if a.dump else [])
            for seed in seeds:
                d = pathlib.Path(tmp) / f"s{seed}"
                subprocess.run([sys.executable, str(HERE / "gen_batches.py"), str(d / "data"), str(d), "--seed", str(seed)] + extra,
                               check=True, capture_output=True)
                with open(d / "key.json") as fh:
                    key = json.load(fh)
                with open(d / "data" / "policy.json") as fh:
                    pol = json.load(fh)
                out, limit = routes(d / "data")
                if a.dump and seed == shipped_seed:
                    print(f"== {label}: the shipped seed {seed}, {len(key['over_limit'])} truly over")
                    for name, (lst, split) in out.items():
                        p, r, w, ag, ok = score(lst, split, key, pol, limit)
                        wid = max(split, key=lambda sid: abs(split[sid] - float(key["split_lab_mg_kg"][sid])) / float(key["split_lab_mg_kg"][sid]))
                        print(f"   {name:22s} listed {len(lst):3d}  p {p:.3f}  r {r:.3f}  worst split {w:.3f} ({wid})  agree {ag}  {'PASS' if ok else 'fail'}")
                    wt, wtid = corrected_vs_truth(d / "data", key)
                    print(f"   reference corrected_mg_kg vs truth_mg_kg, non-split samples: worst {wt:.3f} ({wtid}), "
                          f"against a {pol['corrected_tolerance']:.2f} tolerance")
                    continue
                for name, (lst, split) in out.items():
                    res.setdefault(name, []).append(score(lst, split, key, pol, limit))
        print(f"== {label}, {a.seeds} seeds")
        print(f"   {'route':22s} {'precision':24s} {'recall':24s} {'worst split err':24s} {'p&r':>5s} {'split':>5s} {'agree':>5s} {'all':>5s}")
        for name, v in res.items():
            c = list(zip(*v))
            pr = sum(1 for p, r, *_ in v if p >= pol["minimum_precision"] and r >= pol["minimum_recall"])
            sp = sum(1 for w in c[2] if w <= pol["split_check_tolerance"])
            print(f"   {name:22s} {fmt(c[0]):24s} {fmt(c[1]):24s} {fmt(c[2]):24s} {pr:3d}/{len(v)} {sp:3d}/{len(v)} {sum(c[3]):3d}/{len(v)} {sum(c[4]):3d}/{len(v)}")


if __name__ == "__main__":
    main()
