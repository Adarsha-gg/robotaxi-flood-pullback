"""Download real resident photos attached to 311 street-flooding reports for a date.

Photos stay local (git-ignored: they may show people or plates). The manifest
data/photos_<date>.json (time, address, cell, url, local path) is committed.
Run: .venv/bin/python -m pipeline.fetch_photos 2026-11-18 [max]
"""
import json
import math
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "media", "frames", "311")
GRID = {"lat0": 37.70, "lon0": -122.52, "dlat": 0.0015, "dlon": 0.0019}


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-11-18"
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    os.makedirs(OUT, exist_ok=True)
    q = urllib.parse.urlencode({
        "$select": "requested_datetime,address,lat,long,media_url",
        "$where": f"requested_datetime between '{date}T00:00:00' and '{date}T23:59:59' "
                  "AND lower(service_subtype)='flooding' AND media_url IS NOT NULL",
        "$order": "requested_datetime", "$limit": 1000})
    with urllib.request.urlopen(f"https://data.sf.gov/resource/vw6y-z8j6.json?{q}", timeout=60) as r:
        rows = json.load(r)
    out = []
    for x in rows:
        url = x["media_url"] if isinstance(x["media_url"], str) else x["media_url"].get("url", "")
        if "cloudinary" not in url or not url.lower().endswith((".jpg", ".jpeg", ".png")):
            continue  # skip form-attachment links that aren't direct images
        lat, lon = float(x["lat"]), float(x["long"])
        cell = f"r{math.floor((lat - GRID['lat0']) / GRID['dlat'])}_c{math.floor((lon - GRID['lon0']) / GRID['dlon'])}"
        name = f"{x['requested_datetime'][11:16].replace(':', '')}_{url.rsplit('/', 1)[1]}"
        path = os.path.join(OUT, name)
        if not os.path.exists(path):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "flood-pullback-hackathon"})
                with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
                    f.write(r.read())
            except Exception as e:
                print("skip", url, e)
                continue
        out.append({"t": x["requested_datetime"][:19], "address": x["address"].split(", SAN FRANCISCO")[0],
                    "lat": lat, "lon": lon, "cell": cell, "url": url,
                    "path": os.path.relpath(path, ROOT)})
        if len(out) >= cap:
            break
    with open(os.path.join(ROOT, "data", f"photos_{date}.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"{len(out)} photos -> {OUT}; manifest data/photos_{date}.json")


if __name__ == "__main__":
    main()
