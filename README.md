# twinflames

A personalized job hunt dashboard. Pulls live openings from Job Bank Canada around Woodstock, ON, filters for entry-level roles, scores best fits, and shows prep tips per category.

---

## What's in v2 (fixes for v1 issues)

- **Titles parse cleanly** (no more concatenated badge text)
- **Strict location filtering** (no more Winnipeg or BC results bleeding in)
- **Refresh button** in the status bar, bypasses the cache
- **Update timestamp** shows date + time, not just time
- **Best fit scoring**: top 3-5 matches get a ★ Great fit badge based on a profile heuristic
- **Show requirements** button per job, lazy-loads from a second endpoint
- **What to prep** button per job, shows tailored tips by category
- **Cleaned footer** for privacy on a public URL
- **More cities**: added Embro, Princeton, plus broader Oxford County coverage
- **80 jobs cap** per fetch instead of 60

---

## Deploy (free, ~10 min)

### 1. Push to GitHub

```bash
cd twinflames
git init
git add .
git commit -m "twinflames v2"
git branch -M main
# Create a new repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/twinflames.git
git push -u origin main
```

### 2. Deploy on Vercel

1. [vercel.com](https://vercel.com) → sign in with GitHub
2. **Add New → Project** → pick the `twinflames` repo
3. Leave defaults → **Deploy**
4. ~1 min later you'll have a `*.vercel.app` URL

### 3. Tidy the URL (optional)

Project → **Settings → Domains** → change subdomain. Try `twinflames.vercel.app` or `arsh-jobs.vercel.app`.

---

## File map

```
twinflames/
├── index.html              the app frontend
├── api/
│   ├── jobs.py             main scraper (Job Bank, all cities)
│   └── job-details.py      lazy-load endpoint for one job's requirements
├── requirements.txt
├── vercel.json
└── README.md
```

---

## How to tweak it later

| Change | File | What to look for |
|---|---|---|
| Cities included | `api/jobs.py` | `CITIES` and `TARGET_CITIES` |
| Jobs to exclude | `api/jobs.py` | `EXCLUDE_PATTERNS` |
| Category keywords | `api/jobs.py` | `CATEGORY_KEYWORDS` |
| Best-fit scoring | `index.html` | `fitScore()` function |
| Prep tips text | `index.html` | `PREP_TIPS` object |
| Greeting / quote | `index.html` | search "four-leaf clover" |
| Footer | `index.html` | search "built by Greeky" |
| Colors | `index.html` | `:root` CSS variables |

---

## Why Indeed isn't pulled in directly

Indeed actively blocks scrapers with CAPTCHAs and IP bans. Reliable scraping requires paid services starting around $49/month. The "Search Indeed ↗" button opens a pre-filled search instead, which is free, reliable, and gets her there in one tap.

---

## Local preview

Open `index.html` directly in a browser to see the design with sample data (the live endpoints only work when deployed). To run with the live endpoints locally:

```bash
npm i -g vercel
vercel dev
```
