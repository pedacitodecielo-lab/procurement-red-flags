"""Draw images/00_pipeline_stages.png: one panel per pipeline stage, filled from the real outputs.

Every number in the figure is read from files the pipeline writes (data/*.csv, model/*.csv),
so the figure can be regenerated after each refresh:  python docs/make_pipeline_figure.py
"""
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DATA, MODEL = ROOT / "data", ROOT / "model"
F = "C:/Windows/Fonts/"
S = 2  # render scale

BG, PANEL, BORDER = "#0B1426", "#0F1B31", "#22314F"
GOLD, IVORY, MUTED, GREEN, AMBER = "#D4AF37", "#F4F1EA", "#8C97AD", "#7FB77E", "#E8A33D"


def font(name, size):
    return ImageFont.truetype(F + name, int(size * S))


TITLE, H2, SUB = font("seguisb.ttf", 26), font("seguisb.ttf", 15), font("segoeui.ttf", 11)
MONO, MONO_B = font("consola.ttf", 11.5), font("consolab.ttf", 11.5)


def stage_texts():
    log = pd.read_csv(DATA / "scrape_log.csv", dtype={"status": str})
    status = log["status"].value_counts()
    tenders = pd.read_csv(DATA / "tenders.csv", low_memory=False)
    bids = pd.read_csv(DATA / "bids.csv", low_memory=False)
    issues = pd.read_csv(DATA / "parse_issues.csv")
    pbi = pd.read_csv(MODEL / "pbi_tenders.csv")
    done = pbi[pbi["has_details"]]
    dq = pd.read_csv(MODEL / "dq_checks.csv")
    val = pd.read_csv(MODEL / "anomaly_validation.csv")
    prio = pd.read_csv(MODEL / "pbi_priority.csv")
    flag_rows = len(pd.read_csv(MODEL / "pbi_flags.csv", usecols=["tender_id"]))
    completed = int(tenders["status"].eq("Tender Sudah Selesai").sum())

    tail = log.tail(4)
    scrape = [
        ("robots.txt  User-agent: *  Allow: /   Crawl-delay: 1", MUTED),
        ("delay       1.5 s between requests, cache every page (gzip)", MUTED),
        ("user-agent  procurement-red-flags/1.0 (+github link)", MUTED),
        ("", None),
        ("time (UTC)  portal          page                       status", GOLD),
    ] + [(f"{r.time_utc[11:19]}    {r.portal:<15.15} {r.path[-26:]:<26} {r.status}", IVORY) for r in tail.itertuples()] + [
        ("", None),
        (f"requests {len(log):,}   HTTP 200: {status.get('200', 0):,}   "
         f"403: {status.get('403', 0)}   500: {status.get('500', 0)}   errors: {status.get('error', 0)}", GREEN),
    ]

    parse = [
        ("$ python parse_spse.py", GOLD),
        (f"{len(tenders):,} tenders, {len(bids):,} bid rows, {len(issues)} issues", IVORY),
        ("", None),
        (f"completed provincial tenders   {completed:,}", IVORY),
        (f"with full bid details           {len(done):,}  ({len(done) / completed:.1%})", GREEN),
        (f"winner page empty on SPSE       {int((issues['page'] == 'winner').sum())}  (logged, excluded)", AMBER),
        ("", None),
        ("parsed per tender: pagu, HPS, winner, winning bid,", MUTED),
        ("work unit, method; per bidder: bid, pass/fail per", MUTED),
        ("evaluation stage, disqualification reason, score", MUTED),
    ]

    flag_names = {
        "flag_single_bid": "single bidder", "flag_lowest_not_winner": "cheapest bid did not win",
        "flag_near_hps": "won at 99%+ of estimate", "flag_repeat_winner": "repeat winner (3+ wins)",
        "flag_possible_split": "possible package split", "flag_tight_bid_spread": "bids within 1% (3+ bids)",
        "flag_hps_equals_pagu": "HPS copies pagu (not scored)",
    }
    flags = [("$ python build_model.py   (DuckDB SQL)", GOLD), (f"{'flag':<30}{'tenders':>8}{'share':>8}", MUTED)]
    for k, label in flag_names.items():
        n = int(done[k].sum())
        flags.append((f"{label:<30}{n:>8,}{n / len(done):>8.1%}", AMBER if "not scored" in label else IVORY))
    multi = int((done["risk_score"] >= 2).sum())
    flags += [("", None), (f"2+ scored flags: {multi:,} tenders ({multi / len(done):.1%})", GREEN)]

    checks = [("$ python dq_checks.py", GOLD)]
    for r in dq.itertuples():
        colour = GREEN if r.status == "ok" else (AMBER if r.status == "review" else "#E0564B")
        label = r.check.split(" (")[0]
        checks.append((f"{r.status.upper():<7}{r.problem_rows:>6}  {label[:78]}", colour))
    checks += [("", None), ("a critical FAIL stops the weekly refresh before commit", MUTED)]

    anomaly = [("$ python anomaly_model.py   (Isolation Forest)", GOLD),
               (f"{'group':<26}{'tenders':>8}{'flagged':>8}{'stable':>8}", MUTED)]
    for r in val.itertuples():
        anomaly.append((f"{r.family:<26}{r.tenders:>8,}{r.anomalies:>8}{r.seed_stability_jaccard:>8.2f}", IVORY))
    anomaly += [("", None), ("share with 2+ red flags:", MUTED)]
    for r in val.itertuples():
        anomaly.append((f"  {r.family:<24} anomalies {r.anomaly_with_2plus_flags:.0%}  vs all {r.all_with_2plus_flags:.0%}", GREEN))
    top = prio.iloc[0]
    anomaly += [("", None), ("example reason (rank 1):", MUTED)]
    reason = str(top["reason"]).split("; ")
    anomaly += [("  " + part[:80], IVORY) for part in reason[:3]]

    export = [
        ("$ python export_powerbi.py", GOLD),
        (f"model/pbi_tenders.csv    {len(pbi):,} rows (one per tender)", IVORY),
        (f"model/pbi_flags.csv      {flag_rows:,} rows (tender x flag)", IVORY),
        (f"model/pbi_priority.csv   {len(prio)} rows (audit shortlist)", IVORY),
        ("", None),
        ("Power BI: Python data source, 4 tables, 22 DAX measures", MUTED),
        ("pages: Overview / Red flags / Where / Audit shortlist", MUTED),
        ("", None),
        ("GitHub Actions: weekly re-scrape -> model -> checks -> commit", GREEN),
    ]

    return [
        ("1  Scrape", "scrape_spse.py: 34 provincial SPSE portals, 2025", scrape),
        ("2  Parse", "parse_spse.py: HTML pages to two tidy tables", parse),
        ("3  Red flags", "build_model.py: rule-based flags in SQL", flags),
        ("4  Anomaly model", "anomaly_model.py: risk-directed, explained per tender", anomaly),
        ("5  Data-quality checks", "dq_checks.py: stop bad data before it is published", checks),
        ("6  Power BI", "export_powerbi.py + procurement_red_flags.pbix", export),
    ]


