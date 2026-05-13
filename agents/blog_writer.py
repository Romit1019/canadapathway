#!/usr/bin/env python3
"""
Blog Writer Agent
Uses Claude to generate SEO-optimized immigration articles on a schedule.
Also writes draw-specific articles when triggered by the draw monitor.
Runs every Monday and Thursday via GitHub Actions.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import anthropic

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

POSTS_DIR = Path(__file__).parent.parent / "posts"
BLOG_HTML = Path(__file__).parent.parent / "blog.html"
DATA_DIR = Path(__file__).parent.parent / "data"
TOPICS_FILE = DATA_DIR / "topics_queue.json"
WRITTEN_FILE = DATA_DIR / "written_topics.json"
NEW_DRAW_FLAG = DATA_DIR / "new_draw_flag.json"

# Pre-seeded high-traffic topic queue
DEFAULT_TOPICS = [
    {"slug": "how-to-improve-crs-score-50-points", "title": "How to Improve Your CRS Score by 50+ Points in 6 Months", "category": "Express Entry", "keywords": ["improve CRS score", "CRS score Canada", "increase express entry points"]},
    {"slug": "bc-pnp-tech-pilot-noc-codes-2025", "title": "BC PNP Tech Pilot 2025: Every Eligible NOC Code and How Fast It Processes", "category": "PNP", "keywords": ["BC PNP Tech", "BC PNP NOC codes", "BC tech immigration"]},
    {"slug": "french-language-draw-guide", "title": "French-Language Express Entry Draws: The Complete Strategy Guide", "category": "Express Entry", "keywords": ["French Express Entry", "francophone immigration Canada", "French language draw CRS"]},
    {"slug": "ielts-vs-celpip-2025", "title": "IELTS vs CELPIP 2025: Which Test Gets You a Higher CLB Score", "category": "Language Tests", "keywords": ["IELTS vs CELPIP", "CLB score Canada", "best English test immigration"]},
    {"slug": "pnp-vs-express-entry-which-faster", "title": "PNP vs Express Entry: Which Path Gets You PR Faster in 2025", "category": "Strategy", "keywords": ["PNP vs express entry", "fastest way Canada PR", "provincial nominee program"]},
    {"slug": "noc-teer-complete-guide", "title": "NOC TEER System Explained: How to Find Your Correct NOC Code", "category": "Express Entry", "keywords": ["NOC code Canada", "TEER categories", "NOC code lookup"]},
    {"slug": "eca-guide-which-body", "title": "ECA Canada 2025: Which Designated Body to Use for Your Degree", "category": "Express Entry", "keywords": ["ECA Canada", "educational credential assessment", "WES Canada"]},
    {"slug": "spousal-sponsorship-processing-times-2025", "title": "Spousal Sponsorship Processing Times 2025: Inland vs Outland Compared", "category": "Family Sponsorship", "keywords": ["spousal sponsorship Canada", "spouse visa Canada processing time", "inland vs outland sponsorship"]},
    {"slug": "manitoba-pnp-under-400-crs", "title": "Manitoba PNP 2025: How to Get Nominated With a CRS Score Below 400", "category": "PNP", "keywords": ["Manitoba PNP", "MPNP", "Manitoba immigration"]},
    {"slug": "canada-immigration-levels-2025-outlook", "title": "Canada's 2025 Immigration Levels Plan: What Reduced Targets Mean for You", "category": "Policy", "keywords": ["Canada immigration 2025", "IRCC levels plan", "immigration targets Canada"]},
    {"slug": "pgwp-changes-2025", "title": "Post-Graduation Work Permit 2025: New Rules Every International Graduate Needs to Know", "category": "Study → PR", "keywords": ["PGWP 2025", "post graduation work permit Canada", "study to PR Canada"]},
    {"slug": "lmia-explained", "title": "LMIA Explained: What Employers and Workers Need to Know in 2025", "category": "Work Permits", "keywords": ["LMIA Canada", "Labour Market Impact Assessment", "LMIA job offer express entry"]},
    {"slug": "alberta-pnp-job-offer", "title": "Alberta PNP 2025: How to Get a Nomination With or Without a Job Offer", "category": "PNP", "keywords": ["Alberta PNP", "AINP", "Alberta immigration"]},
    {"slug": "healthcare-worker-canada-pr-2025", "title": "Healthcare Workers: The Fastest Path to Canada PR in 2025", "category": "Healthcare", "keywords": ["healthcare worker Canada immigration", "nurse Canada PR", "healthcare express entry"]},
    {"slug": "express-entry-profile-tips", "title": "10 Things That Weaken Your Express Entry Profile (And How to Fix Them)", "category": "Express Entry", "keywords": ["express entry profile tips", "express entry mistakes", "improve express entry application"]},
]


def load_written():
    if WRITTEN_FILE.exists():
        return json.loads(WRITTEN_FILE.read_text())
    return []


def save_written(written):
    DATA_DIR.mkdir(exist_ok=True)
    WRITTEN_FILE.write_text(json.dumps(written, indent=2))


def load_topics():
    if TOPICS_FILE.exists():
        return json.loads(TOPICS_FILE.read_text())
    return DEFAULT_TOPICS


def get_next_topic(topics, written_slugs):
    for topic in topics:
        if topic["slug"] not in written_slugs:
            return topic
    return None


def generate_article(topic):
    """Use Claude to write a full SEO article."""
    keywords_str = ", ".join(topic["keywords"])
    today = datetime.utcnow().strftime("%B %d, %Y")

    system = """You are a senior immigration content writer for pathwayofcanada.com. 
