import base64
import os, json, datetime
import requests

CLIENT_ID = os.environ["FITBIT_CLIENT_ID"]
CLIENT_SECRET = os.environ["FITBIT_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["FITBIT_REFRESH_TOKEN"]

TOKEN_URL = "https://api.fitbit.com/oauth2/token"
SLEEP_URL = "https://api.fitbit.com/1.2/user/-/sleep/date/{date}.json"


def update_github_secret(secret_name, value):
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_SECRET_TOKEN"]

    url = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }

    key_resp = requests.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers=headers,
        timeout=30
    )
    key_resp.raise_for_status()
    key_data = key_resp.json()

    from nacl import encoding, public

    public_key = public.PublicKey(
        key_data["key"].encode(),
        encoding.Base64Encoder()
    )

    sealed_box = public.SealedBox(public_key)

    encrypted = base64.b64encode(
        sealed_box.encrypt(value.encode())
    ).decode()

    payload = {
        "encrypted_value": encrypted,
        "key_id": key_data["key_id"]
    }

    r = requests.put(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()


def refresh_access_token():
    basic = base64.b64encode(
        f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    ).decode()

    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN
    }

    r = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    r.raise_for_status()

    tok = r.json()

    new_refresh = tok.get("refresh_token")
    if new_refresh:
        update_github_secret("FITBIT_REFRESH_TOKEN", new_refresh)

    return tok


def get_sleep(access_token: str, date_str: str):
    r = requests.get(
        SLEEP_URL.format(date=date_str),
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def summarize_all_sleeps(payload: dict):
    """汇总一天内所有 sleep sessions，不只是 main sleep"""
    sleeps = payload.get("sleep", [])
    if not sleeps:
        return None

    total_duration = 0
    total_wake = 0
    total_light = 0
    total_deep = 0
    total_rem = 0

    # 按开始时间排序
    sleeps_sorted = sorted(sleeps, key=lambda s: s.get("startTime", ""))
    first_start = sleeps_sorted[0].get("startTime")
    last_end = max(s.get("endTime", "") for s in sleeps)

    # 计算加权平均 efficiency
    total_efficiency_weighted = 0
    total_duration_for_avg = 0

    for s in sleeps:
        dur = s.get("duration", 0)
        total_duration += dur

        eff = s.get("efficiency")
        if eff is not None:
            total_efficiency_weighted += eff * dur
            total_duration_for_avg += dur

        levels = s.get("levels", {}).get("summary", {})
        total_wake += levels.get("wake", {}).get("minutes", 0)
        total_light += levels.get("light", {}).get("minutes", 0)
        total_deep += levels.get("deep", {}).get("minutes", 0)
        total_rem += levels.get("rem", {}).get("minutes", 0)

    avg_efficiency = None
    if total_duration_for_avg > 0:
        avg_efficiency = round(total_efficiency_weighted / total_duration_for_avg)

    return {
        "dateOfSleep": sleeps_sorted[0].get("dateOfSleep"),
        "startTime": first_start,
        "endTime": last_end,
        "duration_min": int(round(total_duration / 60000)),
        "efficiency": avg_efficiency,
        "wake_min": total_wake,
        "light_min": total_light,
        "deep_min": total_deep,
        "rem_min": total_rem,
        "session_count": len(sleeps),
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
    const sessions = j.session_count ? ` (${{j.session_count}} sessions)` : '';
    box.innerHTML = `
      <p><b>Date</b>: ${{j.dateOfSleep}}</p>
      <p><b>Start–End</b>: ${{j.startTime}} → ${{j.endTime}}</p>
      <p><b>Duration</b>: ${{j.duration_min}} min${{sessions}} (efficiency ${{j.efficiency ?? 'N/A'}})</p>
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

    today = datetime.date.today()
    candidates = [today + datetime.timedelta(days=1), today, today - datetime.timedelta(days=1)]

    for d in candidates:
        payload = get_sleep(access, d.isoformat())
        if payload.get("sleep"):
            summary = summarize_all_sleeps(payload)
            if summary:
                write_docs(summary)
                write_raw(d.isoformat(), payload)
                print(f"Updated with {summary['session_count']} session(s) from {d.isoformat()}")
                return

    # 没找到任何 sleep 数据
    fallback = {
        "status": "no_sleep_found",
        "checked": [c.isoformat() for c in candidates]
    }
    write_docs(fallback)
    print("No sleep data found")


if __name__ == "__main__":
    main()
