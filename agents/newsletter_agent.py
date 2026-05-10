#!/usr/bin/env python3
"""
Newsletter Agent
Sends draw alert emails and weekly digest via Brevo (formerly Sendinblue) free tier.
Triggered by the draw monitor or on a weekly schedule.
Free tier: 300 emails/day — enough for ~10,000 subscribers at weekly frequency.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
import anthropic
import requests

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "alerts@pathwayofcanada.com")
SENDER_NAME = "PathwayOfCanada"

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
DATA_DIR = Path(__file__).parent.parent / "data"
NEW_DRAW_FLAG = DATA_DIR / "new_draw_flag.json"


def ai_write_email(draw, analysis):
    """Use Claude to write the draw alert email."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        messages=[{"role": "user", "content": f"""Write a concise draw alert email for Canadian immigration applicants.

Draw #{draw['number']} — {draw['date']}
Type: {draw['type']}
Invitations: {draw['invitations']}
CRS Cutoff: {draw['crs']}
Expert analysis: {analysis}

Format:
- Subject line (no "Subject:" prefix, just the line)
- Blank line
- Email body in clean HTML (no html/head/body tags)
- Keep it under 250 words
- End with one clear CTA button linking to https://pathwayofcanada.com/crs-calculator.html
- Tone: factual, direct, no hype

Output subject line first, then blank line, then HTML body."""}]
    )

    text = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        messages=[{"role": "user", "content": f"""Write a concise draw alert email for Canadian immigration applicants.

Draw #{draw['number']} — {draw['date']}
Type: {draw['type']}
Invitations: {draw['invitations']}
CRS Cutoff: {draw['crs']}
Expert analysis: {analysis}

Format:
- Subject line (no prefix, just the line)
- Blank line
- Email body in clean HTML (no html/head/body tags)
- Under 250 words
- End with CTA to https://pathwayofcanada.com/crs-calculator.html
- Tone: factual, direct

Output subject first, blank line, then HTML body."""}]
    )

    raw = text.content[0].text.strip()
    lines = raw.split("\n")
    subject = lines[0].strip()
    body = "\n".join(lines[2:]).strip()  # skip subject + blank line

    return subject, body


def send_via_brevo(subject, html_body, list_id=None):
    """Send email campaign via Brevo API."""
    if not BREVO_API_KEY:
        print("[Newsletter] BREVO_API_KEY not set, skipping send")
        return False

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": BREVO_API_KEY
    }

    # Create campaign
    campaign_data = {
        "name": f"Draw Alert - {datetime.utcnow().strftime('%Y-%m-%d')}",
        "subject": subject,
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "type": "classic",
        "htmlContent": f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1b2a;color:#f5f0e8;margin:0;padding:20px}}
.container{{max-width:600px;margin:0 auto;background:#162235;border-radius:12px;padding:2rem;border:1px solid rgba(255,255,255,0.08)}}
.logo{{font-size:1.2rem;font-weight:700;color:#fff;margin-bottom:1.5rem}}.logo span{{color:#d42b2b}}
.content{{font-size:0.95rem;line-height:1.7;color:rgba(245,240,232,0.9)}}
.cta{{display:block;background:#d42b2b;color:#fff;text-align:center;padding:0.875rem 2rem;border-radius:6px;text-decoration:none;font-weight:600;margin:1.5rem 0}}
.footer{{font-size:0.75rem;color:#8a9ab0;margin-top:1.5rem;padding-top:1rem;border-top:1px solid rgba(255,255,255,0.08)}}
</style>
</head>
<body>
<div class="container">
  <div class="logo">Pathway<span>OfCanada</span></div>
  <div class="content">{html_body}</div>
  <div class="footer">You're receiving this because you subscribed to draw alerts at pathwayofcanada.com. <a href="{{{{ unsubscribe }}}}" style="color:#8a9ab0">Unsubscribe</a></div>
</div>
</body>
</html>""",
        "recipients": {"listIds": [list_id or 1]}
    }

    resp = requests.post(
        "https://api.brevo.com/v3/emailCampaigns",
        headers=headers,
        json=campaign_data,
        timeout=30
    )

    if resp.status_code not in (200, 201):
        print(f"[Newsletter] Campaign creation failed: {resp.status_code} {resp.text}")
        return False

    campaign_id = resp.json()["id"]
    print(f"[Newsletter] Campaign created: {campaign_id}")

    # Send immediately
    send_resp = requests.post(
        f"https://api.brevo.com/v3/emailCampaigns/{campaign_id}/sendNow",
        headers=headers,
        timeout=30
    )

    if send_resp.status_code == 204:
        print(f"[Newsletter] Campaign sent successfully")
        return True
    else:
        print(f"[Newsletter] Send failed: {send_resp.status_code} {send_resp.text}")
        return False


def log_email(subject, draw_num):
    log_path = DATA_DIR / "email_log.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else []
    log.append({
        "timestamp": datetime.utcnow().isoformat(),
        "draw": draw_num,
        "subject": subject
    })
    log_path.write_text(json.dumps(log[-100:], indent=2))  # keep last 100


def main():
    print(f"[Newsletter] Starting at {datetime.utcnow().isoformat()}")

    mode = os.environ.get("NEWSLETTER_MODE", "draw_alert")

    if mode == "draw_alert":
        if not NEW_DRAW_FLAG.exists():
            print("[Newsletter] No new draw flag found, nothing to send")
            sys.exit(0)

        flag = json.loads(NEW_DRAW_FLAG.read_text())
        draw = flag["draw"]
        analysis = flag["analysis"]

        print(f"[Newsletter] Writing email for draw #{draw['number']}")
        subject, body = ai_write_email(draw, analysis)
        print(f"[Newsletter] Subject: {subject}")

        success = send_via_brevo(subject, body)
        if success:
            log_email(subject, draw["number"])

    elif mode == "weekly_digest":
        # Weekly digest: summarize top articles from the week
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{"role": "user", "content": f"""Write a weekly digest email for Canadian immigration applicants.
Today: {datetime.utcnow().strftime('%B %d, %Y')}
Website: pathwayofcanada.com

Include:
- Brief intro (1 sentence)
- 3 quick immigration tips or reminders
- CTA to check their CRS score

Output subject line, blank line, then clean HTML body under 200 words."""}]
        )

        raw = response.content[0].text.strip()
        lines = raw.split("\n")
        subject = lines[0].strip()
        body = "\n".join(lines[2:]).strip()

        print(f"[Newsletter] Sending weekly digest: {subject}")
        send_via_brevo(subject, body)

    print("[Newsletter] Done")


if __name__ == "__main__":
    main()