You write accurate, detailed, deeply practical articles for people planning to immigrate to Canada.
Your writing is direct, factual, and structured. No fluff, no vague advice.
You always include specific numbers, processing times, CRS scores, and actionable steps.
You write in clean HTML using these classes: .article-content h2, h3, p, ul, ol, .highlight-box, .info-table.
Never include <html>, <head>, <body> tags — only the inner article content."""

    prompt = f"""Write a comprehensive SEO article for pathwayofcanada.com.

Title: {topic['title']}
Category: {topic['category']}
Target keywords: {keywords_str}
Date: {today}

Requirements:
- 1,200–1,600 words
- Start with a strong 2-sentence introduction
- Use 4–6 H2 subheadings
- Include at least one practical numbered step list
- Include specific CRS scores, processing times, or program requirements where relevant
- End with a clear next step pointing to our free tools (CRS calculator at /crs-calculator.html or PNP matcher at /pnp-matcher.html)
- Write in clean HTML (only body content, no html/head/body tags)
- Use <div class="highlight-box"> for important callouts
- Naturally include the target keywords without stuffing

Output ONLY the HTML article content. No preamble, no markdown."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        system=system,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def generate_draw_article(draw, analysis):
    """Write a specific article about a new draw result."""
    draw_type = draw.get("type", "General")
    draw_num = draw.get("number", "?")
    draw_date = draw.get("date", "")
    draw_crs = draw.get("crs", "?")
    draw_inv = draw.get("invitations", "?")

    slug = f"express-entry-draw-{draw_num}-results-{draw_date.lower().replace(' ', '-').replace(',', '')}"
    title = f"Express Entry Draw #{draw_num} Results: {draw_inv} Invited at CRS {draw_crs}"

    system = """You are a Canadian immigration analyst writing a draw results article for pathwayofcanada.com.
Write in clean HTML body content only. Be specific and data-driven."""

    prompt = f"""Write a draw results article for this Express Entry round.

Draw #{draw_num} — {draw_date}
Type: {draw_type}
Invitations: {draw_inv}
CRS Cutoff: {draw_crs}

Expert analysis: {analysis}

Write a 600–900 word article covering:
1. Draw summary (what happened)
2. What this cutoff means for applicants in the pool
3. Trend context (how this compares to recent draws of the same type)
4. Who specifically benefits from this draw
5. What applicants just below the cutoff should do now

End with a CTA to check their score at /crs-calculator.html.

Output ONLY clean HTML body content."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": prompt}]
    )

    return {
        "slug": slug,
        "title": title,
        "category": "Draw Results",
        "keywords": [f"express entry draw {draw_num}", f"CRS {draw_crs}", "express entry results"],
        "content": response.content[0].text.strip()
    }


def save_post(slug, title, category, keywords, content, date_str):
    """Save article as HTML file and update the blog index."""
    POSTS_DIR.mkdir(exist_ok=True)
    post_path = POSTS_DIR / f"{slug}.html"

    keywords_meta = ", ".join(keywords)
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — PathwayOfCanada</title>
<meta name="description" content="{title}. Expert Canadian immigration guidance at PathwayOfCanada.com.">
<meta name="keywords" content="{keywords_meta}">
<meta property="og:title" content="{title}">
<meta property="og:type" content="article">
<meta property="og:url" content="https://pathwayofcanada.com/posts/{slug}.html">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--navy:#0d1b2a;--navy-mid:#162235;--red:#d42b2b;--gold-light:#e8b052;--cream:#f5f0e8;--white:#fff;--text-muted:#8a9ab0;--border:rgba(255,255,255,0.08)}}
body{{font-family:'DM Sans',sans-serif;background:var(--navy);color:var(--cream);line-height:1.7;min-height:100vh}}
nav{{position:fixed;top:0;left:0;right:0;z-index:100;background:rgba(13,27,42,0.96);backdrop-filter:blur(12px);border-bottom:1px solid var(--border);padding:0 5%;display:flex;align-items:center;justify-content:space-between;height:64px}}
.logo{{font-family:'Playfair Display',serif;font-size:1.3rem;font-weight:700;color:var(--white);text-decoration:none}}.logo span{{color:var(--red)}}
.nav-back{{color:var(--text-muted);text-decoration:none;font-size:0.875rem;transition:color 0.2s}}.nav-back:hover{{color:var(--cream)}}
.article-wrap{{max-width:760px;margin:0 auto;padding:100px 5% 5rem}}
.post-meta{{display:flex;gap:1rem;align-items:center;margin-bottom:2rem;flex-wrap:wrap}}
.post-cat{{font-size:0.7rem;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:var(--red)}}
.post-date{{font-size:0.78rem;color:var(--text-muted)}}
.post-read{{font-size:0.78rem;color:var(--text-muted)}}
h1{{font-family:'Playfair Display',serif;font-size:clamp(1.8rem,4vw,2.6rem);font-weight:700;color:var(--white);line-height:1.15;margin-bottom:2rem;letter-spacing:-0.02em}}
.article-content h2{{font-family:'Playfair Display',serif;font-size:1.5rem;font-weight:600;color:var(--white);margin:2.5rem 0 1rem;line-height:1.2}}
.article-content h3{{font-size:1.1rem;font-weight:600;color:var(--gold-light);margin:1.75rem 0 0.75rem}}
.article-content p{{color:rgba(245,240,232,0.85);margin-bottom:1.25rem;font-size:0.975rem}}
.article-content ul,.article-content ol{{margin:1rem 0 1.5rem 1.5rem;color:rgba(245,240,232,0.85);font-size:0.975rem}}
.article-content li{{margin-bottom:0.5rem}}
.article-content .highlight-box{{background:rgba(200,146,42,0.08);border:1px solid rgba(200,146,42,0.2);border-left:3px solid var(--gold-light);border-radius:6px;padding:1.25rem 1.5rem;margin:1.75rem 0}}
.article-content .highlight-box p{{margin-bottom:0;color:var(--cream)}}
.article-content .info-table{{width:100%;border-collapse:collapse;margin:1.5rem 0;font-size:0.875rem}}
.article-content .info-table th{{text-align:left;padding:0.75rem 1rem;background:rgba(255,255,255,0.05);color:var(--text-muted);font-size:0.7rem;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid var(--border)}}
.article-content .info-table td{{padding:0.75rem 1rem;border-bottom:1px solid rgba(255,255,255,0.04);color:var(--cream)}}
.cta-box{{background:rgba(212,43,43,0.07);border:1px solid rgba(212,43,43,0.2);border-radius:10px;padding:1.75rem;margin-top:3rem;text-align:center}}
.cta-box h3{{font-family:'Playfair Display',serif;font-size:1.3rem;color:var(--white);margin-bottom:0.75rem}}
.cta-box p{{color:var(--text-muted);margin-bottom:1.25rem;font-size:0.9rem}}
.cta-btn{{background:var(--red);color:white;padding:0.875rem 2rem;border:none;border-radius:6px;font-size:0.9rem;font-weight:600;text-decoration:none;display:inline-block;font-family:'DM Sans',sans-serif}}
</style>
</head>
<body>
<nav>
  <a href="../index.html" class="logo">Pathway<span>OfCanada</span></a>
  <a href="../blog.html" class="nav-back">← All Articles</a>
</nav>
<div class="article-wrap">
  <div class="post-meta">
    <span class="post-cat">{category}</span>
    <span class="post-date">{date_str}</span>
    <span class="post-read">8 min read</span>
  </div>
  <h1>{title}</h1>
  <div class="article-content">
    {content}
  </div>
  <div class="cta-box">
    <h3>Know Where You Stand</h3>
    <p>Use our free CRS calculator to see your exact score and how it compares to recent draw cutoffs.</p>
    <a href="../crs-calculator.html" class="cta-btn">Calculate My CRS Score →</a>
  </div>
</div>
</body>
</html>"""

    post_path.write_text(full_html)
    print(f"[BlogWriter] Saved post: {post_path}")
    return str(post_path)


