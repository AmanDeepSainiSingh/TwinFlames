"""
twinflames /api/jobs endpoint
Scrapes Job Bank Canada for openings near Woodstock, ON.
Filters out jobs that require qualifications Arsh doesn't have yet (RN/RPN, degrees, senior roles).
Returns clean JSON for the frontend.

Deployed as a Vercel serverless function. Cached at the edge for 1 hour.
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import quote
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import requests
from bs4 import BeautifulSoup


# Cities within roughly 20 minutes of Woodstock
CITIES = [
    "Woodstock, ON",
    "Ingersoll, ON",
    "Tavistock, ON",
    "Beachville, ON",
    "Norwich, ON",
    "Innerkip, ON",
]

# Hard exclude: jobs that need credentials Arsh doesn't have
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
    r"\bcfa\b", r"\bcpa\b", r"\bca,? cpa\b",
    r"\bmechanic\b", r"\bwelder\b", r"\bmillwright\b",
    r"\bclass (1|a|az|dz)\b", r"\baz licence\b", r"\bdz licence\b",
    r"\bbachelor'?s? degree\b", r"\bmaster'?s? degree\b",
]

# Soft include hints: signals it's beginner-friendly
INCLUDE_HINTS = [
    "no experience", "entry level", "entry-level", "training provided",
    "will train", "student", "part-time", "casual", "weekend",
    "no certification", "no degree",
]

# Category tagging
CATEGORY_KEYWORDS = {
    "healthcare": [
        "medical office", "pharmacy assist", "dental assist", "dental receptionist",
        "clinic", "patient", "nurse aide", "nursing aide", "personal support",
        "care aide", "health care aide", "lab assist", "phlebotom",
        "optometr", "veterinary assist", "vet clinic",
    ],
    "retail-cafe": [
        "cashier", "sales associate", "sales clerk", "retail", "store clerk",
        "cafe", "barista", "server", "waitstaff", "waiter", "waitress",
        "food counter", "kitchen helper", "cook", "line cook", "prep cook",
        "sandwich artist", "subway", "tim hortons", "mcdonald", "starbucks",
        "wendy", "burger king", "a&w", "harvey", "pizza", "restaurant",
        "grocery", "stock", "shelf", "bagger", "host",
    ],
    "admin": [
        "receptionist", "office assist", "administrative", "admin assist",
        "clerk", "data entry", "secretary", "front desk", "office support",
        "filing", "scheduling",
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


def parse_relative_date(date_str: str) -> str:
    """Normalize 'Posted: 2025-05-19' or similar to friendly relative text."""
    if not date_str:
        return ""
    s = date_str.strip()
    # Try YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            posted = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            delta = (datetime.now() - posted).days
            if delta <= 0:   return "Today"
            if delta == 1:   return "Yesterday"
            if delta < 7:    return f"{delta} days ago"
            if delta < 30:   return f"{delta // 7} week{'s' if delta // 7 > 1 else ''} ago"
            return s
        except ValueError:
            pass
    return s


def scrape_city(city: str, max_results: int = 30) -> list:
    """Fetch Job Bank search results for a given city."""
    url = (
        "https://www.jobbank.gc.ca/jobsearch/jobsearch"
        f"?searchstring=&locationstring={quote(city)}&sort=M&fage=14"
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

    # Job Bank lists results inside <article> elements. We look broadly to stay resilient.
    articles = soup.find_all("article")
    for art in articles[:max_results]:
        link_el = art.find("a", href=re.compile(r"/jobsearch/jobposting/"))
        if not link_el:
            continue

        # Title (NOC title / first heading)
        title_el = art.find(class_=re.compile(r"noctitle|title", re.I))
        title = title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)

        # Employer
        emp_el = art.find(class_=re.compile(r"business|employer", re.I))
        employer = emp_el.get_text(strip=True) if emp_el else ""

        # Location
        loc_el = art.find(class_=re.compile(r"location", re.I))
        location = loc_el.get_text(strip=True) if loc_el else city

        # Salary
        sal_el = art.find(class_=re.compile(r"salary|wage", re.I))
        salary = sal_el.get_text(" ", strip=True) if sal_el else ""

        # Date
        date_el = art.find(class_=re.compile(r"date", re.I))
        date_str = date_el.get_text(strip=True) if date_el else ""

        # Job type (full-time / part-time)
        type_el = art.find(class_=re.compile(r"telework|type|term", re.I))
        job_type = type_el.get_text(strip=True) if type_el else ""

        # Apply URL
        href = link_el.get("href", "")
        if href.startswith("/"):
            apply_url = "https://www.jobbank.gc.ca" + href
        else:
            apply_url = href

        # Description-ish blob from the whole card text, used for filtering
        full_blob = art.get_text(" ", strip=True)

        if not title or is_excluded(title, full_blob):
            continue

        jobs.append({
            "title": title,
            "employer": employer or "Employer not listed",
            "location": location.replace("Location", "").strip(": ").strip() or city,
            "salary": clean_salary(salary),
            "job_type": clean_job_type(job_type),
            "posted": parse_relative_date(date_str),
            "url": apply_url,
            "category": categorize(title, full_blob),
            "_source": "jobbank",
        })

    return jobs


def clean_salary(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"^Salary:?\s*", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:60]


def clean_job_type(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    if "part" in s and "time" in s:   return "Part-time"
    if "full" in s and "time" in s:   return "Full-time"
    if "casual" in s:                 return "Casual"
    if "seasonal" in s:               return "Seasonal"
    return ""


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


def fetch_all() -> dict:
    jobs = []
    # Fetch cities in parallel so we stay under Vercel's 10s timeout
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(scrape_city, c): c for c in CITIES}
        for fut in as_completed(futures, timeout=9):
            try:
                jobs.extend(fut.result())
            except Exception:
                continue

    jobs = dedupe(jobs)

    # Sort: today first, then most recent
    def sort_key(j):
        p = (j.get("posted") or "").lower()
        if "today" in p:      return (0, 0)
        if "yesterday" in p:  return (1, 0)
        m = re.match(r"(\d+) day", p)
        if m: return (2, int(m.group(1)))
        m = re.match(r"(\d+) week", p)
        if m: return (3, int(m.group(1)))
        return (4, 99)
    jobs.sort(key=sort_key)

    return {
        "jobs": jobs[:60],
        "updated": datetime.now().strftime("%-I:%M %p"),
        "city_count": len(CITIES),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            payload = fetch_all()
            status = 200
        except Exception as e:
            payload = {"jobs": [], "error": str(e), "updated": ""}
            status = 200  # still 200 so the frontend can fall back gracefully

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Cache at Vercel's edge for 1 hour, allow stale for a day
        self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
