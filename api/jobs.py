"""
twinflames /api/jobs endpoint
Scrapes Job Bank Canada for openings near Woodstock, ON.

Fixes from v1:
- Exact class match for title (no more concatenated badge text)
- Hard post-filter on location (no more Winnipeg/BC results)
- Better date parsing (handles "May 21, 2026" format)
- Returns short description snippet for context
- Supports ?refresh=1 to bypass cache
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import quote, urlparse, parse_qs
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import requests
from bs4 import BeautifulSoup


# Cities within roughly 20 minutes of Woodstock, ON
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

# Lowercase city names used to verify each returned job is actually nearby
TARGET_CITIES = {
    "woodstock", "ingersoll", "tavistock", "beachville",
    "norwich", "innerkip", "embro", "princeton", "bright",
    "oxford", "drumbo",
}

# Hard exclude: needs credentials Arsh doesn't have
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


def is_excluded(title: str, description: str) -> bool:
    text = (title + " " + description).lower()
    return any(re.search(p, text) for p in EXCLUDE_PATTERNS)


def categorize(title: str, description: str) -> str:
    text = (title + " " + description).lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return cat
    return "other"


def location_in_target_area(location: str) -> bool:
    """Discard jobs that aren't in our Woodstock-area Ontario cities."""
    if not location:
        return False
    loc = location.lower()
    # Must mention one of our target cities
    has_city = any(c in loc for c in TARGET_CITIES)
    # And must be Ontario (Job Bank format is "Woodstock (ON)")
    has_ontario = "(on)" in loc or "ontario" in loc or ", on" in loc
    return has_city and has_ontario


def parse_relative_date(date_str: str) -> str:
    """Turn '2026-05-21' or 'May 21, 2026' into 'Today', 'Yesterday', 'N days ago'."""
    if not date_str:
        return ""
    s = re.sub(r"^Date posted\s*:?\s*", "", date_str, flags=re.I).strip()

    posted = None
    # YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            posted = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # "May 21, 2026" style
    if not posted:
        try:
            posted = datetime.strptime(s, "%B %d, %Y")
        except ValueError:
            try:
                posted = datetime.strptime(s, "%b %d, %Y")
            except ValueError:
                pass

    if posted:
        delta = (datetime.now() - posted).days
        if delta <= 0:   return "Today"
        if delta == 1:   return "Yesterday"
        if delta < 7:    return f"{delta} days ago"
        weeks = delta // 7
        if delta < 30:   return f"{weeks} week{'s' if weeks > 1 else ''} ago"
        return s

    return s


def clean_salary(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"^Salary\s*:?\s*", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s)
    # Trim trailing notes like "(to be negotiated)" to keep cards clean
    s = re.sub(r"\s*\(to be negotiated\)\s*", "", s, flags=re.I).strip()
    return s[:80]


def clean_location(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"^Location\s*:?\s*", "", s, flags=re.I).strip()
    return re.sub(r"\s+", " ", s)[:60]


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def detect_job_type(blob: str) -> str:
    b = blob.lower()
    if "part time" in b or "part-time" in b: return "Part-time"
    if "full time" in b or "full-time" in b: return "Full-time"
    if "casual" in b:   return "Casual"
    if "seasonal" in b: return "Seasonal"
    return ""


def scrape_city(city: str, page_size: int = 50) -> list:
    """Fetch and parse one city's worth of Job Bank search results."""
    url = (
        "https://www.jobbank.gc.ca/jobsearch/jobsearch"
        f"?searchstring=&locationstring={quote(city)}&sort=M&fage=14&page=1"
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
        link_el = art.find("a", href=re.compile(r"/jobsearch/jobposting/"))
        if not link_el:
            continue

        # ── Title: EXACT class match, not regex (fix for v1 bug) ──
        title_el = art.find(class_="noctitle")
        title = clean_text(title_el.get_text() if title_el else "")
        if not title:
            continue

        # Employer
        emp_el = art.find(class_="business")
        employer = clean_text(emp_el.get_text() if emp_el else "")
        # Strip "Employer:" prefix and screen-reader text
        employer = re.sub(r"^Employer\s*:?\s*", "", employer, flags=re.I).strip()

        # Location
        loc_el = art.find(class_="location")
        location = clean_location(loc_el.get_text(" ") if loc_el else "")

        # Hard location filter (fix for v1 Winnipeg/BC bug)
        if not location_in_target_area(location):
            continue

        # Salary
        sal_el = art.find(class_="salary")
        salary = clean_salary(sal_el.get_text(" ") if sal_el else "")

        # Date
        date_el = art.find(class_="date")
        date_str = parse_relative_date(date_el.get_text() if date_el else "")

        # Short summary snippet (used for category + filter, also shown in card)
        summary_el = art.find(class_="summary") or art.find("p")
        summary = clean_text(summary_el.get_text() if summary_el else "")[:240]

        # Full text blob for filtering
        blob = title + " " + summary + " " + employer

        if is_excluded(title, blob):
            continue

        # Apply URL
        href = link_el.get("href", "")
        apply_url = ("https://www.jobbank.gc.ca" + href) if href.startswith("/") else href

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


def dedupe(jobs: list) -> list:
    seen = set()
    out = []
    for j in jobs:
        key = (j["title"].lower(), j["employer"].lower(), j["location"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
    return out


def sort_key(j: dict):
    p = (j.get("posted") or "").lower()
    if "today" in p:      return (0, 0)
    if "yesterday" in p:  return (1, 0)
    m = re.match(r"(\d+) day", p)
    if m: return (2, int(m.group(1)))
    m = re.match(r"(\d+) week", p)
    if m: return (3, int(m.group(1)))
    return (4, 99)


def fetch_all() -> dict:
    jobs = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(scrape_city, c): c for c in CITIES}
        for fut in as_completed(futures, timeout=9):
            try:
                jobs.extend(fut.result())
            except Exception:
                continue

    jobs = dedupe(jobs)
    jobs.sort(key=sort_key)

    now = datetime.now()
    return {
        "jobs": jobs[:80],
        "updated_at": now.isoformat(),
        "updated_label": now.strftime("%b %-d, %-I:%M %p"),
        "city_count": len(CITIES),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Check for refresh query
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
