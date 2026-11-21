"""Pull real Waymo front-camera frames from an SF rain drive (Waymo Open Dataset v2.0.1).

Needs YOUR OWN dataset access: sign in at https://waymo.com/open, accept the
(non-commercial) license, then `gcloud auth login` with that Google account.
Frames are NOT committed: the license does not allow redistribution.

Found by scanning every training/validation stats file: of 1,000 segments, only
one is San Francisco + rain: 3132521568089292927_2220_000_2240_000 (day).
Run: .venv/bin/python -m pipeline.fetch_waymo
"""
import os
import subprocess

import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEG = "3132521568089292927_2220_000_2240_000"
SRC = f"gs://waymo_open_dataset_v_2_0_1/training/camera_image/{SEG}.parquet"


def main():
    raw = os.path.join(ROOT, "data", "raw", "wod")
    out = os.path.join(ROOT, "media", "frames", "waymo")
    os.makedirs(raw, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    local = os.path.join(raw, f"{SEG}.parquet")
    if not os.path.exists(local):
        subprocess.run(["gcloud", "storage", "cp", SRC, raw], check=True)
    t = pq.read_table(local, columns=["key.frame_timestamp_micros", "key.camera_name",
                                      "[CameraImageComponent].image"]).to_pydict()
    front = sorted((ts, img) for ts, cam, img in zip(*t.values()) if cam == 1)  # 1 = FRONT
    for i, (_, img) in enumerate(front):
        with open(os.path.join(out, f"front_{i:03d}.jpg"), "wb") as f:
            f.write(img)
    print(f"{len(front)} front frames -> {out}")


if __name__ == "__main__":
    main()
