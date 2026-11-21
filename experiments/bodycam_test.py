"""Check a police report claim against a public bodycam video with Gemini.

Usage: .venv/bin/python bodycam_test.py <youtube_url> [model]
"""
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client()

URL = sys.argv[1]
MODEL = sys.argv[2] if len(sys.argv) > 2 else "gemini-4-hydrogen"

# The claim as described in public reporting of the arrest report.
REPORT = (
    "Arrest report excerpt: Officers observed the suspect discard a bag containing "
    "a white powdery substance under a parked SUV while fleeing on foot. Officers "
    "recovered the bag from under the vehicle."
)

PROMPT = f"""You are helping a public defender review discovery video.

{REPORT}

Watch the video. Some parts may be news coverage with narration. Base every finding only on
what the bodycam or dashcam footage itself shows, not on narration or captions, and say when a
finding depends on narration.

Return:
1. A timeline of the footage events with MM:SS timestamps.
2. For each factual claim in the report excerpt: SUPPORTED, CONTRADICTED, or NOT SHOWN,
   with the timestamp(s) of the frames that decide it.
3. The 3 timestamps the attorney must watch first, and why.
4. What you could not see or are unsure about."""

t = time.time()
res = client.models.generate_content(
    model=MODEL,
    contents=types.Content(parts=[
        types.Part(file_data=types.FileData(file_uri=URL)),
        types.Part(text=PROMPT),
    ]),
)
print(f"[{MODEL}, {time.time()-t:.1f}s]\n")
print(res.text)
