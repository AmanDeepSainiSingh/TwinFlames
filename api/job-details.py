"""
twinflames /api/job-details endpoint
Lazy-loads full details for a single Job Bank job posting.
Called when Arsh taps "Show requirements" on a job card.
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import re
import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-CA,en;q=0.9",
}


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def safe_section(soup, label_text: str, max_items: int = 8) -> list:
    """
    Find a labeled section on a Job Bank posting page and return its bullet items.
    Job Bank usually uses <h3>Label</h3> followed by <ul>...</ul> or a <p>.
    """
    for h in soup.find_all(["h2", "h3", "h4"]):
        if label_text.lower() in clean_text(h.get_text()).lower():
            # Walk forward until we hit a list or paragraph
            sib = h.find_next_sibling()
            depth = 0
            while sib and depth < 4:
                if sib.name in ("ul", "ol"):
                    items = [clean_text(li.get_text()) for li in sib.find_all("li")]
                    return [i for i in items if i][:max_items]
                if sib.name == "p" and clean_text(sib.get_text()):
                    txt = clean_text(sib.get_text())
                    # Split on bullets or semicolons if it's one paragraph
                    parts = re.split(r"[•;]\s*", txt)
                    return [p for p in parts if p][:max_items]
                sib = sib.find_next_sibling()
                depth += 1
    return []


def fetch_details(url: str) -> dict:
    # Only allow Job Bank URLs for safety
    if "jobbank.gc.ca" not in url:
        return {"error": "invalid url"}

    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            return {"error": f"http {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}

    soup = BeautifulSoup(resp.text, "html.parser")

    requirements = (
        safe_section(soup, "Requirements")
        or safe_section(soup, "Qualifications")
        or safe_section(soup, "Education")
    )
    experience = safe_section(soup, "Experience")
    tasks      = safe_section(soup, "Tasks") or safe_section(soup, "Responsibilities")
    benefits   = safe_section(soup, "Benefits") or safe_section(soup, "Other benefits")
    languages  = safe_section(soup, "Languages")

    # Short job overview blurb (first big paragraph in main content)
    overview = ""
    main = soup.find("main") or soup
    for p in main.find_all("p"):
        t = clean_text(p.get_text())
        if 60 < len(t) < 400 and "log in" not in t.lower():
            overview = t
            break

    return {
        "overview": overview,
        "requirements": requirements,
        "experience": experience,
        "tasks": tasks[:6],
        "benefits": benefits[:6],
        "languages": languages,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        url = params.get("url", [""])[0]

        if not url:
            payload = {"error": "url param required"}
            status = 400
        else:
            payload = fetch_details(url)
            status = 200

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Job details rarely change, cache aggressively
        self.send_header("Cache-Control", "s-maxage=86400, stale-while-revalidate=604800")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
