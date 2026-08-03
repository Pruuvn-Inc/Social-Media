#!/usr/bin/env python3
"""Create Buffer posts from posts.yml, attaching card images by raw URL.

Reads:
  BUFFER_TOKEN        Buffer API token
  BUFFER_CHANNEL_ID   target channel (the Pruuvn LinkedIn page)
  ASSET_BASE          public base URL for cards/, e.g.
                      https://raw.githubusercontent.com/<owner>/<repo>/main/cards

The repo must be PUBLIC. Buffer fetches the image URL without credentials,
so a private repo's raw URLs will 404 and the post will be created with no
image attached.
"""

import argparse
import os
import sys
import time
import pathlib
import requests
import yaml

API = "https://api.bufferapp.com/2/posts"
ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = ROOT / ".posted.txt"          # ids already pushed, one per line


def load_manifest():
    data = yaml.safe_load((ROOT / "posts.yml").read_text())
    defaults = data.get("defaults", {}) or {}
    posts = []
    for p in data["posts"]:
        merged = {**defaults, **p}
        posts.append(merged)
    return posts


def already_posted():
    if not STATE.exists():
        return set()
    return {ln.strip() for ln in STATE.read_text().splitlines() if ln.strip()}


def mark_posted(post_id):
    with STATE.open("a") as fh:
        fh.write(f"{post_id}\n")


def verify_asset(url, external=False):
    """Confirm Buffer will be able to fetch this image."""
    try:
        r = requests.head(url, timeout=15, allow_redirects=True)
    except requests.RequestException as exc:
        return False, str(exc)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    ctype = r.headers.get("content-type", "")
    # External URLs (e.g. event CDNs, Instagram story assets) may serve
    # application/octet-stream or redirect to a signed URL — treat 200 as ok
    if not external and not ctype.startswith("image/"):
        return False, f"content-type is {ctype!r}, not an image (is the repo public?)"
    return True, ctype or "200 ok"


def build_payload(post, channel_id, asset_base):
    body = {
        "channelId": channel_id,
        "schedulingType": "automatic",
        "text": post["text"].strip(),
    }

    # image_url in posts.yml overrides the generated card
    image_url = post.get("image_url") or f"{asset_base.rstrip('/')}/{post['image']}" if post.get("image") else None
    if not image_url and post.get("card_type"):
        # derive from card_type + id if no explicit image field
        cid = str(post.get("id","")).zfill(2)
        image_url = f"{asset_base.rstrip('/')}/pruuvn-linkedin-{cid}-{post['card_type']}.png"

    if image_url:
        body["assets"] = [{
            "image": {
                "url": image_url,
                "metadata": {"altText": post.get("alt", "")},
            }
        }]

    if post.get("draft"):
        body["saveToDraft"] = True
    elif post.get("due"):
        body["mode"] = "customScheduled"
        body["dueAt"] = post["due"]
    else:
        body["mode"] = "addToQueue"

    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    token = os.environ.get("BUFFER_TOKEN")
    channel = os.environ.get("BUFFER_CHANNEL_ID")
    base = os.environ.get("ASSET_BASE")

    missing = [n for n, v in
               [("BUFFER_TOKEN", token), ("BUFFER_CHANNEL_ID", channel),
                ("ASSET_BASE", base)] if not v]
    if missing:
        sys.exit(f"Missing env: {', '.join(missing)}")

    done = already_posted()
    posts = load_manifest()
    if args.only:
        posts = [p for p in posts if str(p["id"]) == args.only]
        if not posts:
            sys.exit(f"No post with id {args.only!r} in posts.yml")

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    failures = 0
    for post in posts:
        pid = str(post["id"])
        if pid in done and not args.only:
            print(f"[{pid}] already pushed, skipping")
            continue

        payload = build_payload(post, channel, base)

        if payload.get("assets"):
            url = payload["assets"][0]["image"]["url"]
            is_external = bool(post.get("image_url"))
            ok, detail = verify_asset(url, external=is_external)
            if not ok:
                print(f"[{pid}] SKIP - image not fetchable: {url} ({detail})")
                failures += 1
                continue
            src = "external" if is_external else "generated"
            print(f"[{pid}] image ok ({src}: {detail})")

        if args.dry_run:
            first = payload["text"].splitlines()[0]
            print(f"[{pid}] DRY RUN - would create: {first[:70]}...")
            continue

        resp = session.post(API, json=payload, timeout=30)
        if resp.status_code >= 300:
            print(f"[{pid}] FAILED {resp.status_code}: {resp.text[:300]}")
            failures += 1
            continue

        created = resp.json()
        print(f"[{pid}] created {created.get('id')} status={created.get('status')}")
        mark_posted(pid)
        time.sleep(1)          # be gentle with the API

    if failures:
        sys.exit(f"{failures} post(s) failed")
    print("done")


if __name__ == "__main__":
    main()
