"""Build the slim national FARS extract the crash layer reads (CR-017).

    python scripts/build_fars_extract.py

Input:  backend/raw_data/crashes/FARS{year}NationalCSV.zip for 2020-2024 (git-ignored), from
        https://static.nhtsa.gov/nhtsa/downloads/FARS/{year}/National/FARS{year}NationalCSV.zip
Output: backend/data/fars_2020_2024_slim.csv.gz (committed; FARS is public-domain US data)

Codes (checked against the *NAME label columns in the 2020 files):
  pedestrian = any person with PER_TYP 5 (Pedestrian)
  cyclist    = any person with PER_TYP 6 (Bicyclist) or 7 (Other Cyclist)
  dark       = LGT_COND 2 (Dark - Not Lighted), 3 (Dark - Lighted), 6 (Dark - Unknown Lighting)
  hour       = HOUR 0-23; 99 (unknown) and 24 become empty
Crashes with sentinel coordinates (LATITUDE 77.7777/88.8888/99.9999, LONGITUD
777.7777/888.8888/999.9999) or missing ones are dropped and counted.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
RAW = BACKEND / "raw_data" / "crashes"
OUT = BACKEND / "data" / "fars_2020_2024_slim.csv.gz"
YEARS = [2020, 2021, 2022, 2023, 2024]

PEDESTRIAN = {5}
CYCLIST = {6, 7}
DARK = {2, 3, 6}
LAT_SENTINELS = {77.7777, 88.8888, 99.9999}
LNG_SENTINELS = {777.7777, 888.8888, 999.9999}
ACCIDENT_COLS = ["ST_CASE", "YEAR", "MONTH", "HOUR", "LATITUDE", "LONGITUD", "FATALS", "LGT_COND"]


def _table(z: zipfile.ZipFile, name: str, cols: list[str]) -> pd.DataFrame:
    members = {m.lower().rsplit("/", 1)[-1]: m for m in z.namelist()}
    return pd.read_csv(z.open(members[name]), encoding="latin-1", usecols=cols, low_memory=False)


def one_year(year: int) -> tuple[pd.DataFrame, int]:
    with zipfile.ZipFile(RAW / f"FARS{year}NationalCSV.zip") as z:
        acc = _table(z, "accident.csv", ACCIDENT_COLS)
        per = _table(z, "person.csv", ["ST_CASE", "PER_TYP"])
    bad = (acc["LATITUDE"].isin(LAT_SENTINELS) | acc["LONGITUD"].isin(LNG_SENTINELS)
           | acc["LATITUDE"].isna() | acc["LONGITUD"].isna())
    acc = acc[~bad]
    ped = set(per.loc[per["PER_TYP"].isin(PEDESTRIAN), "ST_CASE"])
    cyc = set(per.loc[per["PER_TYP"].isin(CYCLIST), "ST_CASE"])
    hour = acc["HOUR"].where(acc["HOUR"].between(0, 23)).astype("Int64")
    out = pd.DataFrame({
        "st_case": acc["ST_CASE"].astype("int64"),
        "year": acc["YEAR"].astype("int64"),
        "month": acc["MONTH"].astype("int64"),
        "hour": hour,
        "lat": acc["LATITUDE"].astype(float).round(6),
        "lng": acc["LONGITUD"].astype(float).round(6),
        "fatalities": acc["FATALS"].astype("int64"),
        "pedestrian": acc["ST_CASE"].isin(ped).astype(int),
        "cyclist": acc["ST_CASE"].isin(cyc).astype(int),
        "dark": acc["LGT_COND"].isin(DARK).astype(int),
    })
    return out, int(bad.sum())


def main() -> int:
    missing = [y for y in YEARS if not (RAW / f"FARS{y}NationalCSV.zip").is_file()]
    if missing:
        print(f"error: missing FARS zips for {missing} in {RAW}", file=sys.stderr)
        return 2
    frames = []
    print("year   crashes   dropped (unknown coords)   pedestrian  cyclist  dark")
    for year in YEARS:
        df, dropped = one_year(year)
        frames.append(df)
        print(f"{year}   {len(df):7d}   {dropped:7d}                    {df.pedestrian.mean():6.1%}   {df.cyclist.mean():6.1%}  {df.dark.mean():6.1%}")
    all_rows = pd.concat(frames, ignore_index=True).sort_values(["year", "st_case"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps the gzip bytes identical across rebuilds of the same data.
    all_rows.to_csv(OUT, index=False, lineterminator="\n",
                    compression={"method": "gzip", "compresslevel": 9, "mtime": 0})
    print(f"total  {len(all_rows)} crashes -> {OUT.relative_to(BACKEND)} ({OUT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
