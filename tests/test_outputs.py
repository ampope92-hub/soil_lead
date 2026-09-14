"""Verifier for the over-limit list.

test.sh compiles the agent's TypeScript itself, runs the program once on the export that shipped
and once on another survey's export it has never seen, and captures each over_limit.json
root-only. This module only reads those captures and the keys under /opt: the samples the
reference lab's confirmatory analysis found over the limit. It never runs agent code.

Every bar here is stated in instruction.md, and the same bars apply to both runs.
"""
import csv
import hashlib
import json
import math
import os
import pathlib

import pytest

SHIPPED_RUN = pathlib.Path("/opt/run_shipped.json")
HIDDEN_RUN = pathlib.Path("/opt/run_hidden.json")
SHIPPED_KEY = pathlib.Path("/opt/golden/key.json")
HIDDEN_KEY = pathlib.Path("/opt/hidden/key.json")
SHIPPED_DATA = pathlib.Path("/app/data")
HIDDEN_DATA = pathlib.Path("/opt/hidden/data")

SHIPPED_SHA = {
    "results.csv": "be080bde2032eaa301a552431751e3631bdf771aa92e0ba189faf855819a523c",
    "reference_materials.csv": "6e4085ea07ed57c6932dc386425ee43960169959efb179cc46c18ec968f410d4",
    "samples.csv": "b0d1f7102c69edae6de9fa241b3929c749ec1c88dcd78052aae7b5bf51f214b3",
    "policy.json": "f259e541045528f8ecb072a59305e11d141e6c30bcce8fb06efcbd3865fe0216",
    "split_checks.csv": "ec0240c26caefc9a89ad755ec54e773ba3128842b6f76641f9379c8b709586dd",
}

RUNS = [
    pytest.param(SHIPPED_RUN, SHIPPED_KEY, SHIPPED_DATA, id="shipped"),
    pytest.param(HIDDEN_RUN, HIDDEN_KEY, HIDDEN_DATA, id="hidden"),
]


def _open(path, mode="r"):
    """Open without following a final symlink, so a read can never be redirected into /opt."""
    return os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), mode)


def _sha(path):
    with _open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _load(path):
    assert path.exists() and path.stat().st_size > 0, (
        f"{path.name}: no over_limit.json was written for this run"
    )
    with _open(path) as fh:
        text = fh.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        pytest.fail(f"{path.name}: not valid JSON ({e}): {text[:200]!r}")


def _key(path):
    with open(path) as fh:
        return json.load(fh)


def _policy(data_dir):
    with open(data_dir / "policy.json") as fh:
        return json.load(fh)


def _sample_ids(data_dir):
    with open(data_dir / "results.csv", newline="") as fh:
        return {row["sample_id"] for row in csv.DictReader(fh) if row["type"] == "sample"}


def test_shipped_export_unmodified():
    """The five files in /app/data are byte-identical to what shipped."""
    for name, sha in SHIPPED_SHA.items():
        assert _sha(SHIPPED_DATA / name) == sha, f"{name} was altered"


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_report_shape(run_path, key_path, data_dir):
    """One object with exactly the keys over_limit, split_check and corrected_mg_kg: an array of
    sample ids from that run's results.csv with no repeats, a figure for every split-check sample,
    and a figure for every sample in results.csv."""
    r = _load(run_path)
    assert isinstance(r, dict) and set(r) == {"over_limit", "split_check", "corrected_mg_kg"}, (
        f"{run_path.name}: expected exactly the keys over_limit, split_check and corrected_mg_kg"
    )
    assert isinstance(r["over_limit"], list), f"{run_path.name}: over_limit is not an array"
    assert all(isinstance(x, str) for x in r["over_limit"]), f"{run_path.name}: over_limit must hold sample ids"
    assert len(r["over_limit"]) == len(set(r["over_limit"])), f"{run_path.name}: a sample is listed more than once"
    unknown = sorted(set(r["over_limit"]) - _sample_ids(data_dir))
    assert not unknown, f"{run_path.name}: {len(unknown)} listed ids are not samples in results.csv, e.g. {unknown[:5]}"


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_precision_against_the_reference_lab(run_path, key_path, data_dir):
    """Of the samples listed, at least the policy's minimum_precision were confirmed over the limit."""
    listed = _load(run_path)["over_limit"]
    over = set(_key(key_path)["over_limit"])
    bar = _policy(data_dir)["minimum_precision"]
    hits = sum(1 for s in listed if s in over)
    # An empty list is a list the contract allows. It has no unconfirmed sample on it, so it meets
    # this bar as it stands; it is the recall bar that says whether it should have been empty.
    precision = hits / len(listed) if listed else 1.0
    assert precision >= bar, (
        f"{run_path.name}: {hits} of the {len(listed)} listed samples were confirmed over the limit, precision "
        f"{precision:.3f}, under the {bar:.2f} the policy requires. An instrument result is not a concentration"
    )


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_recall_against_the_reference_lab(run_path, key_path, data_dir):
    """Of the samples confirmed over the limit, the list holds at least the policy's minimum_recall."""
    listed = set(_load(run_path)["over_limit"])
    over = _key(key_path)["over_limit"]
    bar = _policy(data_dir)["minimum_recall"]
    hits = sum(1 for s in over if s in listed)
    recall = hits / len(over)
    assert recall >= bar, (
        f"{run_path.name}: the list holds {hits} of the {len(over)} samples confirmed over the limit, recall "
        f"{recall:.3f}, under the {bar:.2f} the policy requires"
    )


