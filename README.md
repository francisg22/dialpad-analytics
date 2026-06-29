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

Pass in a config file (more about creating below)

```bash
python main.py --config configs/test.json
```

Output is written to `output.csv`. Each row is a day that contains all the combined stats from all the call centers.

## Creating a config

Configs live in `configs/` and hold the call-center IDs to pull plus any
request options. A config is simply just a json file with the below text inside it. Only `cc_ids` is required; everything else falls back to a
default if omitted.

Minimal config:

```json
{
  "cc_ids": [2349823, 9823749, 123456]
}
```

Full config with all optional keys set to their defaults:

```json
{
  "cc_ids": [2349823, 9823749, 123456],
  "days_ago_start": 1,
  "days_ago_end": 31,
  "stat_type": "calls",
  "export_type": "stats",
  "target_type": "callcenter",
  "group_by": "date",
  "timezone": "America/Phoenix"
}
```

| Key | Required | Default | Notes |
|-----|----------|---------|-------|
| `cc_ids` | **Yes** | — | List of Dialpad call-center IDs to pull and aggregate. |
| `days_ago_start` | No | `1` | More-recent bound of the range, in days back from today (`1` = yesterday). Must be the smaller number. |
| `days_ago_end` | No | `31` | Further-back bound, in days back from today. Must be the larger number. |
| `stat_type` | No | `calls` | `calls`, `csat`, `dispositions`, `onduty`, `recordings`, `screenshare`, `texts`, `voicemails`. |
| `export_type` | No | `stats` | `stats` (pre-aggregated) or `records` (one row per event). |
| `target_type` | No | `callcenter` | `callcenter`, `department`, `office`, `user`, `room`, `coachinggroup`, `coachingteam`, `staffgroup`, `unknown`. |
| `group_by` | No | `date` | `date`, `group`, or `user`. |
| `timezone` | No | `America/Phoenix` | tz database name used to bucket data by day. |

> The aggregation logic in this script assumes the default
> `stat_type=calls`, `export_type=stats`, `group_by=date` shape. Changing these
> changes the returned columns and may break the `rows_to_keep` trim and the
> per-day summing. See [`DIALPAD_STATS_REFERENCE.md`](./DIALPAD_STATS_REFERENCE.md)
> for the full meaning of each parameter.

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

The API is rate limited at 200 POSTs per hour. The way each call center stats are retrieved is that the script first has to POST, and then GET the csv back from the API. So the script is limited by the 200 POSTs per hour for grabbing lots of call centers. The GET is rate limited at 1200 per minute, so it is not an issue.

## Additional notes

- Need to verify if the way each average is calculated is fine
- Each output CSV starts with a column where each row is the same, it is just the list of call center IDs used. It is there to keep the metadata tightly coupled with the actual data.
- Right now the csv has a lot of columns sliced off, modify rows_to_keep to get more columns or less columns
- Script outputs to stdout just for visibility and to show its done, not really needed.
