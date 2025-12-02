#!/usr/bin/env python3
"""
Reads JSON logs in data/raw_logs/ and writes analysis/features.csv
"""

import glob
import json
import statistics
import numpy as np
import pandas as pd
from pathlib import Path

RAW_DIR = Path("data/raw_logs")
OUT_DIR = Path("analysis")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_CSV = OUT_DIR / "features.csv"


def inter_key_intervals(ts_list):
    if len(ts_list) < 2:
        return []
    return [ (ts_list[i+1] - ts_list[i]) * 1000.0 for i in range(len(ts_list)-1) ]


def safe_mean(xs):
    return float(statistics.mean(xs)) if xs else 0.0


def safe_std(xs):
    return float(statistics.pstdev(xs)) if xs else 0.0


def autocorr_lag1(xs):
    if len(xs) < 2:
        return 0.0
    x = np.array(xs)
    x = x - x.mean()
    denom = (x * x).sum()
    if denom == 0:
        return 0.0
    return float((x[1:] * x[:-1]).sum() / denom)


rows = []
for path in sorted(glob.glob(str(RAW_DIR / "*.json"))):
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    meta = d.get("meta", {})
    ks = d.get("keystroke_log", [])
    timestamps = [k.get("timestamp") for k in ks if k.get("timestamp") is not None]
    keys = [k.get("key") for k in ks]
    ikis = inter_key_intervals(timestamps)
    chars_typed = sum(1 for k in keys if k not in ("Backspace", "Shift", "Enter"))
    duration_s = (timestamps[-1] - timestamps[0]) if len(timestamps) >= 2 else 0.0
    computed_wpm = (chars_typed / 5.0) / (duration_s / 60.0) if duration_s > 0 else 0.0
    backspaces = sum(1 for k in keys if k == "Backspace")
    burst_fraction = (sum(1 for x in ikis if x < 30.0) / len(ikis)) if ikis else 0.0

    row = {
        "json_file": Path(path).name,
        "profile": meta.get("profile"),
        "site_mode": meta.get("site_mode"),
        "start_time": meta.get("start_time"),
        "end_time": meta.get("end_time"),
        "chars_typed": chars_typed,
        "duration_s": duration_s,
        "computed_wpm": computed_wpm,
        "mean_iki_ms": safe_mean(ikis),
        "std_iki_ms": safe_std(ikis),
        "median_iki_ms": float(statistics.median(ikis)) if ikis else 0.0,
        "min_iki_ms": float(min(ikis)) if ikis else 0.0,
        "max_iki_ms": float(max(ikis)) if ikis else 0.0,
        "backspace_count": backspaces,
        "backspace_rate": backspaces / chars_typed if chars_typed > 0 else 0.0,
        "burst_fraction": burst_fraction,
        "autocorr_lag1": autocorr_lag1(ikis),
        "extracted_wpm": meta.get("extracted_wpm"),
        "extracted_accuracy": meta.get("extracted_accuracy"),
    }
    rows.append(row)

if rows:
    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False)
    print(f"Wrote {len(rows)} rows to {OUT_CSV}")
else:
    print("No JSON logs found in", RAW_DIR)