def _split_rows(data_dir):
    with open(data_dir / "split_checks.csv", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_split_check_is_reported_for_every_split_sample(run_path, key_path, data_dir):
    """split_check carries a finite number for exactly the samples in split_checks.csv."""
    reported = _load(run_path)["split_check"]
    assert isinstance(reported, dict), f"{run_path.name}: split_check is not an object"
    want = {row["sample_id"] for row in _split_rows(data_dir)}
    assert set(reported) == want, (
        f"{run_path.name}: split_check must carry exactly the {len(want)} samples in split_checks.csv"
    )
    for sid, v in reported.items():
        assert isinstance(v, (int, float)) and not isinstance(v, bool), (
            f"{run_path.name}: split_check[{sid}] is not a number"
        )
        assert math.isfinite(v), f"{run_path.name}: split_check[{sid}] is not finite"


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_split_check_reproduces_the_reference_lab(run_path, key_path, data_dir):
    """Every split sample's reported figure lands within split_check_tolerance, as a fraction, of
    the figure the reference lab returned for the same soil. The lab figures come from the key,
    not from the export, so the four rows whose column is blank cannot be copied."""
    reported = _load(run_path)["split_check"]
    tol = _policy(data_dir)["split_check_tolerance"]
    lab_all = _key(key_path)["split_lab_mg_kg"]
    worst, worst_id = 0.0, None
    for row in _split_rows(data_dir):
        sid = row["sample_id"]
        lab = float(lab_all[sid])
        err = abs(float(reported[sid]) - lab) / lab
        if err > worst:
            worst, worst_id = err, sid
    assert worst <= tol, (
        f"{run_path.name}: {worst_id} is {worst:.3f} away from the reference lab's figure, outside the "
        f"{tol:.2f} the policy allows. A correction that cannot manage the samples we already have both "
        f"numbers for is not one to screen the rest of the survey with"
    )


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_the_pending_split_samples_are_not_copied(run_path, key_path, data_dir):
    """The four split samples whose reference_lab_mg_kg is blank in the export are graded too, so a
    program that copies the lab column and leaves the blanks alone cannot pass."""
    reported = _load(run_path)["split_check"]
    key = _key(key_path)
    tol = _policy(data_dir)["split_check_tolerance"]
    blank = {row["sample_id"] for row in _split_rows(data_dir) if not row["reference_lab_mg_kg"].strip()}
    assert blank == set(key["split_pending"]), (
        f"{run_path.name}: the export's blank split rows are not the ones the key expects"
    )
    for sid in sorted(blank):
        lab = float(key["split_lab_mg_kg"][sid])
        err = abs(float(reported[sid]) - lab) / lab
        assert err <= tol, (
            f"{run_path.name}: {sid} has no reference figure in the export and the reported value is "
            f"{err:.3f} away from what the lab returned, outside the {tol:.2f} the policy allows"
        )


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_the_split_figures_agree_with_the_list(run_path, key_path, data_dir):
    """The two keys come out of one correction, so they have to agree with each other: a split
    sample reported above the limit is in over_limit, and one reported at or below it is not.
    Without this the split figures could be computed properly while the list was arrived at some
    other way, which is not the correction being asked for."""
    report = _load(run_path)
    listed = set(report["over_limit"])
    reported = report["split_check"]
    limit = _policy(data_dir)["limit_mg_kg"]
    for sid in sorted(reported):
        above = float(reported[sid]) > limit
        if above and sid not in listed:
            pytest.fail(
                f"{run_path.name}: {sid} is reported at {float(reported[sid]):.2f}, above the "
                f"{limit:.1f} limit, but it is not in over_limit"
            )
        if not above and sid in listed:
            pytest.fail(
                f"{run_path.name}: {sid} is reported at {float(reported[sid]):.2f}, at or below the "
                f"{limit:.1f} limit, but it is in over_limit"
            )


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_the_corrected_figure_decides_every_sample_on_the_list(run_path, key_path, data_dir):
    """The instruction says the same corrected figure decides every sample on the list, not only
    the ones split_checks.csv names. corrected_mg_kg has to carry a finite number for every sample
    in results.csv, and over_limit has to agree with it for every one of them: a sample reported
    above limit_mg_kg is listed, and one reported at or below it is not. A report that reasons
    correctly about the split samples and then quietly drops other over-limit samples out of
    over_limit, while still reporting a corrected figure that says they are over, fails here."""
    report = _load(run_path)
    listed = set(report["over_limit"])
    corrected = report["corrected_mg_kg"]
    limit = _policy(data_dir)["limit_mg_kg"]
    ids = _sample_ids(data_dir)
    assert isinstance(corrected, dict) and set(corrected) == ids, (
        f"{run_path.name}: corrected_mg_kg must carry exactly the {len(ids)} samples in results.csv"
    )
    for sid in sorted(ids):
        v = corrected[sid]
        assert isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v), (
            f"{run_path.name}: corrected_mg_kg[{sid}] is not a finite number"
        )
        above = float(v) > limit
        if above and sid not in listed:
            pytest.fail(
                f"{run_path.name}: {sid}'s corrected_mg_kg is {float(v):.2f}, above the {limit:.1f} "
                f"limit, but it is not in over_limit"
            )
        if not above and sid in listed:
            pytest.fail(
                f"{run_path.name}: {sid}'s corrected_mg_kg is {float(v):.2f}, at or below the "
                f"{limit:.1f} limit, but it is in over_limit"
            )


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_corrected_agrees_with_split_check_for_split_samples(run_path, key_path, data_dir):
    """split_check and corrected_mg_kg are the same correction seen twice, so for the samples
    split_checks.csv names the two figures have to be the same number. A program that reports a
    genuine split_check but only a boundary marker in corrected_mg_kg, or the reverse, fails
    here even though each field passes its own shape and boundary checks in isolation."""
    report = _load(run_path)
    reported = report["split_check"]
    corrected = report["corrected_mg_kg"]
    for sid in sorted(reported):
        a = float(corrected[sid])
        b = float(reported[sid])
        assert math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6), (
            f"{run_path.name}: corrected_mg_kg[{sid}] is {a:.4f} but split_check[{sid}] is "
            f"{b:.4f}; one correction has to produce both figures"
        )


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_corrected_matches_the_reference_lab_for_ordinary_samples(run_path, key_path, data_dir):
    """corrected_mg_kg has to be the calibrated concentration, not a marker of which side of the
    limit a sample landed on. For every sample split_checks.csv does not name, it is held to the
    reference lab's true confirmed concentration, at the policy's corrected_tolerance: an
    ordinary sample is compared to the concentration itself rather than to a second noisy
    reading of it, but it is corrected from only one batch's own three control readings, which
    can miss by more than the twelve split samples happen to."""
    report = _load(run_path)
    corrected = report["corrected_mg_kg"]
    truth = _key(key_path)["truth_mg_kg"]
    tol = _policy(data_dir)["corrected_tolerance"]
    split_ids = {row["sample_id"] for row in _split_rows(data_dir)}
    worst, worst_id = 0.0, None
    for sid, t in truth.items():
        if sid in split_ids or sid not in corrected:
            continue
        err = abs(float(corrected[sid]) - float(t)) / float(t)
        if err > worst:
            worst, worst_id = err, sid
    assert worst <= tol, (
        f"{run_path.name}: {worst_id}'s corrected_mg_kg is {worst:.3f} away, as a fraction of the "
        f"reference lab's confirmed concentration, outside the {tol:.2f} allowed. A corrected "
        f"figure has to be a concentration, not a marker of which side of the limit it falls on"
    )


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_no_sample_sits_on_the_limit(run_path, key_path, data_dir):
    """The instruction says no sample sits exactly on the limit, so nothing here turns on whether
    the comparison is strict. This holds the shipped data to that, since a survey that broke it
    would start grading a decision the contract does not settle."""
    limit = _policy(data_dir)["limit_mg_kg"]
    on_it = [s for s, v in _key(key_path)["truth_mg_kg"].items() if abs(float(v) - limit) < 1e-9]
    assert not on_it, (
        f"{run_path.name}: {on_it[:3]} sit exactly on the {limit:.1f} limit, so the strict-versus-"
        f"inclusive reading would decide them and the contract does not settle it"
    )


@pytest.mark.parametrize("run_path,key_path,data_dir", RUNS)
def test_every_sample_has_one_accepted_reading(run_path, key_path, data_dir):
    """No sample has more than one reading the lab accepted, which is what the instruction promises
    and what makes one figure per id well defined. The rows the lab rejected, R in the flag column,
    are its discards and do not count."""
    seen = {}
    with open(data_dir / "results.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["type"] != "sample" or row["flag"].strip() == "R":
                continue
            seen[row["sample_id"]] = seen.get(row["sample_id"], 0) + 1
    repeats = sorted(k for k, n in seen.items() if n > 1)
    assert not repeats, f"{data_dir}: more than one accepted reading, so the figure is ambiguous: {repeats[:5]}"
    with open(data_dir / "samples.csv", newline="") as fh:
        register = {row["sample_id"] for row in csv.DictReader(fh)}
    missing = sorted(register - set(seen))
    assert not missing, f"{data_dir}: samples in the register with no accepted reading: {missing[:5]}"

