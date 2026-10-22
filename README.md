# Soil Lead Screening (Per-Batch Instrument Calibration in TypeScript)

An environmental consultancy has a contract lab's export for a soil survey and needs the list of samples over the 200 mg/kg lead limit rebuilt before it goes to the council. The export holds instrument results in run order (samples and certified reference material controls interleaved), the certified values, a sample register, a policy file, and a dozen split samples, eight of which carry a reference lab's confirmatory figure. The agent writes one TypeScript file, `/app/screen/src/screen.ts`, using only node's standard modules and no network, that takes `<data-dir> <output-json>` and writes `over_limit` (the over-limit sample ids), `split_check` (a figure for each split sample) and `corrected_mg_kg` (a corrected figure for every sample).

## What makes it hard

The lab's own count - 172 of 480 over the limit - is read straight off the results column, and that column is not a concentration. Every batch of 24 digests sits on its own scale (an offset of tens of mg/kg and a gain several percent either way), which is why each batch runs two reference materials at its head and one again at its end.

- **Per-batch correction.** Raw results score 0.872 precision / 0.811 recall; one line fitted through every control in the run scores 0.855 / 0.827. Correcting each reading from its batch's own three control readings scores 0.989 / 0.984. Across 20 generated surveys the raw list passes both bars 0 times, the single line once, and the per-batch correction 20 times. Correcting only the offset lists well but misses a split sample beyond tolerance.
- **Span drift within a batch.** The instrument's span falls as the batch runs while the zero holds; the repeat control at the end is the drift check. Pinning on the head pair, fitting a three-point line, or taking the repeat/head ratio (forgetting the zero) all pass the shipped survey, where drift is 1-10%, and all fail the hidden one, where it is 8-34%.
- **Export facts that bite only on the hidden survey.** Rejected readings (flag `R`) stay in the file and are re-run later; the hottest digests were diluted 1 in 5; the lab reports wet weight while the limit is dry weight, with moisture in the sample register. On the shipped survey (samples air-dried, 1-4% moisture) ignoring moisture still passes; on the hidden one (10-30%) recall drops to 0.612.
- **A second, unseen survey.** A former gasworks with a 300 mg/kg limit, different reference materials, batches of 20 and 26 batches. Raw results there score 0.970 / 0.376, so neither a carried-over correction nor no correction passes.

The code itself is small; the difficulty is reading the control rows for what they are.

## How it's graded

The verifier runs in a separate, offline container. It deletes everything under `src/` except `screen.ts`, compiles that file with its own `tsc` settings as an unprivileged user, and runs it on the shipped survey and then on the hidden second survey (whose data README is withheld from the program). 25 checks: the five shipped files unchanged by sha256, then on each run:

- Output shape; `over_limit` ids valid and unique; `split_check` and `corrected_mg_kg` complete and finite.
- Precision and recall of `over_limit` against the reference lab's confirmation, at the policy's bars (0.90 / 0.90 shipped; 0.88 / 0.92 hidden).
- Each split figure within `split_check_tolerance` of the lab's figure (0.15 / 0.22), including four split samples whose lab figure is blank in the export so it cannot be copied.
- Every `corrected_mg_kg` within `corrected_tolerance` of the true concentration (0.30 / 0.44), and consistent with `split_check` and with `over_limit` for every sample.

Anti-cheat: all system executables except node are closed to the build user while the script runs; everything in the project but the compiled program is root-owned and unreadable during the run; stray files in the export directory are removed; the two runs use different output paths; outputs are read with `O_NOFOLLOW`; keys are root-only and `/tests` is closed (run scored 0 if reachable); pytest runs by full path with `-P`. The task.toml verification write-up lists the one-change variants of the reference used to confirm each wrong reading scores 0.

## Repository layout

- `instruction.md` - the task prompt given to the agent.
- `task.toml` - metadata, difficulty/solution/verification write-ups, timeouts and network policy.
- `environment/` - agent image: `Dockerfile`, the TypeScript stub, `tsconfig.json` and `build.sh` in `screen/`, and the survey export in `data/`.
- `solution/` - reference `screen.ts` and `solve.sh`, the generator `gen_batches.py` (rebuilds both surveys and keys byte for byte), and `calibrate.py`, which reproduces the figures above.
- `tests/` - verifier image, `test.sh`, `test_outputs.py`, the verifier's `graded_tsconfig.json`, the shipped key (`golden/`) and the hidden survey with its key (`hidden/`).

## Running it

Requires Docker and Harbor (`uv tool install harbor` or `pip install harbor`). From the repo root:

```
harbor run -p . -a oracle
```

runs the reference solution through the verifier (should score reward 1). To try an agent instead:

```
harbor run -p . -a <agent> -m <model>
```

for example `-a claude-code`.

---

Task design, data generators, reference solution and verifier by Audrey Pope.
