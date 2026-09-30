"""Parse the cached SPSE pages into two tidy tables.

Inputs (from scrape_spse.py):
    raw/lists/<portal>_<year>.json            tender list rows
    raw/html/<portal>/<id>_<page>.html.gz     announcement, participants, evaluation, winner

Outputs:
    data/tenders.csv   one row per provincial-government tender (all statuses)
    data/bids.csv      one row per participant of a completed tender
    data/parse_issues.csv   pages that were missing or could not be parsed
"""

import gzip
import json
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from scrape_spse import PORTALS, is_provincial

ROOT = Path(__file__).parent
RAW = ROOT / "raw"
OUT = ROOT / "data"

issues = []

# Tender list columns returned by /dt/lelang (by position).
LIST_COLUMNS = {
    0: "tender_id", 1: "tender_name", 2: "agency", 3: "status", 4: "hps_label",
    5: "qualification_method", 6: "procurement_method", 7: "evaluation_method",
    8: "category_years", 10: "contract_value_text",
}

# Evaluation table column codes. The header has two "P" columns: the first is the
# bid price (penawaran), the second is the winner star (pemenang).
EVAL_CODES = {
    "K": "qualification", "B": "verification", "A": "administrative", "T": "technical",
    "H": "price_evaluation", "SK": "qualification_score", "SB": "verification_score",
    "ST": "technical_score", "SH": "price_score", "SA": "final_score",
    "PT": "corrected_bid", "HN": "negotiated_price", "PK": "contract_winner",
}
MARKS = {"fa fa-check": "pass", "fa fa-close": "fail", "fa fa-minus": "not evaluated"}


def money(text):
    """'Rp. 814.109.520,00' -> 814109520.0"""
    if not text:
        return None
    digits = re.sub(r"[^0-9,]", "", text)
    if not digits:
        return None
    return float(digits.replace(",", "."))


def number(text):
    if not text or not re.search(r"\d", text):
        return None
    return float(text.strip().replace(".", "").replace(",", "."))


def cached(portal, tender_id, page):
    return RAW / "html" / portal / f"{tender_id}_{page}.html.gz"


def load(portal, tender_id, page):
    path = cached(portal, tender_id, page)
    if not path.exists():
        issues.append({"portal": portal, "tender_id": tender_id, "page": page, "issue": "missing"})
        return None
    return BeautifulSoup(gzip.decompress(path.read_bytes()), "lxml")


def previous_output():
    """Rows parsed in earlier runs. The HTML cache is not committed, so on a fresh
    machine (GitHub Actions) tenders parsed before are carried over from here."""
    tenders_path, bids_path = OUT / "tenders.csv", OUT / "bids.csv"
    if not tenders_path.exists():
        return {}, {}
    old = pd.read_csv(tenders_path, dtype={"tender_id": str})
    old = old[old["hps"].notna()]
    old_rows = {r["tender_id"]: {k: v for k, v in r.items() if pd.notna(v)} for r in old.to_dict("records")}
    old_bids = {}
    if bids_path.exists():
        for b in pd.read_csv(bids_path, dtype={"tender_id": str}).to_dict("records"):
            old_bids.setdefault(b["tender_id"], []).append({k: v for k, v in b.items() if pd.notna(v)})
    return old_rows, old_bids


def key_values(table):
    """Rows of the form <th>label</th><td>value</td>, at the top level of a table."""
    rows = table.find_all("tr", recursive=False) or table.find("tbody").find_all("tr", recursive=False)
    out = {}
    for tr in rows:
        th = tr.find("th", recursive=False)
        td = tr.find("td", recursive=False)
        if th and td:
            out[th.get_text(" ", strip=True)] = td
    return out


def parse_announcement(soup):
    kv = key_values(soup.find("table"))
    text = {k: v.get_text(" ", strip=True) for k, v in kv.items()}
    rup = kv.get("Rencana Umum Pengadaan")
    rup_cells = [td.get_text(" ", strip=True) for td in rup.find_all("td")] if rup else []
    registered = re.search(r"(\d+)", text.get("Peserta Tender", ""))
    return {
        "created_date": text.get("Tanggal Pembuatan"),
        "work_unit": text.get("Satuan Kerja"),
        "procurement_type": text.get("Jenis Pengadaan"),
        "method_full": text.get("Metode Pengadaan"),
        "fiscal_year_label": text.get("Tahun Anggaran"),
        "contract_type": text.get("Jenis Kontrak"),
        "work_location": text.get("Lokasi Pekerjaan"),
        "business_class": text.get("Kualifikasi Usaha"),
        "funding_source": rup_cells[-1] if len(rup_cells) >= 3 else None,
        "rup_code": rup_cells[-3] if len(rup_cells) >= 3 else None,
        "technical_weight": number(text.get("Bobot Teknis")),
        "price_weight": number(text.get("Bobot Biaya")),
        "reverse_auction": "tidak menggunakan" not in text.get("Reverse Auction?", "tidak menggunakan"),
        "n_registered": int(registered.group(1)) if registered else None,
    }


