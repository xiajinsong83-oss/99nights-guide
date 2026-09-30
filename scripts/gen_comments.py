#!/usr/bin/env python3
"""
Generate content/feedback/comments/*.md stub pages from data/comments.yaml.

Each stub becomes a page in the feedback section so Hugo's built-in
pagination (pagerSize = 15, see hugo.toml) can page through the comment
feed with First / Prev / Next / Last controls — same mechanism as the
video archive.

Usage (from the project root):
    python3 scripts/gen_comments.py

Then: git add -A && git commit && git push   (Cloudflare rebuilds).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML_PATH = os.path.join(ROOT, "data", "comments.yaml")
OUT_DIR = os.path.join(ROOT, "content", "feedback", "comments")


def parse_blocks(text):
    """Parse the small, fixed yaml shape used by data/comments.yaml:
    list items of {id, author, date, text, likes, dislikes, pass, example}."""
    blocks = []
    cur = None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r'^-\s*id:\s*"(.*)"$', s)
        if m:
            cur = {"id": m.group(1)}
            blocks.append(cur)
        elif cur is not None:
            m2 = re.match(r'^([a-zA-Z]+):\s*(?:"(.*)"|(true|false)|(\d+))$', s)
            if m2:
                key, quoted, flag, num = m2.group(1), m2.group(2), m2.group(3), m2.group(4)
                if quoted is not None:
                    cur[key] = quoted
                elif flag is not None:
                    cur[key] = flag == "true"
                else:
                    cur[key] = int(num)
    return blocks


def esc(value):
    # TOML basic string escaping: backslash, quotes; newlines collapse to space
    return (value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " "))


def main():
    with open(YAML_PATH, encoding="utf-8") as f:
        blocks = parse_blocks(f.read())

    if not blocks:
        print("No comment entries found in data/comments.yaml — aborting.")
        return 1

    if os.path.isdir(OUT_DIR):
        for name in os.listdir(OUT_DIR):
            os.remove(os.path.join(OUT_DIR, name))
    os.makedirs(OUT_DIR, exist_ok=True)

    for i, b in enumerate(blocks, 1):
        cid = b.get("id", f"c{i}")
        author = b.get("author", "Anonymous survivor")
        date = b.get("date", "")
        text = b.get("text", "")
        likes = b.get("likes", 0)
        dislikes = b.get("dislikes", 0)
        pass_ = b.get("pass", 0)
        example = b.get("example", False)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", author).strip("-").lower()[:40] or f"comment-{i}"
        path = os.path.join(OUT_DIR, f"c{i:02d}-{slug}.md")
        fm = (
            '+++\n'
            f'title = "Comment by {esc(author)}"\n'
            f'cid = "{esc(cid)}"\n'
            f'author = "{esc(author)}"\n'
            f'date = "{esc(date)}"\n'
            f'text = "{esc(text)}"\n'
            f'likes = {likes}\n'
            f'dislikes = {dislikes}\n'
            f'pass = {pass_}\n'
            f'example = {str(example).lower()}\n'
            f'weight = {i}\n'
            '_build = {render = "never", list = "local"}\n'
            '+++\n'
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(fm)

    print(f"Generated {len(blocks)} comment stub pages in content/feedback/comments/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
