from dialpad import DialpadClient
import time
import requests
import io
import pandas as pd
from dotenv import load_dotenv
import os
import argparse
import json

load_dotenv()
client = DialpadClient(token=os.getenv("API_KEY"))

parser = argparse.ArgumentParser(description="Pull Dialpad API Analytics")


parser.add_argument("--config", type=str,
                    help="Path to config file")

#can be done with office ids too, but not as useful to me right now
#client.offices.list()
ccs = {cc["id"]: cc["name"] for cc in client.call_centers.list()}
with open("cc_ids.json", "w") as f:
    json.dump(ccs, f, indent=2)

#dialpad only processes new requests after 3 hours, requests with the same
#post body return a cached csv (or the link to the same csv)
#have to change body params or wait 3 hours or responses will be fast and the exact same
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
                #maybe just fail for the one cc, continue checking
                raise RuntimeError("Stats job failed")
            time.sleep(3)
    return results

args = parser.parse_args()

with open(args.config) as f:
    j = json.load(f)

id_list = j["cc_ids"] #required, script will not run without
#below are not required in config, defaults are 2nd arg
#will run without the below args in config
#more info in DIALPAD_STATS_REFERENCE.md about the args
days_ago_start = j.get("days_ago_start", 1)
days_ago_end = j.get("days_ago_end", 31)
#stat_type types - calls, csat, dispositions, onduty, recordings, screenshare, texts, voicemails
stat_type = j.get("stat_type", "calls")
#export types - stats, records
export_type = j.get("export_type", "stats")
#target types - callcenter, department, office, user, room, 
# coachinggroup, coachingteam, staffgroup, unknown
target_type = j.get("target_type", "callcenter")
#group by types - date, group, user
group_by = j.get("group_by", "date")
#timezone - string (tz database name, e.g. America/Phoenix)
timezone = j.get("timezone", "America/Phoenix")

summed = ";".join(str(i) for i in id_list)
results = run_stats(
    target_ids=id_list,
    stat_type=stat_type,
    export_type=export_type,
    target_type=target_type,
    target_id=-1,
    group_by=group_by,    
    days_ago_start=days_ago_start,
    days_ago_end=days_ago_end,
    timezone=timezone,
)

rows_to_keep = [
    "date",
    "all_calls",
    "inbound_calls",
    "outbound_calls",
    "missed",
    "abandoned",
    "short_abandoned",
    "voicemails",
    "handled",
    "answered",
    "minutes",
    "acd",
    "aht",
    "asa",
    "inbound_minutes",
    "outbound_minutes",
    "service_level",
    "callbacks_requested",
    "callbacks_completed",
    "callbacks_cancelled",
    "talk_duration",
    "avg_talk_duration",
    "queued_duration",
    "avg_queued_duration",
    "wrapup_duration",
    "avg_wrapup_duration",
    "hold_duration",
    "avg_hold_duration",
]

#essentially stacks the csvs on top of eachother, to all of them are together in 
#one data structure
frames = [pd.read_csv(io.StringIO(t))[rows_to_keep] for t in results.values()]
df = pd.concat(frames, ignore_index=True)

#since total / count = average, do total / average to get the count, dialpad
#does not specify anywhere (at least, according to claude) in the docs the specific counts used
for col in ["talk", "queued", "wrapup", "hold"]:
    avg = df[f"avg_{col}_duration"]
    df[f"_{col}_n"] = df[f"{col}_duration"] / avg.where(avg != 0)

#instead of straight up averaging the 3 averages, compute weighted averages
#probably needs to change, not really another good way to aggregate this though.
#only other way would be compute it from all call data - technichally could be done but not sure how
#dialpad reports that
df["_asa_num"] = df["asa"] * df["answered"]
df["_aht_num"] = df["aht"] * df["handled"]
df["_acd_num"] = df["acd"] * df["handled"]

#Takes csvs and sums them together
g = df.groupby("date").sum(numeric_only=True)

#getting the new averages based off the calculated count for each located in
#the _n col for each of the 4 cols
for col in ["talk", "queued", "wrapup", "hold"]:
    g[f"avg_{col}_duration"] = g[f"{col}_duration"] / g[f"_{col}_n"] 

#each _num col will have the scaled average by the # of answered or handled
#so, those cols get summed by the groupby in g, so we then divide by total # of answered and handled
#to get the weighted average for the aggregate
#again, this will probably need to be changed
g["asa"] = g["_asa_num"] / g["answered"].where(g["answered"] != 0)
g["aht"] = g["_aht_num"] / g["handled"].where(g["handled"] != 0)
g["acd"] = g["_acd_num"] / g["handled"].where(g["handled"] != 0)

# Abandon rate per day = (abandoned - short_abandoned) / inbound.
g["abandon_rate"] = (g["abandoned"] - g["short_abandoned"]) / g["inbound_calls"].where(g["inbound_calls"] != 0)

g = g.round(3)
#below is unimportant, mostly formatting stuff done by claude
g["summed_cc_ids"] = summed
g = g.reset_index()
out_cols = ["summed_cc_ids", "date"] + [c for c in rows_to_keep if c != "date"] + ["abandon_rate"]
g[out_cols].to_csv("output.csv", index=False)

call_volume  = int(g["all_calls"].sum())
abandoned    = int(g["abandoned"].sum())
short_ab     = int(g["short_abandoned"].sum())
inbound      = int(g["inbound_calls"].sum())
answered     = int(g["answered"].sum())

asa_minutes  = (g["_asa_num"].sum() / answered) if answered else 0
asa_seconds  = asa_minutes * 60
abandon_rate = (abandoned - short_ab) / inbound if inbound else 0

print(f"Call centers summed: {summed}")
print(f"Period volume: {call_volume}")
print(f"Avg speed to answer: {asa_seconds:.0f}s ({asa_minutes:.2f} min)")
print(f"Abandon rate: {abandon_rate:.1%}")