#!/usr/bin/env python3
"""
Auto-update engine for the 99 Nights Guide Hub (www.portalaser.com).

Runs every 12 hours via .github/workflows/auto-update.yml and:

  1. Fetches the OFFICIAL Roblox game page (roblox.com/games/79546208627805)
     to detect the last "Updated" date and new event previews.
  2. Fetches the community update log (99-nights-in-the-forest.com/updates)
     and parses every dated update into structured entries.
  3. Cross-checks codes with public code trackers (rocodes.gg, twinfinite.net)
     and auto-ADDS new codes to data/codes.yaml (never removes any).
  4. Merges NEW updates into data/updates.yaml (dedup by date+title),
     re-stamps data/codes.yaml lastVerified, then commits & pushes.

Safety rails:
  - Pure stdlib (no requests/bs4/PyYAML) so the GitHub Actions runner
    always has everything it needs.
  - Never deletes or rewrites existing entries/codes — only appends.
  - A failed fetch is logged and skipped; the script never pushes when
    nothing changed.
  - --dry-run writes the merged files locally but skips git entirely.

Usage:
    python3 scripts/auto_update.py            # full run (fetch + merge + push)
    python3 scripts/auto_update.py --dry-run  # fetch + merge, no git
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPDATES_YAML = os.path.join(ROOT, "data", "updates.yaml")
CODES_YAML = os.path.join(ROOT, "data", "codes.yaml")
STATE_JSON = os.path.join(ROOT, "data", ".updates_state.json")

UA = ("Mozilla/5.0 (compatible; PortalaserAutoUpdate/1.0; "
      "+https://www.portalaser.com)")

# ---------------------------------------------------------------- sources
SOURCES = [
    {
        "name": "Roblox Official Game Page",
        "url": "https://www.roblox.com/games/79546208627805",
    },
    {
        "name": "99 Nights in the Forest Wiki — Updates",
        "url": "https://99-nights-in-the-forest.com/updates",
    },
    {
        "name": "RoCodes.gg — Codes",
        "url": "https://rocodes.gg/codes/99-nights-in-the-forest",
    },
    {
        "name": "Twinfinite — Codes",
        "url": "https://twinfinite.net/codes/99-nights-in-the-forest-codes/",
    },
]

CATEGORY_WORDS = {
    "classes", "events", "codes", "items", "locations", "badges", "entities",
    "guides", "rewards", "fixes", "features", "chests", "entities", "intro",
    "overview", "summary", "latest", "live", "new",
}

MONTHS = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November",
    12: "December",
}


# ---------------------------------------------------------------- helpers
def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def strip_tags(text):
    """Turn the wiki's <link text="..."/> + other tags into plain text."""
    text = re.sub(r"<link\b[^>]*?text=\"([^\"]*)\"[^>]*?/?>", r"\1", text,
                  flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def sha(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def q(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def pretty_date(dt):
    return f"{MONTHS[dt.month]} {dt.day}, {dt.year}"


def load_state():
    if os.path.exists(STATE_JSON):
        try:
            with open(STATE_JSON, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state):
    with open(STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------- parsers
def parse_wiki_updates(text):
    """Parse the wiki update log into entries + extracted codes.

    The page is a card list (shadcn-style HTML). Each update card:

        <h2 ...>...<svg/>2026-09-19</h2>
        <span class="...font-mono">2x Diamond Weekend</span>
        <div ...card-description...>Summary text...</div>
        <span class="ml-1">Classes</span> ... category chips ...
        <ul class="list-disc..."><li><a ...>bullet</a></li></ul>  (per category)
    """
    entries = []
    codes = []
    # Split on date headings; leading tags (icons) allowed, but NOT plain
    # text, so the "Latest covered update:" heading is ignored.
    parts = re.split(r"<h2[^>]*>(?:<[^>]+>)*\s*(\d{4}-\d{2}-\d{2})\s*</h2>",
                     text)
    for i in range(1, len(parts), 2):
        date = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        title = ""
        m = re.search(r'<span[^>]*font-mono[^>]*>([^<]+)</span>', body)
        if m:
            title = html.unescape(m.group(1)).strip()
        summary = ""
        m = re.search(r'<div[^>]*card-description[^>]*>(.*?)</div>', body,
                      flags=re.S)
        if m:
            summary = strip_tags(m.group(1)).strip()
        bullets = []
        for ul in re.finditer(r"<ul[^>]*>(.*?)</ul>", body, flags=re.S):
            for li in re.finditer(r"<li[^>]*>(.*?)</li>", ul.group(1),
                                  flags=re.S):
                b = strip_tags(li.group(1))
                if b:
                    bullets.append(b)
        if not title:
            continue
        entry_codes = []
        for b in bullets:
            c = parse_code_bullet(b)
            if c:
                codes.append(c)
                entry_codes.append({"code": c[0], "reward": c[1]})
        entries.append({"date": date, "title": title, "summary": summary,
                        "bullets": bullets, "codes": entry_codes})
    return entries, codes


def parse_code_bullet(bullet):
    """Strict pattern: 'Added awardwinner_yay for 15 Diamonds and three Flames'.

    Also matches 'Added the X code <code> for <reward>'. Returns
    (code, reward) or None. Conservative on purpose.
    """
    m = re.search(
        r"Added\s+(?:the\s+)?.*?code\s*[:：]?\s*"
        r"([a-z0-9_]{5,40})\s+for\s+(.+)", bullet, flags=re.I)
    if not m:
        m = re.search(
            r"Added\s+([a-z0-9_]{5,40})\s+for\s+(.+)", bullet, flags=re.I)
    if not m:
        return None
    code, reward = m.group(1).strip(), m.group(2).strip().rstrip(".")
    if code.lower() in {"codes", "reward", "update", "newcode"}:
        return None
    if not re.search(r"diamond|gem|flame|candy|token", reward, flags=re.I):
        return None
    if not (any(ch.isdigit() for ch in code) or "_" in code or len(code) >= 8):
        return None
    return code, reward


def parse_roblox(text):
    """Extract 'Updated M/D/YYYY', new-quest previews, Halloween tease."""
    result = {"updated": None, "upcoming": [], "halloween": False}
    m = re.search(r"Updated\s+(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        mo, da, ye = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result["updated"] = f"{ye:04d}-{mo:02d}-{da:02d}"
    else:
        m = re.search(r"Updated\s+([A-Z][a-z]{2})\s+(\d{1,2}),?\s+(\d{4})",
                      text)
        if m:
            mo = {v: k for k, v in MONTHS.items()}.get(m.group(1))
            if mo:
                result["updated"] = (f"{int(m.group(3)):04d}-{mo:02d}-"
                                     f"{int(m.group(2)):02d}")
    # Event previews: "Sun, Oct 4, 1:00 AM <title line>"
    for m in re.finditer(
            r"([A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{1,2}:\d{2}\s+"
            r"[AP]M)\s*\n\s*([^\n]{3,60})", text):
        when, what = m.group(1), m.group(2).strip()
        if re.search(r"quest|event|update|new", what, flags=re.I):
            result["upcoming"].append((when, what))
    if re.search(r"halloween", text, flags=re.I):
        result["halloween"] = True
    return result


def parse_code_table(text):
    """Parse code lists from trackers. Two shapes are handled:

    1. Markdown/HTML pipe rows: '| code | reward | status |'
    2. JSON-LD ItemList (used by RoCodes.gg):
         {"@type":"ItemList","name":"Active Codes List",
          "itemListElement":[{"name":"awardwinner_yay",
                              "description":"15 Diamonds"}, ...]}
    """
    codes = []
    for m in re.finditer(
            r"\|\s*([a-z0-9_ ]{3,40}?)\s*\|\s*([^|]{3,120}?)"
            r"\|\s*(active|new|working|expired|inactive|dead)\s*\|",
            text, flags=re.I):
        code, reward, status = (m.group(1).strip(), m.group(2).strip(),
                                m.group(3).lower())
        if status in ("active", "new", "working"):
            c = _accept_code(code, reward)
            if c:
                codes.append(c)
    # JSON-LD ItemList blocks
    for m in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>'
                         r'(.*?)</script>', text, flags=re.S | re.I):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            data = [data]
        for doc in data:
            if not isinstance(doc, dict):
                continue
            part = doc.get("hasPart") or doc.get("mainEntity") or {}
            if not isinstance(part, dict) or part.get("@type") != "ItemList":
                continue
            if not re.search(r"active codes|code", str(part.get("name", "")),
                             flags=re.I):
                continue
            for item in part.get("itemListElement", []):
                if not isinstance(item, dict):
                    continue
                c = _accept_code(str(item.get("name", "")),
                                 str(item.get("description", "")))
                if c:
                    codes.append(c)
    return codes


def _accept_code(code, reward):
    """Return (code, reward) when it looks like a real code with a reward."""
    code = code.strip()
    reward = reward.strip()
    if not re.search(r"diamond|gem|flame|candy", reward, flags=re.I):
        return None
    if not (any(ch.isdigit() for ch in code) or "_" in code
            or " " in code or len(code) >= 8):
        return None
    if code.lower() in {"codes", "reward", "update", "newcode"}:
        return None
    return code, reward


# ---------------------------------------------------------------- data io
def read_entries(path):
    """Return (updates, upcoming) parsed from updates.yaml, preserving every
    field (status/summary/details/codes/source/note) so a merge round-trip
    never loses data."""
    updates, upcoming = [], []
    block = None
    cur = None
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return updates, upcoming
    for raw in lines:
        m = re.match(r"^\s*(\S.*)$", raw)
        if not m:
            continue
        body = m.group(1)
        if body == "updates:":
            block, cur = "updates", None
            continue
        if body == "upcoming:":
            block, cur = "upcoming", None
            continue
        if block is None:
            continue
        m = re.match(r'^- date:\s*"(\d{4}-\d{2}-\d{2})"$', body)
        if m:
            cur = {"date": m.group(1)}
            (updates if block == "updates" else upcoming).append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r'^- code:\s*"([^"]+)"$', body)
        if m:
            cur["_pending_code"] = m.group(1)
            continue
        m = re.match(r'^(\w+):\s*(?:"(.*)")?\s*$', body)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "details":
                cur["details"] = []
                cur["_list"] = cur["details"]
            elif key == "codes":
                cur["codes"] = []
                cur["_list"] = cur["codes"]
            elif key == "reward" and cur.get("_pending_code"):
                cur.setdefault("codes", []).append(
                    {"code": cur.pop("_pending_code"), "reward": val})
            elif val is not None and key != "reward":
                cur[key] = val
            continue
        m = re.match(r'^-\s*"(.*)"$', body)
        if m and cur.get("_list") is not None:
            cur["_list"].append(m.group(1))
            continue
    for e in updates + upcoming:
        e.pop("_list", None)
        e.pop("_pending_code", None)
    return updates, upcoming


def read_codes(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def existing_codes(text):
    return set(re.findall(r'^\s*- code:\s*"([^"]+)"$', text, flags=re.M))


def emit_entry(e):
    out = [f'  - date: "{e["date"]}"', f'    title: "{q(e["title"])}"']
    status = e.get("status", "live")
    if status:
        out.append(f'    status: "{status}"')
    if e.get("summary"):
        out.append(f'    summary: "{q(e["summary"])}"')
    details = e.get("details") or []
    if details:
        out.append("    details:")
        for d in details:
            out.append(f'      - "{q(d)}"')
    codes = e.get("codes") or []
    if codes:
        out.append("    codes:")
        for c in codes:
            out.append(f'      - code: "{q(c["code"])}"')
            out.append(f'        reward: "{q(c["reward"])}"')
    src = e.get("source") or ""
    if src:
        out.append(f'    source: "{src}"')
    return "\n".join(out)


def emit_upcoming(e):
    return (f'  - date: "{e["date"]}"\n'
            f'    title: "{q(e["title"])}"\n'
            f'    note: "{q(e.get("note", ""))}"\n'
            f'    source: "{q(e.get("source", ""))}"')


def build_summary(entry, bullets):
    """Short, original, factual summary from the parsed bullets."""
    if not bullets:
        return entry["title"].strip(" .") + " — see the official changelog."
    text = " ".join(bullets)
    if len(text) > 260:
        text = text[:257].rsplit(" ", 1)[0] + "…"
    return text


def write_updates_yaml(updates, upcoming, synced):
    header = (
        "# ============================================================\n"
        "# Game update log for 99 Nights in the Forest.\n"
        "# Auto-maintained by scripts/auto_update.py (every 12h):\n"
        "#   fetches the official Roblox game page + the community\n"
        "#   update log, appends NEW updates only, never removes history.\n"
        "# ============================================================\n"
    )
    lines = [header, f'lastSynced: "{synced}"', "", "sources:"]
    for s in SOURCES[:2]:
        lines.append(f'  - name: "{q(s["name"])}"')
        lines.append(f'    url: "{s["url"]}"')
    lines.append("")
    lines.append("updates:")
    for e in sorted(updates, key=lambda x: x["date"], reverse=True):
        lines.append(emit_entry(e))
        lines.append("")
    lines.append("upcoming:")
    if upcoming:
        for e in upcoming:
            lines.append(emit_upcoming(e))
    else:
        lines.append("  # no previews yet")
    lines.append("")
    with open(UPDATES_YAML, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------- git
def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          cwd=ROOT)


def commit_and_push(dry_run):
    if dry_run:
        print("[dry-run] would commit & push changed data files")
        return True
    git("config", "user.name", "Auto Update Bot")
    git("config", "user.email", "actions@users.noreply.github.com")
    r = git("add", "data/updates.yaml", "data/codes.yaml",
            "data/.updates_state.json")
    if r.returncode != 0:
        print("git add failed:", r.stderr)
        return False
    r = git("diff", "--cached", "--quiet")
    if r.returncode == 0:
        print("nothing staged — no push")
        return True
    r = git("commit", "-m",
            f"auto: sync game updates ({datetime.date.today().isoformat()})")
    if r.returncode != 0:
        print("git commit failed:", r.stderr)
        return False
    r = git("push")
    if r.returncode != 0:
        print("git push failed:", r.stderr)
        return False
    print("pushed:", r.stdout.strip() or "ok")
    return True


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch + merge locally, skip git commit/push")
    args = ap.parse_args()

    today = datetime.date.today()
    state = load_state()
    fetched = {}

    # --- 1) fetch all sources (each failure is non-fatal; Roblox gets
    #        one retry — its CDN occasionally drops the TLS handshake) ---
    for s in SOURCES:
        for attempt in (1, 2):
            try:
                fetched[s["name"]] = fetch(s["url"])
                print(f"fetched {s['name']} ({len(fetched[s['name']])} chars)")
                break
            except Exception as exc:  # noqa: BLE001 — network errors expected
                if attempt == 2:
                    print(f"WARN: could not fetch {s['name']}: {exc}")
                else:
                    time.sleep(3)

    # --- 2) parse ---
    new_updates = []
    new_upcoming = []
    new_codes = []
    roblox_updated_changed = False

    wiki = fetched.get("99 Nights in the Forest Wiki — Updates")
    if wiki:
        entries, wiki_codes = parse_wiki_updates(wiki)
        existing_updates, existing_upcoming = read_entries(UPDATES_YAML)
        known_dates = {e["date"] for e in existing_updates}
        for e in entries:
            if not e["title"] or e["date"] in known_dates:
                continue  # date already covered — never duplicate history
            known_dates.add(e["date"])
            new_updates.append({
                "date": e["date"],
                "title": e["title"],
                "status": "live",
                "summary": build_summary(e, e["bullets"]),
                "details": e["bullets"],
                "source": SOURCES[1]["url"],
            })
        new_codes += wiki_codes

    roblox = fetched.get("Roblox Official Game Page")
    if roblox:
        rb = parse_roblox(roblox)
        if rb["updated"] and rb["updated"] != state.get("roblox_updated"):
            print(f"Roblox page now shows Updated {rb['updated']} "
                  f"(state: {state.get('roblox_updated')})")
            state["roblox_updated"] = rb["updated"]
            roblox_updated_changed = True
        for when, what in rb["upcoming"]:
            title = what
            if title not in {u["title"] for u in new_upcoming}:
                note = f"Previewed on the official Roblox page ({when})."
                if rb["halloween"]:
                    note += " Halloween plans also teased in the lobby."
                new_upcoming.append({
                    "date": today.isoformat(),
                    "title": title,
                    "note": note,
                    "source": SOURCES[0]["url"],
                })

    for name in ("RoCodes.gg — Codes", "Twinfinite — Codes"):
        text = fetched.get(name)
        if text:
            new_codes += parse_code_table(text)

    # --- 3) merge updates.yaml ---
    updates, upcoming = read_entries(UPDATES_YAML)
    updates += new_updates
    for u in new_upcoming:
        if u["title"] not in {x["title"] for x in upcoming}:
            upcoming.append(u)

    updates_changed = bool(new_updates or new_upcoming)
    if updates_changed:
        write_updates_yaml(updates, upcoming, today.isoformat())
        print(f"updates.yaml: +{len(new_updates)} new, "
              f"+{len(new_upcoming)} upcoming")

    # --- 4) merge codes.yaml (auto-add only) ---
    codes_text = read_codes(CODES_YAML)
    existing = existing_codes(codes_text)
    additions = []
    for code, reward in new_codes:
        if code.lower() in {c.lower() for c in existing}:
            continue
        additions.append((code, reward))
    codes_changed = False
    if additions or updates_changed:
        codes_text = re.sub(
            r'(lastVerified:\s*)"[^"]*"',
            lambda m: f'{m.group(1)}"{pretty_date(today)}"', codes_text, count=1)
        if additions:
            block = "".join(
                f'\n  - code: "{q(code)}"\n'
                f'    reward: "{q(reward)}"\n'
                f'    method: "lobby"\n'
                f'    note: "Auto-added by the update script on '
                f'{pretty_date(today)} — verify in-game."\n'
                for code, reward in additions)
            codes_text = codes_text.replace("\nexpired:", block + "\nexpired:")
        codes_changed = True
        with open(CODES_YAML, "w", encoding="utf-8") as f:
            f.write(codes_text)
        print(f"codes.yaml: +{len(additions)} auto-added codes")

    # --- 5) state + git: only commit when something meaningful changed ---
    had_state = os.path.exists(STATE_JSON)
    meaningful = (updates_changed or codes_changed
                  or roblox_updated_changed or not had_state)
    if not meaningful:
        print("no changes — nothing to do")
        return 0
    state["last_run"] = today.isoformat()
    save_state(state)
    if not commit_and_push(args.dry_run):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
