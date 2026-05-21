"""
twinflames /api/job-details endpoint (v3)
Extracts structured details from a Job Bank posting page.

Job Bank uses <dl>/<dt>/<dd> definition lists for sections like:
  <dt>Education</dt><dd><ul><li>...</li></ul></dd>
  <dt>Experience</dt><dd>Will train</dd>
  <dt>Tasks</dt><dd><ul>...</ul></dd>
  <dt>Languages</dt><dd>English</dd>

Plus header-based sections as a fallback.
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


def clean_text(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def extract_dl_sections(soup):
    """Pull all <dt>...</dt><dd>...</dd> pairs from the page."""
    sections = {}
    for dt in soup.find_all("dt"):
        label = clean_text(dt.get_text()).lower().rstrip(":")
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        # Try list items first
        lis = dd.find_all("li")
        if lis:
            items = [clean_text(li.get_text()) for li in lis]
            items = [i for i in items if i]
            if items:
                sections[label] = items
                continue
        # Otherwise grab the text content split on common separators
        text = clean_text(dd.get_text())
        if text:
            # Split on bullets or semicolons within a single dd
            parts = [p.strip() for p in re.split(r"[•·;]\s*", text) if p.strip()]
            sections[label] = parts if len(parts) > 1 else [text]
    return sections


def extract_heading_section(soup, labels, max_items=10):
    """Find a heading containing one of the labels, return its list items."""
    targets = [l.lower() for l in labels]
    for h in soup.find_all(["h2", "h3", "h4"]):
        text = clean_text(h.get_text()).lower()
        if not any(t in text for t in targets):
            continue
        sib = h.find_next_sibling()
        depth = 0
        while sib and depth < 6:
            if sib.name in ("ul", "ol"):
                items = [clean_text(li.get_text()) for li in sib.find_all("li")]
                items = [i for i in items if i]
                if items:
                    return items[:max_items]
            if sib.name in ("p", "div"):
                t = clean_text(sib.get_text())
                if 20 < len(t) < 600:
                    parts = [p.strip() for p in re.split(r"[•·;]\s*", t) if p.strip()]
                    return (parts if len(parts) > 1 else [t])[:max_items]
            if sib.name in ("h2", "h3"):
                break
            sib = sib.find_next_sibling()
            depth += 1
    return []


def get_section(dl_sections, labels, soup=None, max_items=10):
    """Try <dl> first, fall back to heading search. labels are tried in order."""
    for label in labels:
        for key, value in dl_sections.items():
            if label in key:
                return value[:max_items]
    if soup is not None:
        return extract_heading_section(soup, labels, max_items=max_items)
    return []


def extract_overview(soup):
    """Find a meaningful job description paragraph, skipping nav/sidebar boilerplate."""
    main = soup.find("main") or soup.find(id="jobpostingdetail") or soup
    boilerplate_kw = (
        "log in", "sign in", "favourite", "favorite", "to add a job",
        "cookies", "privacy", "save this job", "report this job",
    )
    for p in main.find_all(["p", "div"]):
        t = clean_text(p.get_text())
        if not (60 < len(t) < 500):
            continue
        if any(b in t.lower() for b in boilerplate_kw):
            continue
        # Skip if it's likely a list container or has many child elements
        if len(p.find_all(["a", "li", "input", "button"])) > 2:
            continue
        return t
    return ""


def fetch_details(url):
    if "jobbank.gc.ca" not in url:
        return {"error": "invalid url"}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            return {"error": f"http {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}

    soup = BeautifulSoup(resp.text, "html.parser")
    dl = extract_dl_sections(soup)

    return {
        "overview":     extract_overview(soup),
        "education":    get_section(dl, ["education"], soup, 5),
        "experience":   get_section(dl, ["experience"], soup, 5),
        "requirements": get_section(dl, ["requirement", "qualification", "skill"], soup, 10),
        "tasks":        get_section(dl, ["task", "responsibilit", "duties"], soup, 8),
        "languages":    get_section(dl, ["language"], soup, 3),
        "benefits":     get_section(dl, ["benefit"], soup, 6),
        "work_setting": get_section(dl, ["work setting", "work site"], soup, 5),
        "transportation": get_section(dl, ["transportation"], soup, 3),
        "_debug_dl_keys": list(dl.keys()),  # helps you see what was found if something's missing
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
        self.send_header("Cache-Control", "s-maxage=86400, stale-while-revalidate=604800")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
