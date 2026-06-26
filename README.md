# Dialpad Metrics

Pulls call-center analytics from the Dialpad Stats API, trims the export to the
columns we care about, aggregates multiple call centers into one daily CSV, and
prints a period summary.

> For column-level definitions and how each metric is calculated, see
> [`DIALPAD_STATS_REFERENCE.md`](./DIALPAD_STATS_REFERENCE.md).

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Create a `.env` file with your API key:
   ```
   API_KEY=your_dialpad_api_key
   ```

## Usage

Pass call-center IDs directly:

```bash
python main.py --target-ids 2349823 9823749
```

…or point at a config file:

```bash
python main.py --config configs/test.json
```

Output is written to `output.csv` (one combined row per day).

## Creating a config

Configs live in `configs/` and hold the call-center IDs to pull. Structure:

```json
{
  "cc_ids": [2349823, 9823749, 123456]
}
```

- `cc_ids` — **required.** A list of Dialpad call-center IDs to pull and aggregate.

To find valid IDs, run the script once — it writes every call center's
`id: name` mapping to `cc_ids.json`.

## How call-center stats are aggregated

All listed call centers are pulled separately, then **summed by day** into a
single output. The `summed_cc_ids` column records which IDs went into each row.

Columns fall into two buckets:

- **Additive** — counts and total durations (`all_calls`, `abandoned`,
  `talk_duration`, …) are simply summed across call centers.
- **Derived** — averages (`asa`, `acd`, `aht`, `avg_*_duration`) **cannot** be
  summed or averaged-of-averages. They are recomputed from summed totals:
  - `avg_*_duration` → recover each row's call count (`total / avg`), sum the
    totals and counts separately, then divide.
  - `asa` / `acd` / `aht` → carry a weighted numerator (`value × weight`), sum,
    then divide by the summed weight.

`abandon_rate` is computed per day as `(abandoned - short_abandoned) / inbound_calls`.

> **Note:** recovered counts rely on Dialpad's rounded averages, so combined
> figures are very close but not bit-exact. Use `export_type=records` if you
> need exact denominators.

## How the request loop works

The Stats API is asynchronous — you submit a job, then poll for the result.

1. **Submit** one processing job per call-center ID; Dialpad returns a
   `request_id` for each.
2. **Poll** each `request_id` until its status is `complete`, then fetch the
   CSV from the returned `download_url`.
3. A status of `failed` raises an error.

> **Caching gotcha:** Dialpad caches results for ~3 hours. An identical request
> body returns the *same* cached CSV instantly. Change a parameter (e.g.
> `days_ago_end`) or wait out the window to force fresh processing.

## Additional notes

- TODO: document the `--days-start` / `--days-end` flags once wired into the request.
- `cc_ids.json` is regenerated on every run.
- Output rounding is left to the consumer — full precision is kept on disk.
