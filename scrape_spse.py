"""Collect public tender data from Indonesia's provincial e-procurement portals.

Source: SPSE (Sistem Pengadaan Secara Elektronik), reached through the national
gateway https://spse.inaproc.id/<portal>. Its robots.txt allows these portal
paths and asks for a 1-second crawl delay; we wait DELAY seconds between
requests, which is gentler than required.

For each provincial portal and year:
1. The tender list comes from the JSON endpoint behind the "Cari Paket" page
   (POST /<portal>/dt/lelang?tahun=YYYY with the page's authenticity token).
2. For every completed tender, four public pages are saved:
   announcement, participants, evaluation results and winner.

Every response is cached (gzipped) under raw/, so a rerun only fetches what is
missing. The run stops a portal on HTTP 429 or 503 and logs every request to
data/scrape_log.csv. Parsing is done separately in parse_spse.py.

Usage:
    python scrape_spse.py --year 2025                  # all provinces
    python scrape_spse.py --year 2025 --portal jabarprov --limit 3
    python scrape_spse.py --year 2025 --lists-only     # tender lists only
"""

import argparse
import csv
import gzip
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://spse.inaproc.id"
DELAY = 1.5  # seconds between requests; robots.txt asks for at least 1
ROOT = Path(__file__).parent
RAW = ROOT / "raw"
LOG = ROOT / "data" / "scrape_log.csv"
# Standard crawler format ("Mozilla/5.0 (compatible; <bot>; +<url>)", as Googlebot
# uses): the portal refuses detail pages to agents without the Mozilla prefix, and
# this still names the bot so the site can identify or block it.
USER_AGENT = "Mozilla/5.0 (compatible; procurement-red-flags/1.0; +https://github.com/pedacitodecielo-lab)"

# Provincial government portals on the SPSE gateway (all listed in robots.txt).
PORTALS = {
    "acehprov": "Aceh", "sumutprov": "Sumatera Utara", "sumbarprov": "Sumatera Barat",
    "riau": "Riau", "jambiprov": "Jambi", "sumselprov": "Sumatera Selatan",
    "bengkuluprov": "Bengkulu", "lampungprov": "Lampung", "babelprov": "Kepulauan Bangka Belitung",
    "kepriprov": "Kepulauan Riau", "jakarta": "DKI Jakarta", "jabarprov": "Jawa Barat",
    "jatengprov": "Jawa Tengah", "jogjaprov": "DI Yogyakarta", "jatimprov": "Jawa Timur",
    "bantenprov": "Banten", "baliprov": "Bali", "ntbprov": "Nusa Tenggara Barat",
    "nttprov": "Nusa Tenggara Timur", "kalbarprov": "Kalimantan Barat", "kalteng": "Kalimantan Tengah",
    "kalselprov": "Kalimantan Selatan", "kaltimprov": "Kalimantan Timur", "kaltaraprov": "Kalimantan Utara",
    "sulutprov": "Sulawesi Utara", "sultengprov": "Sulawesi Tengah", "sulselprov": "Sulawesi Selatan",
    "sultraprov": "Sulawesi Tenggara", "gorontaloprov": "Gorontalo", "sulbarprov": "Sulawesi Barat",
    "malukuprov": "Maluku", "malutprov": "Maluku Utara", "papua": "Papua", "papuabaratprov": "Papua Barat",
}

# Detail pages saved for each completed tender: name -> path template.
PAGES = {
    "announcement": "lelang/{id}/pengumumanlelang",
    "participants": "lelang/{id}/peserta",
    "evaluation": "evaluasi/{id}/hasil",
    "winner": "evaluasi/{id}/pemenang",
}
COMPLETED = "Tender Sudah Selesai"


def is_provincial(agency):
    """Portals also host a few tenders for regencies, ministries and state firms.
    We keep the provincial government's own tenders ("Provinsi ...", or "Aceh")."""
    return agency.startswith("Provinsi ") or agency == "Aceh"


class StopPortal(Exception):
    """Raised when the server signals overload; we stop this portal."""


