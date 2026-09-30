+++
title = "Site Update — September 2026: New Architecture, Codes Verified, Videos Coming"
description = "September 2026 site update: full site moved to a static data-driven architecture, codes re-verified, and the video section prepared for quest walkthroughs."
category = "Site"
date = 2026-09-30
lastmod = 2026-09-30
+++

Big month for the hub. Here's what changed:

## What's new

- **New architecture** — the site moved to a data-driven static build (Route A): every page is generated from content files, and the Codes page now renders from a single data file. Updating a code is now a one-file change.
- **Codes re-verified** — `forestwakesup26`, `afterparty` and the `yay fishing` chat code remain working; the expired archive keeps `happyhalloween` with context.
- **Video section prepared** — the [Videos page](/media/) is live with embed slots ready for quest walkthroughs and boss guides.

## What's in the writing queue

- Spawn timetable (night-by-night monster schedule).
- Full taming list and pet roles.
- Forest Rage hard mode numbers (Corruption rates, Rift timers, Research Outpost costs).

## How updates work now

Codes, videos and freshness dates live in `data/` files. A single push rebuilds the whole site in about a minute — no server, no CMS, no database.
