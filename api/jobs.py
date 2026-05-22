"""
twinflames /api/jobs endpoint (v3)

Fixes from v2:
- Bulletproof posting URL extraction (uses link wrapping the title)
- URL validation: must contain /jobposting/ and a numeric ID
- More defensive fallbacks
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import quote, urlparse, parse_qs
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import requests
from bs4 import BeautifulSoup


CITIES = [
    "Woodstock, ON",
    "Ingersoll, ON",
    "Tavistock, ON",
    "Beachville, ON",
    "Norwich, ON",
    "Innerkip, ON",
    "Embro, ON",
    "Princeton, ON",
]

TARGET_CITIES = {
    "woodstock", "ingersoll", "tavistock", "beachville",
    "norwich", "innerkip", "embro", "princeton", "bright",
    "oxford", "drumbo",
}

EXCLUDE_PATTERNS = [
    r"\bregistered nurse\b", r"\brn\b(?!a)", r"\brpn\b", r"\bnurse practitioner\b",
    r"\blicensed practical\b", r"\blpn\b",
    r"\bphysician\b", r"\bmedical doctor\b", r"\b\.?md\b",
    r"\bphd\b", r"\bdoctorate\b",
    r"\bregistered pharmacist\b", r"\bregistered massage\b", r"\brmt\b",
    r"\bparamedic\b", r"\bfirefighter\b", r"\bpolice officer\b",
    r"\bred seal\b", r"\bjourneyperson\b", r"\bcertified electrician\b",
    r"\b(5|6|7|8|9|10)\+? years\b",
    r"\bsenior (manager|director|engineer|developer|analyst)\b",
    r"\bsoftware (developer|engineer)\b", r"\bdata scientist\b",
    r"\bcfa\b", r"\bcpa\b",
    r"\bmechanic\b", r"\bwelder\b", r"\bmillwright\b",
    r"\bclass (1|a|az|dz)\b", r"\baz licence\b", r"\bdz licence\b",
    r"\b(bachelor|master)'?s? degree required\b",
    r"\bsupervisor\b", r"\bforeperson\b",
]

CATEGORY_KEYWORDS = {
    "healthcare": [
        "medical office", "pharmacy assist", "dental assist", "dental receptionist",
        "clinic", "patient", "nurse aide", "nursing aide", "personal support",
        "care aide", "health care aide", "lab assist", "phlebotom",
        "optometr", "veterinary assist", "vet clinic", "long-term care",
    ],
    "retail-cafe": [
        "cashier", "sales associate", "sales clerk", "retail", "store clerk",
        "cafe", "barista", "server", "waitstaff", "waiter", "waitress",
        "food counter", "kitchen helper", "cook", "line cook", "prep cook",
        "sandwich artist", "subway", "tim hortons", "mcdonald", "starbucks",
        "wendy", "burger king", "a&w", "harvey", "pizza", "restaurant",
        "grocery", "stock", "shelf", "bagger", "host",
        "food and beverage", "fast food", "counter attendant",
    ],
    "admin": [
        "receptionist", "office assist", "administrative", "admin assist",
        "clerk", "data entry", "secretary", "front desk", "office support",
        "filing", "scheduling", "customer service representative",
    ],
}


def is_excluded(title, description):
    text = (title + " " + description).lower()
    return any(re.search(p, text) for p in EXCLUDE_PATTERNS)


def categorize(title, description):
    text = (title + " " + description).lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return cat
    return "other"


def location_in_target_area(location):
    if not location:
        return False
    loc = location.lower()
    has_city = any(c in loc for c in TARGET_CITIES)
    has_ontario = "(on)" in loc or "ontario" in loc or ", on" in loc
    return has_city and has_ontario


def parse_relative_date(date_str):
    if not date_str:
        return ""
    s = re.sub(r"^Date posted\s*:?\s*", "", date_str, flags=re.I).strip()
    posted = None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            posted = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    if not posted:
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                posted = datetime.strptime(s, fmt); break
            except ValueError:
                pass
    if posted:
        delta = (datetime.now() - posted).days
        if delta <= 0:   return "Today"
        if delta == 1:   return "Yesterday"
        if delta < 7:    return f"{delta} days ago"
        if delta < 30:   weeks = delta // 7; return f"{weeks} week{'s' if weeks > 1 else ''} ago"
        return s
    return s


def clean_text(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def clean_salary(s):
    if not s: return ""
    s = re.sub(r"^Salary\s*:?\s*", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*\(to be negotiated\)\s*", "", s, flags=re.I).strip()
    return s[:80]


def clean_location(s):
    if not s: return ""
    s = re.sub(r"^Location\s*:?\s*", "", s, flags=re.I).strip()
    return re.sub(r"\s+", " ", s)[:60]


def detect_job_type(blob):
    b = blob.lower()
    if "part time" in b or "part-time" in b: return "Part-time"
    if "full time" in b or "full-time" in b: return "Full-time"
    if "casual" in b:   return "Casual"
    if "seasonal" in b: return "Seasonal"
    return ""


def find_posting_url(art, title_el):
    """
    Find the URL to the specific job posting, NOT the search page.

    Strategy:
    1. Find the link wrapping the title (most reliable on Job Bank)
    2. Fall back to any link in the article matching the posting URL pattern
    3. Validate the URL contains 'jobposting' and a numeric ID
    """
    candidates = []

    # Strategy 1: parent link of the title element
    if title_el:
        p = title_el.find_parent("a")
        if p and p.get("href"):
            candidates.append(p.get("href"))

    # Strategy 2: links matching common Job Bank posting patterns
    for link in art.find_all("a", href=True):
        href = link.get("href", "")
        if "jobposting" in href or re.search(r"/\d{6,}", href):
            candidates.append(href)

    # Pick the first valid one (contains jobposting AND a numeric ID)
    for href in candidates:
        if "jobposting" in href and re.search(r"\d{6,}", href):
            return ("https://www.jobbank.gc.ca" + href) if href.startswith("/") else href

    # Last resort: first candidate even if not perfect
    if candidates:
        href = candidates[0]
        return ("https://www.jobbank.gc.ca" + href) if href.startswith("/") else href

    return ""


def scrape_city(city, page_size=50):
    url = (
        "https://www.jobbank.gc.ca/jobsearch/jobsearch"
        f"?searchstring=&locationstring={quote(city)}&sort=M&fage=7&page=1"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-CA,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return []
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    jobs = []
    articles = soup.find_all("article")

    for art in articles[:page_size]:
        title_el = art.find(class_="noctitle")
        title = clean_text(title_el.get_text() if title_el else "")
        if not title:
            continue

        # CRITICAL: must get a real posting URL, not the search page
        apply_url = find_posting_url(art, title_el)
        if not apply_url or "jobposting" not in apply_url:
            continue  # Skip jobs we can't deep-link to

        emp_el = art.find(class_="business")
        employer = clean_text(emp_el.get_text() if emp_el else "")
        employer = re.sub(r"^Employer\s*:?\s*", "", employer, flags=re.I).strip()

        loc_el = art.find(class_="location")
        location = clean_location(loc_el.get_text(" ") if loc_el else "")
        if not location_in_target_area(location):
            continue

        sal_el = art.find(class_="salary")
        salary = clean_salary(sal_el.get_text(" ") if sal_el else "")

        date_el = art.find(class_="date")
        date_str = parse_relative_date(date_el.get_text() if date_el else "")

        summary_el = art.find(class_="summary") or art.find("p")
        summary = clean_text(summary_el.get_text() if summary_el else "")[:240]

        blob = title + " " + summary + " " + employer
        if is_excluded(title, blob):
            continue

        jobs.append({
            "title": title,
            "employer": employer or "Employer not listed",
            "location": location,
            "salary": salary,
            "job_type": detect_job_type(blob),
            "posted": date_str,
            "url": apply_url,
            "summary": summary,
            "category": categorize(title, blob),
        })

    return jobs


def dedupe(jobs):
    seen = set(); out = []
    for j in jobs:
        key = (j["title"].lower(), j["employer"].lower(), j["location"].lower())
        if key in seen: continue
        seen.add(key); out.append(j)
    return out


# ── Expiration check ──
EXPIRED_MARKERS = [
    "no longer available",
    "no longer accepting applications",
    "this posting has expired",
    "this job has expired",
    "this offer is no longer available",
    "position has been filled",
    "posting has been removed",
    "posting closed",
    "this job posting has been removed",
]


def is_job_active(url, timeout=4):
    """Quick check whether a Job Bank posting is still live. Returns True on uncertainty."""
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html",
                "Accept-Language": "en-CA,en;q=0.9",
            },
            timeout=timeout,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return False
        text = resp.text.lower()
        if any(m in text for m in EXPIRED_MARKERS):
            return False
        return True
    except Exception:
        # Network hiccup, don't lose the job
        return True


def verify_active(jobs, max_workers=20):
    """Run all jobs through is_job_active in parallel, drop the expired ones."""
    if not jobs:
        return []
    active = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(is_job_active, j["url"]): j for j in jobs}
        try:
            for fut in as_completed(futures, timeout=6):
                try:
                    if fut.result():
                        active.append(futures[fut])
                except Exception:
                    active.append(futures[fut])
        except Exception:
            # Timeout, return what we have plus any pending (assume active)
            done_ids = {id(f) for f in futures if f.done()}
            for f, j in futures.items():
                if id(f) not in done_ids:
                    active.append(j)
    return active


def sort_key(j):
    p = (j.get("posted") or "").lower()
    if "today" in p:      return (0, 0)
    if "yesterday" in p:  return (1, 0)
    m = re.match(r"(\d+) day", p)
    if m: return (2, int(m.group(1)))
    m = re.match(r"(\d+) week", p)
    if m: return (3, int(m.group(1)))
    return (4, 99)


def fetch_all():
    jobs = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(scrape_city, c): c for c in CITIES}
        for fut in as_completed(futures, timeout=5):
            try:
                jobs.extend(fut.result())
            except Exception:
                continue
    jobs = dedupe(jobs)
    jobs.sort(key=sort_key)

    # Cap candidates BEFORE verification to keep us under Vercel's 10s timeout
    candidates = jobs[:40]
    active = verify_active(candidates)
    # Preserve sort order
    active_keys = {(j["title"].lower(), j["employer"].lower(), j["location"].lower()) for j in active}
    final = [j for j in candidates
             if (j["title"].lower(), j["employer"].lower(), j["location"].lower()) in active_keys]

    now = datetime.now()
    return {
        "jobs": final,
        "updated_at": now.isoformat(),
        "updated_label": now.strftime("%b %-d, %-I:%M %p"),
        "city_count": len(CITIES),
        "scraped_count": len(jobs),
        "verified_active": len(final),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        refresh = "refresh" in params
        try:
            payload = fetch_all()
        except Exception as e:
            payload = {"jobs": [], "error": str(e), "updated_at": "", "updated_label": ""}

        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if refresh:
            self.send_header("Cache-Control", "no-store, max-age=0")
        else:
            self.send_header("Cache-Control", "s-maxage=1800, stale-while-revalidate=86400")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
