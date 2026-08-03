#!/usr/bin/env python3
"""Generate new Pruuvn LinkedIn post entries and append them to posts.yml.

Calls the Claude API with brand rules + existing post history, asks it to
write N new posts in YAML format, validates the output, and appends the
new entries to posts.yml.

Usage:
    python scripts/generate_posts.py [--count 5] [--theme "healthcare focus"] [--dry-run]

Environment:
    ANTHROPIC_API_KEY   required
"""

import argparse
import json
import os
import pathlib
import re
import sys
import time
import datetime
import requests
import yaml

ROOT    = pathlib.Path(__file__).resolve().parent.parent
POSTSF  = ROOT / "posts.yml"
API_URL = "https://api.anthropic.com/v1/messages"
MODEL   = "claude-sonnet-4-6"

# ── brand brief sent to Claude ────────────────────────────────────────────────

BRAND_RULES = """
You are the LinkedIn content writer for Pruuvn®, a universal trust infrastructure
platform operating the Network Trust Standard™ (NTS™).

BRAND RULES — follow every one of these exactly:
- Always write Pruuvn® (with ®) and Network Trust Standard™ / NTS™ (with ™)
- Members, never "providers"
- Never say "patent-filed", "patent-pending", "pilot", or "pilot direction"
- Agent governance (RAAMS) is not yet built — never say it's live or deployable.
  Describing the delegation-binding architecture is fine.
- No em dashes in copy
- Pruuvn is infrastructure, not a service network

VOICE:
- Direct, confident, infrastructure-category tone
- Posts interconnect — the human trust network came first, AI agents extend it
- Each post has one clear thesis; no lists, no bullet points in the post body
- Hashtags always end with #NTS #Pruuvn #TrustInfrastructure
  (AI agent posts use #NTSforAI #Pruuvn #TrustInfrastructure instead)

CARD TYPES available (use exactly one per post):
  nts-intro, human-network, ai-agents, enterprise, fleet, thought-leadership,
  nts-ai-feature, cta, trust-center, why-now

CARD COPY RULES:
- headline: 5 words max, punchy, statement-first
- subline: one sentence, tight

OUTPUT FORMAT — return only valid YAML, no markdown fences, no preamble:

- id: "XX"
  card_type: <card_type>
  headline: "<headline>"
  subline: "<subline>"
  due: "<ISO 8601 with -04:00 offset>"
  alt: "Pruuvn card: <headline>"
  text: |
    <post body>

    #NTS #Pruuvn #TrustInfrastructure
"""

VALID_CARD_TYPES = {
    "nts-intro", "human-network", "ai-agents", "enterprise", "fleet",
    "thought-leadership", "nts-ai-feature", "cta", "trust-center", "why-now",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def load_posts():
    data = yaml.safe_load(POSTSF.read_text())
    return data.get("posts", []), data.get("defaults", {})


def next_id(posts):
    if not posts:
        return 11
    return max(int(p["id"]) for p in posts) + 1


def next_due(posts, count):
    """Return a list of `count` due dates starting from the post after the last one.
    Schedules Tue/Thu at 9 AM ET, skipping weekends."""
    TUE, THU = 1, 3
    if posts and posts[-1].get("due"):
        last = datetime.datetime.fromisoformat(posts[-1]["due"])
        cursor = last + datetime.timedelta(days=1)
    else:
        cursor = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-4)))
        cursor = cursor.replace(hour=9, minute=0, second=0, microsecond=0)

    dates, seen = [], 0
    while seen < count:
        if cursor.weekday() in (TUE, THU):
            dates.append(cursor.strftime("%Y-%m-%dT09:00:00-04:00"))
            seen += 1
        cursor += datetime.timedelta(days=1)
    return dates


def call_claude(prompt, api_key):
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": MODEL,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post(API_URL, headers=headers, json=body, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["content"][0]["text"]


def parse_yaml_posts(raw):
    """Extract and parse YAML list from Claude's response."""
    # Strip any accidental markdown fences
    raw = re.sub(r"```ya?ml", "", raw)
    raw = re.sub(r"```", "", raw)
    raw = raw.strip()

    # Wrap in a list key if not already
    if not raw.startswith("-"):
        raw = "- " + raw

    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, list):
        raise ValueError("Expected a YAML list of posts")
    return parsed


def validate(post):
    errors = []
    for field in ("id", "card_type", "headline", "subline", "due", "alt", "text"):
        if field not in post:
            errors.append(f"missing field: {field}")
    if post.get("card_type") not in VALID_CARD_TYPES:
        errors.append(f"invalid card_type: {post.get('card_type')!r}")
    if errors:
        raise ValueError(f"Post {post.get('id','?')} invalid: {'; '.join(errors)}")


def append_to_posts_yml(new_posts):
    """Append new entries preserving the existing file structure."""
    original = POSTSF.read_text()
    additions = []
    for p in new_posts:
        additions.append(yaml.dump([p], allow_unicode=True, default_flow_style=False))
    POSTSF.write_text(original.rstrip() + "\n\n" + "\n".join(additions))


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count",   type=int, default=5,  help="Number of posts to generate")
    ap.add_argument("--theme",   default="",           help="Optional content theme hint")
    ap.add_argument("--dry-run", action="store_true",  help="Print output without writing")
    args = ap.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set")

    existing, _ = load_posts()
    start_id    = next_id(existing)
    due_dates   = next_due(existing, args.count)

    # Summarise existing posts so Claude doesn't repeat themes
    history = "\n".join(
        f"  - [{p['id']}] {p.get('card_type','?')}: {p.get('headline','')}"
        for p in existing[-10:]   # last 10 only to keep prompt tight
    )

    prompt = f"""{BRAND_RULES}

EXISTING POSTS (do not repeat these themes):
{history}

TASK:
Write exactly {args.count} new LinkedIn posts for Pruuvn®.
{"Theme / focus: " + args.theme if args.theme else "Continue the established arc naturally."}

Number them starting from id "{str(start_id).zfill(2)}".
Use these exact due dates in order:
{chr(10).join("  " + d for d in due_dates)}

Return only the YAML list, nothing else.
"""

    print(f"Calling Claude API for {args.count} posts (starting id {str(start_id).zfill(2)})...")
    raw = call_claude(prompt, api_key)

    try:
        new_posts = parse_yaml_posts(raw)
    except Exception as e:
        print("Failed to parse Claude response:")
        print(raw)
        sys.exit(str(e))

    # Validate and inject correct due dates (override whatever Claude wrote)
    for i, post in enumerate(new_posts):
        post["id"] = str(start_id + i).zfill(2)
        post["due"] = due_dates[i]
        try:
            validate(post)
        except ValueError as e:
            sys.exit(str(e))

    if args.dry_run:
        print("\n--- DRY RUN: would append to posts.yml ---\n")
        for p in new_posts:
            print(yaml.dump([p], allow_unicode=True, default_flow_style=False))
        return

    append_to_posts_yml(new_posts)
    print(f"Appended {len(new_posts)} posts to posts.yml")
    for p in new_posts:
        print(f"  [{p['id']}] {p['card_type']}: {p['headline']}")


if __name__ == "__main__":
    main()