def parse_winner(soup):
    tables = soup.find_all("table")
    kv = {k: v.get_text(" ", strip=True) for k, v in key_values(tables[0]).items()}
    out = {"pagu": money(kv.get("Pagu")), "hps": money(kv.get("HPS"))}
    if len(tables) > 1:
        rows = tables[1].find_all("tr")
        header = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        if len(rows) > 1:
            cells = [c.get_text(" ", strip=True) for c in rows[1].find_all(["th", "td"])]
            rec = dict(zip(header, cells))
            out.update({
                "winner_name": rec.get("Nama Pemenang"),
                "winner_address": rec.get("Alamat"),
                "winner_bid": money(rec.get("Harga Penawaran")),
                "winner_corrected_bid": money(rec.get("Harga Terkoreksi")),
                "winner_negotiated_price": money(rec.get("Harga Negosiasi")),
            })
    return out


def cell_value(td):
    icon = td.find("i")
    if icon is not None:
        return MARKS.get(" ".join(icon.get("class", [])), "unknown")
    if td.find("img"):
        return "star"
    return td.get_text(" ", strip=True) or None


def parse_bids(participants, evaluation):
    """Participants page: every registered bidder and its bid (if one was submitted).
    Evaluation page: stage-by-stage results for bidders that were evaluated."""
    bids = {}
    rows = participants.find("table").find_all("tr")
    for tr in rows[1:]:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if len(cells) < 3:
            continue
        key = (cells[1], cells[2])
        bids[key] = {
            "bidder_name": cells[1], "tax_id_masked": cells[2],
            "bid": money(cells[3]) if len(cells) > 3 else None,
            "participant_corrected_bid": money(cells[4]) if len(cells) > 4 else None,
            "evaluated": False, "is_winner": False,
        }

    if evaluation is not None and evaluation.find("table") is not None:
        rows = evaluation.find("table").find_all("tr")
        header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        seen_p = False
        names = []
        for h in header:
            if h == "P":
                names.append("winner" if seen_p else "bid_price")
                seen_p = True
            else:
                names.append(EVAL_CODES.get(h, h))
        for tr in rows[1:]:
            tds = tr.find_all(["th", "td"])
            if len(tds) != len(names):
                continue
            rec = dict(zip(names, [cell_value(td) for td in tds]))
            key = (rec.get("Nama Peserta"), rec.get("NPWP"))
            row = bids.setdefault(key, {"bidder_name": key[0], "tax_id_masked": key[1],
                                        "bid": money(rec.get("bid_price")), "evaluated": False,
                                        "is_winner": False})
            row["evaluated"] = True
            row["is_winner"] = rec.get("winner") == "star"
            row["reason"] = rec.get("Alasan")
            for code in ("qualification", "verification", "administrative", "technical", "price_evaluation"):
                if code in rec:
                    row[code] = rec[code]
            for code in ("technical_score", "price_score", "final_score"):
                if code in rec:
                    row[code] = number(rec[code])
            if "corrected_bid" in rec:
                row["corrected_bid"] = money(rec["corrected_bid"])
    return list(bids.values())


def main():
    tenders, bids = [], []
    old_rows, old_bids = previous_output()
    for list_file in sorted((RAW / "lists").glob("*.json")):
        portal, year = list_file.stem.rsplit("_", 1)
        for raw_row in json.loads(list_file.read_text(encoding="utf-8")):
            row = {name: raw_row[i] for i, name in LIST_COLUMNS.items()}
            if not is_provincial(row["agency"]):
                continue
            row.update({"portal": portal, "province": PORTALS[portal], "year": int(year),
                        "contract_value": money(row.pop("contract_value_text"))})
            tid = row["tender_id"]
            page_names = ("announcement", "participants", "evaluation", "winner")
            if row["status"] == "Tender Sudah Selesai" and tid in old_rows \
                    and not any(cached(portal, tid, p).exists() for p in page_names):
                tenders.append({**old_rows[tid], **row})
                bids.extend(old_bids.get(tid, []))
                continue
            if row["status"] == "Tender Sudah Selesai":
                pages = {p: load(portal, tid, p) for p in page_names}
                try:
                    if pages["announcement"] is not None:
                        row.update(parse_announcement(pages["announcement"]))
                    if pages["winner"] is not None:
                        row.update(parse_winner(pages["winner"]))
                    if pages["participants"] is not None:
                        for b in parse_bids(pages["participants"], pages["evaluation"]):
                            bids.append({"portal": portal, "tender_id": tid, **b})
                except Exception as exc:  # keep going, but record the failure
                    issues.append({"portal": portal, "tender_id": tid, "page": "parse", "issue": repr(exc)[:200]})
            tenders.append(row)

    OUT.mkdir(exist_ok=True)
    pd.DataFrame(tenders).to_csv(OUT / "tenders.csv", index=False)
    pd.DataFrame(bids).to_csv(OUT / "bids.csv", index=False)
    pd.DataFrame(issues, columns=["portal", "tender_id", "page", "issue"]).to_csv(OUT / "parse_issues.csv", index=False)
    print(f"{len(tenders)} tenders, {len(bids)} bid rows, {len(issues)} issues")


if __name__ == "__main__":
    main()