class Portal:
    def __init__(self, code):
        self.code = code
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.token = None
        self.last_request = 0.0

    def _wait(self):
        pause = DELAY - (time.monotonic() - self.last_request)
        if pause > 0:
            time.sleep(pause)
        self.last_request = time.monotonic()

    def request(self, method, path, referer=None, **kwargs):
        self._wait()
        url = f"{BASE}/{self.code}/{path}"
        headers = {"Referer": referer} if referer else {}
        try:
            resp = self.session.request(method, url, headers=headers, timeout=60, **kwargs)
        except requests.RequestException as exc:
            log_row(self.code, path, "error", str(exc)[:200])
            return None
        log_row(self.code, path, resp.status_code, len(resp.content))
        if resp.status_code in (429, 503):
            raise StopPortal(f"{self.code}: HTTP {resp.status_code}")
        return resp

    def open(self):
        """Load the list page to get the session cookie and authenticity token."""
        resp = self.request("GET", "lelang")
        if resp is None or resp.status_code != 200:
            return False
        match = re.search(r"authenticityToken = '([0-9a-f]+)'", resp.text)
        self.token = match.group(1) if match else None
        return self.token is not None

    def tender_list(self, year):
        resp = self.request(
            "POST", f"dt/lelang?tahun={year}", referer=f"{BASE}/{self.code}/lelang",
            data={"draw": 1, "start": 0, "length": 100000, "authenticityToken": self.token},
        )
        if resp is None or resp.status_code != 200:
            return None
        return resp.json()["data"]

    def page(self, tender_id, name):
        path = PAGES[name].format(id=tender_id)
        # Detail pages are only served when reached from the tender's own pages.
        referer = f"{BASE}/{self.code}/lelang/{tender_id}/pengumumanlelang"
        if name == "announcement":
            referer = f"{BASE}/{self.code}/lelang"
        resp = self.request("GET", path, referer=referer)
        if resp is not None and resp.status_code == 403:
            # The session may have expired: reopen once and retry.
            if self.open():
                resp = self.request("GET", path, referer=referer)
        return resp


def log_row(portal, path, status, detail):
    new = not LOG.exists()
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(["time_utc", "portal", "path", "status", "detail"])
        writer.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), portal, path, status, detail])


def cache_path(portal, tender_id, name):
    return RAW / "html" / portal / f"{tender_id}_{name}.html.gz"


def known_tenders():
    """Tender IDs already parsed with full details (committed in data/tenders.csv).
    On a fresh machine such as a GitHub Actions runner the HTML cache is empty,
    so this is what keeps the weekly refresh incremental."""
    path = ROOT / "data" / "tenders.csv"
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as f:
        return {row["tender_id"] for row in csv.DictReader(f) if row.get("hps")}


def scrape_portal(code, year, limit=None, lists_only=False, skip=frozenset()):
    portal = Portal(code)
    list_file = RAW / "lists" / f"{code}_{year}.json"
    if not portal.open():
        print(f"{code}: could not open portal, skipped")
        return
    rows = portal.tender_list(year)
    if rows is None:
        print(f"{code}: tender list unavailable, skipped")
        return
    list_file.parent.mkdir(parents=True, exist_ok=True)
    list_file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    completed = [r[0] for r in rows if r[3] == COMPLETED and is_provincial(r[2])]
    new = [t for t in completed if t not in skip]
    print(f"{code}: {len(rows)} tenders in {year}, {len(completed)} completed provincial tenders, {len(new)} not yet parsed")
    if lists_only:
        return

    todo = new[:limit] if limit else new
    fetched = 0
    for tender_id in todo:
        for name in PAGES:
            target = cache_path(code, tender_id, name)
            if target.exists():
                continue
            resp = portal.page(tender_id, name)
            if resp is None or resp.status_code != 200:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(gzip.compress(resp.content))
            fetched += 1
    print(f"{code}: {fetched} pages fetched")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, nargs="+", required=True)
    parser.add_argument("--portal", choices=sorted(PORTALS), help="one portal only")
    parser.add_argument("--limit", type=int, help="max completed tenders per portal (for testing)")
    parser.add_argument("--lists-only", action="store_true")
    args = parser.parse_args()

    skip = known_tenders()
    for year in args.year:
        for code in [args.portal] if args.portal else PORTALS:
            try:
                scrape_portal(code, year, args.limit, args.lists_only, skip)
            except StopPortal as exc:
                print(f"stopped: {exc}")


if __name__ == "__main__":
    main()