def main():
    W, H = 1600, 1180
    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([40 * S, 30 * S, 45 * S, 74 * S], fill=GOLD)
    d.text((58 * S, 26 * S), "How the pipeline runs: real output from each stage", font=TITLE, fill=IVORY)
    d.text((58 * S, 60 * S), "Procurement Red-Flag Monitor, data as of the latest refresh", font=SUB, fill=MUTED)

    pw, ph, gap = 750, 335, 20
    for i, (title, sub, lines) in enumerate(stage_texts()):
        x = 40 + (i % 2) * (pw + gap)
        y = 100 + (i // 2) * (ph + gap)
        d.rounded_rectangle([x * S, y * S, (x + pw) * S, (y + ph) * S], radius=10 * S, fill=PANEL, outline=BORDER, width=S)
        d.text(((x + 18) * S, (y + 12) * S), title, font=H2, fill=GOLD)
        d.text(((x + 18) * S, (y + 36) * S), sub, font=SUB, fill=MUTED)
        ty = y + 64
        for text, colour in lines:
            if colour:
                d.text(((x + 18) * S, ty * S), text, font=MONO_B if colour == GOLD else MONO, fill=colour)
            ty += 17
    out = ROOT / "images" / "00_pipeline_stages.png"
    img.resize((W, H), Image.LANCZOS).save(out, optimize=True)
    print("saved", out)


if __name__ == "__main__":
    main()
