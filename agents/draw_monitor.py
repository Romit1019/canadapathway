#!/usr/bin/env python3
"""
Draw Monitor Agent
Pulls Express Entry rounds from IRCC's official JSON dataset, updates
draws.html, and triggers the newsletter/blog agents if a new draw appears.
Runs every 6 hours via GitHub Actions.
"""

import json
import os
import re
import sys
import hashlib
from datetime import datetime
from pathlib import Path

import requests
import anthropic

# IRCC Open Data — Express Entry rounds (official, JSON, stable)
IRCC_JSON_URL = "https://www.canada.ca/content/dam/ircc/documents/json/ee_rounds_123_en.json"

DRAWS_JSON = Path(__file__).parent.parent / "data" / "draws.json"
DRAWS_HTML = Path(__file__).parent.parent / "draws.html"
STATE_FILE = Path(__file__).parent.parent / "data" / "last_draw_hash.txt"

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def fetch_ircc_draws():
    """Fetch the IRCC JSON dataset and normalize fields."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CanadaPathway/1.0; +https://pathwayofcanada.com)",
        "Accept": "application/json,text/plain,*/*",
    }
    try:
        resp = requests.get(IRCC_JSON_URL, headers=headers, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"[DrawMonitor] Failed to fetch IRCC JSON: {e}")
        return []

    try:
        data = resp.json()
    except Exception as e:
        print(f"[DrawMonitor] Failed to parse JSON: {e}")
        return []

    rounds = data.get("rounds") or data.get("Rounds") or []
    if not rounds:
        print("[DrawMonitor] JSON contained no rounds")
        return []

    draws = []
    for r in rounds[:40]:
        number = str(r.get("drawNumber") or r.get("drawNumberURL") or "").strip()
        date_full = (r.get("drawDateFull") or r.get("drawDate") or "").strip()
        draw_type = (r.get("drawName") or r.get("drawText2") or "General").strip()
        invitations = re.sub(r"[^\d]", "", str(r.get("drawSize") or "0"))
        crs = re.sub(r"[^\d]", "", str(r.get("drawCRS") or "0"))
        tie = (r.get("drawCutOff") or "").strip()

        if not number or not date_full:
            continue

        draws.append({
            "number": number,
            "date": date_full,
            "type": draw_type,
            "invitations": invitations or "0",
            "crs": crs or "N/A",
            "tie_breaking": tie or "N/A",
        })

    print(f"[DrawMonitor] Parsed {len(draws)} draws from IRCC JSON")
    return draws


def get_draw_hash(draws):
    if not draws:
        return ""
    latest = json.dumps(draws[0], sort_keys=True)
    return hashlib.md5(latest.encode()).hexdigest()


def load_last_hash():
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip()
    return ""


def save_hash(h):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(h)


def classify_draw_type(raw_type):
    t = raw_type.lower()
    if "provincial" in t or "pnp" in t:
        return ("PNP only", "badge-pnp")
    if "french" in t:
        return ("French language", "badge-french")
    if "stem" in t:
        return ("STEM", "badge-stem")
    if "health" in t:
        return ("Healthcare", "badge-healthcare")
    if "trade" in t or "transport" in t:
        return ("Trades", "badge-trades")
    if "agriculture" in t or "agri" in t:
        return ("Agriculture", "badge-agri")
    if "education" in t:
        return ("Education", "badge-education")
    return ("General", "badge-general")


def save_draws_json(draws):
    DRAWS_JSON.parent.mkdir(exist_ok=True)
    with open(DRAWS_JSON, "w") as f:
        json.dump(draws, f, indent=2)
    print(f"[DrawMonitor] Saved {len(draws)} draws to draws.json")


def ai_analyze_draw(draw):
    prompt = f"""You are an expert on Canadian immigration. Write exactly 2 crisp sentences analyzing this Express Entry draw for applicants. Be specific, factual, and helpful. No fluff.

