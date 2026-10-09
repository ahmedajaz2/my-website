#!/usr/bin/env python3
"""Email Buttondown subscribers about new ahmedajaz.com blog posts.

Reads blog/posts.json, diffs post URLs against scripts/newsletter-state.json,
and for each new post creates and sends a Buttondown email
(POST /v1/emails with status="about_to_send").

Modes:
  --dry-run    Log what would be sent. No API calls, no state changes.
  --check-key  Validate BUTTONDOWN_API_KEY with a read-only API call.

Environment:
  BUTTONDOWN_API_KEY  Required unless --dry-run.

Safety:
  - Sends at most MAX_PER_RUN emails per run.
  - A post URL is recorded as sent only after Buttondown returns 201.
  - API failures exit non-zero without touching state for that post.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.buttondown.com"
MAX_PER_RUN = 3
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_JSON = os.path.join(REPO_ROOT, "blog", "posts.json")
STATE_JSON = os.path.join(REPO_ROOT, "scripts", "newsletter-state.json")
SITE = "https://ahmedajaz.com"


def api(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    key = os.environ.get("BUTTONDOWN_API_KEY", "")
    if not key:
        print("ERROR: BUTTONDOWN_API_KEY is not set.", file=sys.stderr)
        sys.exit(2)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API_BASE + path, data=data, method=method)
    req.add_header("Authorization", f"Token {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8"))
        except Exception:
            detail = {"raw": "unreadable error body"}
        return e.code, detail


def check_key() -> int:
    status, body = api("GET", "/v1/subscribers?page_size=1")
    if status == 200:
        print(f"API key OK. Subscriber count: {body.get('count')}")
        return 0
    print(f"API key check FAILED (HTTP {status}): {json.dumps(body)[:500]}")
    return 1


def compose(post: dict) -> tuple[str, str]:
    url = SITE + post["url"]
    subject = f"New post: {post['title']}"
    body = (
        "New on ahmedajaz.com:\n\n"
        f"## [{post['title']}]({url})\n\n"
        f"{post.get('description', '').strip()}\n\n"
        f"[Read the full post]({url})\n"
    )
    return subject, body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-key", action="store_true")
    args = parser.parse_args()

    if args.check_key:
        return check_key()

    with open(POSTS_JSON, encoding="utf-8") as f:
        posts = json.load(f)
    try:
        with open(STATE_JSON, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {"sent_urls": []}
    sent = set(state.get("sent_urls", []))

    new_posts = [p for p in posts if p.get("url") and p["url"] not in sent]
    if not new_posts:
        print("No new posts. Nothing to send.")
        return 0

    if args.dry_run:
        print(f"DRY RUN - would send {len(new_posts)} email(s):")
        for p in new_posts:
            subject, _ = compose(p)
            print(f"  - {subject} ({SITE + p['url']})")
        return 0

    to_send = new_posts[:MAX_PER_RUN]
    if len(new_posts) > MAX_PER_RUN:
        print(f"WARNING: {len(new_posts)} new posts; capping at {MAX_PER_RUN} this run.")

    failed = False
    for post in to_send:
        subject, body = compose(post)
        status, resp = api("POST", "/v1/emails", {
            "subject": subject,
            "body": body,
            "status": "about_to_send",
            "email_type": "public",
            "canonical_url": SITE + post["url"],
        })
        if status == 201:
            print(f"SENT: {subject} (id={resp.get('id')})")
            sent.add(post["url"])
        else:
            print(f"FAILED (HTTP {status}) for {post['url']}: {json.dumps(resp)[:500]}",
                  file=sys.stderr)
            failed = True

    state["sent_urls"] = sorted(sent)
    with open(STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    print(f"State updated: {len(state['sent_urls'])} posts recorded as sent.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
