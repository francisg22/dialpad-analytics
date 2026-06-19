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

parser.add_argument("--target-id", type=list, required=True, nargs="+",
                    help="Call center IDs")
parser.add_argument("--days-start", type=int, defualt=1,
                    help="Bound on how recent the stats are pulled, default is 1")
parser.add_argument("--days-end", type=int, defualt=31,
                    help="Bound on how long ago the stats are pulled, default is 31")


#dialpad only processes new requests after 3 hours, requests with the same
#post body return a cached csv (or the link to the same csv)
#have to change body params or wait 3 hours
def run_stats(target_ids, **body):
    """Initiate multiple stats jobs, poll until done, return the results."""
    results = {}
    request_ids = {}
    for id in target_ids:
        body["target_id"] = id
        proc = client.stats.initiate_processing(request_body=body)
        request_ids[id] = proc["request_id"]

    for cc_id, request_id in request_ids.items():
        while True:
            result = client.stats.get_result(request_id)
            status = result.get("status")
            if status == "complete":
                # SDK gives you a URL, not the bytes — fetch it yourself
                results[cc_id] = requests.get(result["download_url"]).text 
                break
            if status == "failed":
                #maybe just fail for the one cc
                raise RuntimeError("Stats job failed")
            time.sleep(3)
    return results

#print call center and office ids
# for cc in client.call_centers.list():
#     print(cc["id"], cc["name"])
# for office in client.offices.list():
#     print(office["id"], office["name"])

args = parser.parse_args()
# Group export: one row per call center with period totals — ideal for monthly KPIs
csv_text = run_stats(
    target_ids=args.target_ids,
    stat_type="calls",
    export_type="stats",
    target_type="callcenter",
    target_id=-1,
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