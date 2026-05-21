# twinflames 🌸💙

A personalized job hunt dashboard for Arsh. Pulls live openings from Job Bank Canada around Woodstock, ON, filters for entry-level roles she's actually qualified for (no degrees or certifications required), and gives her one-tap access to Indeed and LinkedIn searches.

Built with love by Greeky.

---

## What it does

- Fetches Job Bank Canada listings every hour for: Woodstock, Ingersoll, Tavistock, Beachville, Norwich, Innerkip
- Filters out jobs requiring RN/RPN, degrees, senior roles, trades licences, etc.
- Tags jobs into Healthcare, Retail/Cafe, Admin, or Other
- Lets Arsh save jobs locally (stored in her browser)
- One-click smart search URLs for Indeed and LinkedIn

---

## Deploy it (free, ~10 minutes)

### 1. Push to GitHub

```bash
cd twinflames
git init
git add .
git commit -m "twinflames v1, for Arsh"
git branch -M main
# create a new repo on github.com first, then:
git remote add origin https://github.com/YOUR_USERNAME/twinflames.git
git push -u origin main
```

### 2. Deploy on Vercel

1. Go to [vercel.com](https://vercel.com) and sign in with your GitHub
2. Click **Add New → Project**
3. Pick the `twinflames` repo, click **Import**
4. Leave all defaults, click **Deploy**
5. Wait ~1 minute. You'll get a URL like `twinflames-xyz.vercel.app`

### 3. Customize the URL (optional)

In your Vercel project → **Settings → Domains**, you can change the subdomain to something cleaner like `twinflames.vercel.app` (if available) or `arsh-jobs.vercel.app`.

That's it. Share the URL with Arsh.

---

## Local preview

You can open `index.html` directly in your browser to see the design. It'll show sample jobs because `/api/jobs` only works when deployed. To test the live backend locally, install the Vercel CLI:

```bash
npm i -g vercel
vercel dev
```

Then open `http://localhost:3000`.

---

## How to tweak it later

| What to change | Where |
|---|---|
| Cities included | `api/jobs.py` → `CITIES` list |
| Jobs to exclude | `api/jobs.py` → `EXCLUDE_PATTERNS` |
| Category keywords | `api/jobs.py` → `CATEGORY_KEYWORDS` |
| Greeting / quote | `index.html` → search for "four-leaf clover" |
| Footer message | `index.html` → search for "tere liye" |
| Colors | `index.html` → `:root` CSS variables |

---

## Tech stack

- **Frontend**: pure HTML/CSS/JS (no framework, fast)
- **Backend**: Python serverless function on Vercel (free tier)
- **Data**: Job Bank Canada public search, scraped server-side
- **Caching**: 1-hour edge cache on Vercel CDN

---

🌸
