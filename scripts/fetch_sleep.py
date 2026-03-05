import os, json, datetime
import requests

CLIENT_ID = os.environ["FITBIT_CLIENT_ID"]
CLIENT_SECRET = os.environ["FITBIT_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["FITBIT_REFRESH_TOKEN"]

TOKEN_URL = "https://api.fitbit.com/oauth2/token"
SLEEP_URL = "https://api.fitbit.com/1.2/user/-/sleep/date/{date}.json"

def refresh_access_token():
    # Fitbit token endpoint uses HTTP Basic with client_id:client_secret
    import base64
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {basic}",
               "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN}
    r = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    r.raise_for_status()
    return r.json()

def get_sleep(access_token: str, date_str: str):
    r = requests.get(
        SLEEP_URL.format(date=date_str),
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

def pick_main_sleep(payload: dict):
    sleeps = payload.get("sleep", [])
    mains = [s for s in sleeps if s.get("isMainSleep")]
    if mains:
        # pick the longest main sleep (just in case)
        return max(mains, key=lambda s: s.get("duration", 0))
    return None

def minutes(x_ms: int) -> int:
    return int(round(x_ms / 60000))

def summarize(s: dict):
    levels = s.get("levels", {}).get("summary", {})
    # Fitbit sometimes provides both "stages" and "classic" keys; we guard.
    def lvl(name):
        v = levels.get(name, {})
        return int(v.get("minutes", 0))

    return {
        "dateOfSleep": s.get("dateOfSleep"),
        "startTime": s.get("startTime"),
        "endTime": s.get("endTime"),
        "duration_min": minutes(int(s.get("duration", 0))),
        "efficiency": s.get("efficiency"),
        "wake_min": lvl("wake"),
        "light_min": lvl("light"),
        "deep_min": lvl("deep"),
        "rem_min": lvl("rem"),
    }

def write_docs(summary: dict):
    os.makedirs("docs", exist_ok=True)
    with open("docs/latest.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

def write_raw(date_str: str, payload: dict):
    os.makedirs("out_raw", exist_ok=True)
    path = f"out_raw/{date_str}.sleep.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # minimal HTML that fetches latest.json
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="robots" content="noindex,nofollow"/>
  <title>Fitbit Sleep Latest</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; }}
    pre {{ background: #f6f8fa; padding: 12px; border-radius: 8px; overflow: auto; }}
  </style>
</head>
<body>
<h1>Latest sleep</h1>
<div id="box">Loading…</div>
<script>
fetch('./latest.json', {{cache:'no-store'}})
  .then(r => r.json())
  .then(j => {{
    const box = document.getElementById('box');
    box.innerHTML = `
      <p><b>Date</b>: ${{j.dateOfSleep}}</p>
      <p><b>Start–End</b>: ${{j.startTime}} → ${{j.endTime}}</p>
      <p><b>Duration</b>: ${{j.duration_min}} min (efficiency ${{j.efficiency}})</p>
      <p><b>Stages (min)</b>: wake ${{j.wake_min}}, rem ${{j.rem_min}}, light ${{j.light_min}}, deep ${{j.deep_min}}</p>
      <h2>Raw</h2>
      <pre>${{JSON.stringify(j, null, 2)}}</pre>
    `;
  }})
  .catch(e => {{
    document.getElementById('box').textContent = 'Failed to load latest.json: ' + e;
  }});
</script>
</body>
</html>
"""
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)

def main():
    tok = refresh_access_token()
    access = tok["access_token"]

    # try today then yesterday (local date handling is Fitbit-side; we just ask)
    today = datetime.date.today()
    candidates = [today, today - datetime.timedelta(days=1)]

best = None
best_payload = None
best_date = None

for d in candidates:
    payload = get_sleep(access, d.isoformat())
    s = pick_main_sleep(payload)
    if s:
        best = summarize(s)
        best_payload = payload
        best_date = d.isoformat()
        break

if not best:
    best = {"status": "no_main_sleep_found_yet", "checked": [c.isoformat() for c in candidates]}
    write_docs(best)
    return

write_docs(best)
write_raw(best_date, best_payload)

if __name__ == "__main__":
    main()