Draw details:
- Draw number: #{draw['number']}
- Date: {draw['date']}
- Type: {draw['type']}
- Invitations issued: {draw['invitations']}
- CRS cutoff: {draw['crs']}

Output only the 2 sentences, nothing else."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def update_draws_html(draws):
    if not DRAWS_HTML.exists():
        print("[DrawMonitor] draws.html not found, skipping HTML update")
        return

    html = DRAWS_HTML.read_text()
    rows_html = ""
    prev_crs = None
    for i, d in enumerate(draws[:40]):
        draw_type, badge_class = classify_draw_type(d["type"])
        crs = d["crs"]

        trend = "—"
        if prev_crs and crs.isdigit() and prev_crs.isdigit():
            diff = int(crs) - int(prev_crs)
            if diff > 0:
                trend = f'<span class="trend-up">▲ {diff}</span>'
            elif diff < 0:
                trend = f'<span class="trend-dn">▼ {abs(diff)}</span>'
        if crs.isdigit():
            prev_crs = crs

        crs_int = int(crs) if crs.isdigit() else 0
        if crs_int >= 500:
            crs_class = "crs-high"
        elif crs_int >= 460:
            crs_class = "crs-mid"
        else:
            crs_class = "crs-low"

        try:
            inv_fmt = f"{int(d['invitations']):,}"
        except ValueError:
            inv_fmt = d['invitations']

        rows_html += f"""<tr>
      <td style="color:var(--text-muted)">#{d['number']}</td>
      <td>{d['date']}</td>
      <td><span class="type-badge {badge_class}">{draw_type}</span></td>
      <td>{inv_fmt}</td>
      <td class="crs-cell {crs_class}">{crs}</td>
      <td>{trend}</td>
      <td style="color:var(--text-muted)">—</td>
    </tr>"""

    new_html = re.sub(
        r'<tbody id="tableBody">.*?</tbody>',
        f'<tbody id="tableBody">{rows_html}</tbody>',
        html,
        flags=re.DOTALL
    )

    latest = draws[0] if draws else {}
    if latest.get("crs", "").isdigit():
        latest_crs = latest["crs"]
        new_html = re.sub(
            r'(<div class="stat-val" id="latestCRS">).*?(</div>)',
            f'\\g<1>{latest_crs}\\g<2>',
            new_html
        )

    DRAWS_HTML.write_text(new_html)
    print(f"[DrawMonitor] Updated draws.html with {len(draws)} draws")


def write_new_draw_flag(draw, analysis):
    flag = {
        "draw": draw,
        "analysis": analysis,
        "timestamp": datetime.utcnow().isoformat()
    }
    flag_path = Path(__file__).parent.parent / "data" / "new_draw_flag.json"
    with open(flag_path, "w") as f:
        json.dump(flag, f, indent=2)
    print(f"[DrawMonitor] Wrote new draw flag for #{draw['number']}")


def main():
    print(f"[DrawMonitor] Starting at {datetime.utcnow().isoformat()}")

    draws = fetch_ircc_draws()
    if not draws:
        print("[DrawMonitor] No draws fetched, exiting")
        sys.exit(0)

    current_hash = get_draw_hash(draws)
    last_hash = load_last_hash()

    new_draw_detected = current_hash != last_hash
    print(f"[DrawMonitor] New draw detected: {new_draw_detected}")
    print(f"[DrawMonitor] Latest: #{draws[0]['number']} | {draws[0]['date']} | CRS {draws[0]['crs']}")

    save_draws_json(draws)
    update_draws_html(draws)

    if new_draw_detected:
        print(f"[DrawMonitor] Analyzing draw #{draws[0]['number']} with Claude...")
        analysis = ai_analyze_draw(draws[0])
        print(f"[DrawMonitor] Analysis: {analysis}")
        write_new_draw_flag(draws[0], analysis)
        save_hash(current_hash)
        print(f"::notice::New draw detected #{draws[0]['number']}")
    else:
        print("[DrawMonitor] No new draw, nothing to publish")


if __name__ == "__main__":
    main()
