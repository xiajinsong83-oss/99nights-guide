#!/usr/bin/env python3
"""
Generate content/media/videos/*.md stub pages from data/videos.yaml.

Each stub becomes a page in the media section so Hugo's built-in
pagination (paginate = 15, see hugo.toml) can page through the video
archive with First / Prev / Next / Last controls.

Usage (from the project root):
    python3 scripts/gen_videos.py

Then: git add -A && git commit && git push   (Cloudflare rebuilds).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML_PATH = os.path.join(ROOT, "data", "videos.yaml")
OUT_DIR = os.path.join(ROOT, "content", "media", "videos")


def parse_blocks(text):
    """Parse the small, fixed yaml shape used by data/videos.yaml:
    list items of {title, id, category, description}."""
    blocks = []
    cur = None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r'^-\s*title:\s*"(.*)"$', s)
        if m:
            cur = {"title": m.group(1)}
            blocks.append(cur)
        elif cur is not None:
            m2 = re.match(r'^(\w+):\s*"(.*)"$', s)
            if m2:
                cur[m2.group(1)] = m2.group(2)
    return blocks


def esc(value):
    return value.replace('"', '\\"')


def main():
    with open(YAML_PATH, encoding="utf-8") as f:
        blocks = parse_blocks(f.read())

    if not blocks:
        print("No video entries found in data/videos.yaml — aborting.")
        return 1

    # Do NOT wipe the output directory: the video pages now carry hand-written
    # bodies and frontmatter (author, lastmod) from the content overhaul.
    # Regeneration only creates stubs for entries that have no page yet.
    os.makedirs(OUT_DIR, exist_ok=True)

    created = 0
    for i, b in enumerate(blocks, 1):
        title = b.get("title", "Untitled video")
        vid = b.get("id", "")
        cat = b.get("category", "Guide")
        desc = b.get("description", "")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()[:60] or f"video-{i}"
        path = os.path.join(OUT_DIR, f"v{i:02d}-{slug}.md")
        if os.path.exists(path):
            continue
        created += 1
        fm = (
            '+++\n'
            f'title = "{esc(title)}"\n'
            f'id = "{esc(vid)}"\n'
            f'category = "{esc(cat)}"\n'
            f'description = "{esc(desc)}"\n'
            f'weight = {i}\n'
            '_build = {render = "never", list = "local"}\n'
            '+++\n'
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(fm)

    print(f"Created {created} new video stub pages in content/media/videos/ (existing pages preserved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
