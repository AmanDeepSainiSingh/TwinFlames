# twinflames v3

A personalized job hunt dashboard. Pulls live openings from Job Bank Canada around Woodstock, ON, filters for entry-level roles, scores best fits, shows distance from home, and generates prep notes tailored to each job's actual requirements.

---

## v3 fixes

- **Apply links now go to the actual posting**, not the generic Job Bank search page. URL extraction now uses the link wrapping the title element with strict validation (must contain `jobposting` and a numeric ID), and skips any job we can't deep-link to.
- **Requirements actually load**. The details endpoint now correctly parses Job Bank's `<dl>/<dt>/<dd>` definition list structure (which is what they actually use), pulling Education, Experience, Languages, Skills, Tasks, and Benefits sections.
- **Prep notes are now job-specific**. Instead of generic category tips, the app reads the actual requirements and generates targeted advice. If the job mentions "cash handling," it suggests leading with Subway experience. If it mentions "patient confidentiality," it flags her health science background. If it requires Smart Serve, it tells her how to get it.
- **One consolidated "View details & prep notes" button** per card, instead of two separate buttons. Cleaner UX.
- **Distance from home** shown on each card based on 320 Mill St, Woodstock. Drive time in minutes and km.

---

## Deploy (free)

```bash
cd twinflames
git init
git add .
git commit -m "twinflames v3"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/twinflames.git
git push -u origin main
```

Then on vercel.com → **Add New → Project** → pick the repo → **Deploy**.

If you already deployed v1 or v2, just push v3 to the same repo and Vercel auto-redeploys in ~30 seconds.

---

## File map

```
twinflames/
├── index.html              frontend
├── api/
│   ├── jobs.py             main scraper
│   └── job-details.py      lazy-loaded requirements/details
├── requirements.txt
├── vercel.json
└── README.md
```

---

## Tuning

| Change | Where |
|---|---|
| Cities | `api/jobs.py` → `CITIES` and `TARGET_CITIES` |
| Exclude rules | `api/jobs.py` → `EXCLUDE_PATTERNS` |
| Category words | `api/jobs.py` → `CATEGORY_KEYWORDS` |
| Distance from home | `index.html` → `DISTANCES` (if you move) |
| Best-fit scoring | `index.html` → `fitScore()` |
| Prep notes logic | `index.html` → `generatePrepNotes()` |
| Greeting / quote | `index.html` → search "four-leaf clover" |
| Footer | `index.html` → search "built by Greeky" |

---

## Debugging tip

If a particular job's "View details" panel shows the generic fallback, open the network tab and look at the `/api/job-details` response. The `_debug_dl_keys` field lists every `<dt>` label found on that posting page, so you can see which labels Job Bank used and add them to the matching logic in `api/job-details.py` if needed.