def update_blog_index(new_posts):
    """Prepend new article cards to blog.html."""
    if not BLOG_HTML.exists() or not new_posts:
        return

    html = BLOG_HTML.read_text()
    colors = ["c-red", "c-blue", "c-green", "c-purple", "c-orange", "c-gold"]

    new_cards = ""
    for i, post in enumerate(new_posts):
        color = colors[i % len(colors)]
        icon = {"Draw Results": "📊", "PNP": "🏛️", "Express Entry": "🍁",
                "Language Tests": "💬", "Family Sponsorship": "👨‍👩‍👧",
                "Study → PR": "🎓", "Healthcare": "🏥", "Policy": "⚖️"}.get(post["category"], "📋")
        new_cards += f"""
        <a href="posts/{post['slug']}.html" class="article-card">
          <div class="card-img {color}"><span>{icon}</span><div class="card-badge">{post['category']}</div></div>
          <div class="card-body">
            <div class="card-meta"><span class="card-cat">{post['category']}</span><span class="card-date">{post['date']}</span></div>
            <h3>{post['title']}</h3>
            <p>{post['excerpt']}</p>
            <div class="card-footer"><span class="read-time">8 min read</span><span class="read-more">Read →</span></div>
          </div>
        </a>"""

    # Insert new cards at the top of the grid
    updated = html.replace(
        '<div class="articles-grid">',
        f'<div class="articles-grid">{new_cards}'
    )
    BLOG_HTML.write_text(updated)
    print(f"[BlogWriter] Updated blog.html with {len(new_posts)} new cards")


