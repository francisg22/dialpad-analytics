from dialpad import DialpadClient
import time
import requests
import io
import csv
from dotenv import load_dotenv
import os
import argparse

load_dotenv()
client = DialpadClient(token=os.getenv("API_KEY"))

parser = argparse.ArgumentParser(description="Pull Dialpad API Analytics")

parser.add_argument("--target-id", type=int, required=True, nargs="+",
                    help="Call center IDs")
parser.add_argument("--days-start", type=int, defualt=1,
                    help="Bound on how recent the stats are pulled, default is 1")
parser.add_argument("--days-end", type=int, defualt=31,
                    help="Bound on how long ago the stats are pulled, default is 31")


#dialpad only processes new requests after 3 hours, requests with the same
#post body return a cached csv (or the link to the same csv)
#have to change body params or wait 3 hours
def run_stats(**body):
    """Initiate a stats job, poll until done, return the CSV text."""
    proc = client.stats.initiate_processing(request_body=body)
    request_id = proc["request_id"]

    # Docs recommend waiting ~15-20s before first poll, then every 5-10s
    time.sleep(15)
    while True:
        result = client.stats.get_result(request_id)
        status = result.get("status")
        if status == "complete":
            # SDK gives you a URL, not the bytes — fetch it yourself
            return requests.get(result["download_url"]).text
        if status == "failed":
            raise RuntimeError("Stats job failed")
        time.sleep(8)

#print call center and office ids
# for cc in client.call_centers.list():
#     print(cc["id"], cc["name"])
# for office in client.offices.list():
#     print(office["id"], office["name"])

args = parser.parse_args()
# Group export: one row per call center with period totals — ideal for monthly KPIs
csv_text = run_stats(
    stat_type="calls",
    export_type="stats",
    target_type="callcenter",
    target_id=args.target_id,
    group_by="date",     # period rollup, no per-day rows  
    days_ago_start=1,
    days_ago_end=31,
    timezone="America/Phoenix",
)

rows = list(csv.DictReader(io.StringIO(csv_text)))   # one row per day

call_volume = sum(int(r["all_calls"])     for r in rows)
abandoned   = sum(int(r["abandoned"])     for r in rows)
inbound     = sum(int(r["inbound_calls"]) for r in rows)
answered    = inbound - abandoned
# Dialpad reports `asa` in MINUTES. Weight by answered calls -> period ASA in minutes.
asa_minutes = (
    sum(float(r["asa"]) * (int(r["inbound_calls"]) - int(r["abandoned"])) for r in rows) / answered
    if answered else 0
)
asa_seconds = asa_minutes * 60
abandon_rate = abandoned / inbound if inbound else 0

print(f"Monthly volume: {call_volume}")
print(f"Avg speed to answer: {asa_seconds:.0f}s ({asa_minutes:.2f} min)")
print(f"Abandon rate: {abandon_rate:.1%}")