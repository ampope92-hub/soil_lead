# Salford former gasworks, soil lead survey, lab export

Five files from the contract lab's results folder for the survey. The four csv files come out of
the lab's system with CRLF line endings, a carriage return before every line feed.

## results.csv

Every position the instrument ran, in run order: `batch`, `run_date`, `position` within the
batch, `sample_id`, `type`, `lead_mg_kg`, the instrument result in mg/kg of the soil as it arrived, `dilution`
and `flag`.
`type` is `sample` for a survey sample and `control` for a certified reference material, in which
case `sample_id` is the material's name. Samples were digested and run in batches of 20, and the
lab runs the two reference materials at the head of every batch and one of them again at the end,
as it always has. The results are the raw instrument results as the instrument reported them.
Each batch is digested and read as its own run, and a run carries its own zero and its own span.
What the instrument reports for any cup, control or sample alike, is the lead in that cup scaled
by the span the instrument had at that cup's position and shifted by the zero, so the same soil
reads differently from one batch to the next. The zero holds through a run. The span does not: it
falls away as a batch goes through, digest after digest, by the same amount from each position to
the next, so a cup read late in a batch reads lower than the same cup would have read at the head.
The three control readings in a batch are readings of that instrument at their own positions like
any other, and between them they settle the batch: the two materials at the head pin where its
scale starts, and the repeat of the first material at the end, the lab's drift check, shows how
far the span had fallen between its head cup and the repeat, the zero being the same for both
readings. Nothing else in a batch is known, so a batch's zero, its span and its fall are whatever
those three readings say they are, and the same three give the span at every sample position
between.

`flag` is blank on a reading the lab accepted and `R` on one it rejected: a short pour, the wrong
cup in the rack, that kind of thing. A rejected reading stays in the export and the lab uses it for
nothing. A rejected control was run again in the position straight after it, and that repeat is the
reading the lab's own calibration stands on; where the two cups at the head of a batch were the
wrong way round, both were rejected and both run again, so that batch opens with four control rows.
A rejected sample was run again later in the run, in a later batch, and the later row is the lab's
result for that sample, so its id appears twice in the file. Six control readings and ten sample
readings in this export carry `R`.

`dilution` is the factor a digest was diluted by before it went on the instrument, 1 for nearly
every row. The hottest digests were too strong for the instrument's range and were run at 1 in 5, so
their `dilution` is 5 and the reading in `lead_mg_kg` is the reading of the diluted digest, not of
the soil: the lab's figure for the sample is the reading, on the certified scale, times the factor.
Eighteen digests in this export were run diluted.

The lab digests a portion of each sample as it arrived, water and all, and `lead_mg_kg` is on
that basis: lead per kilogram of the soil as received. The assessment limit in policy.json, the
certified values of the reference materials, which are dried powders, and every figure the
reference lab returns are dry weight, lead per kilogram of dry soil. The water in each sample is in
the register, `moisture_pct` in samples.csv, measured by the lab on a separate portion of the same
sample and given as a percentage of its mass as received. The water carries none of the lead, so
what the instrument found in a kilogram as received all sits in the dry soil left once that water
is gone, and dry soil is what the reference lab's kilogram is made of. These samples went to the lab as they
came out of the ground, in May, and the made ground on this site holds a good deal of water.

## reference_materials.csv

The two certified reference materials the lab ran: `material`, `certified_lead_mg_kg` and the
certificate's `uncertainty_mg_kg`.

## samples.csv

The survey register: `sample_id`, the sampling `plot` on the site grid, the `depth_cm` it was
taken at, and `moisture_pct`, the water in the sample as received, as a percentage of its
as-received mass, measured by the lab on a separate portion of it.

## split_checks.csv

The dozen samples a second portion of which was sent to the reference lab, the external check
the survey carries: `sample_id`, the `batch` it was run in, `our_reading_mg_kg` as it appears in
the results column, and `reference_lab_mg_kg`, the figure the reference lab returned for the same
soil. The reference lab reports the concentration in the sample, dry weight; our column reports
what the instrument read that day, on the soil as received. Those results are what this survey is
held to: the correction of the instrument column that puts these samples where the reference lab
has them, within the policy's tolerance, is the one the survey is screened with. Four of the
twelve are still with the reference lab, so their `reference_lab_mg_kg` is blank, and they are
held to the lab's figures the same way when they come. Our reading and the batch are there for
all twelve.

## policy.json

| key | meaning |
|---|---|
| site | the survey |
| limit_mg_kg | the assessment limit a sample is reported against |
| minimum_precision | of the samples listed as over the limit, the share that have to be confirmed over it |
| minimum_recall | of the samples confirmed over the limit, the share the list has to hold |
| split_check_tolerance | how far a split-sample figure may sit from the reference lab's, as a fraction of it |
| corrected_tolerance | how far a corrected figure for any other sample may sit from the reference lab's confirmed concentration, as a fraction of it |
| samples_over_limit_as_reported | how many accepted results in results.csv are over the limit as they stand, dilution applied |

## From the lab's cover note

66 of the 520 samples came back over the 300 mg/kg limit, counted straight off the accepted rows of
the results column with the dilution applied, and the lab has asked which grid squares the developer
wants excavated first.