def generate_excerpt(content):
    """Use Claude to write a 1-sentence excerpt from the article HTML."""
    plain = re.sub(r"<[^>]+>", " ", content)[:600]
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=80,
        messages=[{"role": "user", "content": f"Write one sentence (max 20 words) summarizing this immigration article for a blog card preview. Output only the sentence:\n\n{plain}"}]
    )
    return response.content[0].text.strip()


def main():
    print(f"[BlogWriter] Starting at {datetime.utcnow().isoformat()}")
    DATA_DIR.mkdir(exist_ok=True)
    POSTS_DIR.mkdir(exist_ok=True)

    written = load_written()
    written_slugs = [w["slug"] for w in written]
    topics = load_topics()
    new_posts_meta = []
    today_str = datetime.utcnow().strftime("%b %d, %Y")

    # Check if draw monitor flagged a new draw
    if NEW_DRAW_FLAG.exists():
        flag = json.loads(NEW_DRAW_FLAG.read_text())
        draw = flag["draw"]
        analysis = flag["analysis"]
        print(f"[BlogWriter] Writing draw article for #{draw['number']}")
        draw_post = generate_draw_article(draw, analysis)
        if draw_post["slug"] not in written_slugs:
            content = draw_post["content"]
            excerpt = generate_excerpt(content)
            save_post(draw_post["slug"], draw_post["title"], draw_post["category"],
                      draw_post["keywords"], content, today_str)
            meta = {"slug": draw_post["slug"], "title": draw_post["title"],
                    "category": draw_post["category"], "date": today_str, "excerpt": excerpt}
            new_posts_meta.append(meta)
            written.append({"slug": draw_post["slug"], "date": today_str})
        NEW_DRAW_FLAG.unlink()  # consume the flag

    # Write 1 scheduled article if not already done today
    mode = os.environ.get("WRITER_MODE", "scheduled")
    if mode == "scheduled":
        next_topic = get_next_topic(topics, written_slugs)
        if next_topic:
            print(f"[BlogWriter] Writing: {next_topic['title']}")
            content = generate_article(next_topic)
            excerpt = generate_excerpt(content)
            save_post(next_topic["slug"], next_topic["title"], next_topic["category"],
                      next_topic["keywords"], content, today_str)
            meta = {"slug": next_topic["slug"], "title": next_topic["title"],
                    "category": next_topic["category"], "date": today_str, "excerpt": excerpt}
            new_posts_meta.append(meta)
            written.append({"slug": next_topic["slug"], "date": today_str})
        else:
            print("[BlogWriter] All queued topics written, need new topics")

    save_written(written)
    if new_posts_meta:
        update_blog_index(new_posts_meta)
        print(f"[BlogWriter] Published {len(new_posts_meta)} article(s)")
    else:
        print("[BlogWriter] Nothing published this run")


if __name__ == "__main__":
    main()
