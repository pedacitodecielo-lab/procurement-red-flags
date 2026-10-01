"""Render the page backgrounds for the Power BI report (premium dark theme).

Static design only: panels, titles, guidance text and footer. Every number on the report comes from
Power BI visuals placed on top, so the backgrounds never go out of date when the data refreshes.
Canvas is 1280 x 720 in Power BI; images are drawn at 2x for sharp text.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "backgrounds"
S = 2  # render scale
W, H = 1280, 720

BG = "#0B1426"        # page
PANEL = "#111E36"     # cards
BORDER = "#22314F"
GOLD = "#D4AF37"
IVORY = "#F4F1EA"
MUTED = "#8C97AD"
F = "C:/Windows/Fonts/"


def font(name, size):
    return ImageFont.truetype(F + name, int(size * S))


TITLE = font("seguisb.ttf", 22)
SUB = font("segoeuil.ttf", 12.5)
H2 = font("seguisb.ttf", 12.5)
SMALL = font("segoeui.ttf", 9.5)
TINY = font("segoeui.ttf", 8.5)
LABEL = font("segoeui.ttf", 10)


def new_page(title, question):
    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([32 * S, 22 * S, 36 * S, 58 * S], fill=GOLD)                       # accent bar
    d.text((46 * S, 18 * S), title, font=TITLE, fill=IVORY)
    d.text((46 * S, 46 * S), question, font=SUB, fill=MUTED)
    d.line([32 * S, 72 * S, (W - 32) * S, 72 * S], fill=BORDER, width=S)
    d.text((32 * S, 690 * S), "Red flags are risk indicators to help auditors choose what to review first. "
           "They are not evidence of wrongdoing.", font=TINY, fill=MUTED)
    d.text((32 * S, 704 * S), "Source: SPSE provincial e-procurement portals (spse.inaproc.id), completed provincial "
           "government tenders, 2025. Analysis: Emelio Exaudi.", font=TINY, fill=MUTED)
    return img, d


def panel(d, x, y, w, h, title=None, subtitle=None, accent=False):
    d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=10 * S, fill=PANEL,
                        outline=GOLD if accent else BORDER, width=S)
    if title:
        d.text(((x + 16) * S, (y + 12) * S), title, font=H2, fill=IVORY)
    if subtitle:
        d.text(((x + 16) * S, (y + 31) * S), subtitle, font=SMALL, fill=MUTED)


def text_block(d, x, y, lines, width_chars=62, gap=15, fnt=SMALL, fill=IVORY):
    import textwrap
    for ln in lines:
        head, _, body = ln.partition("|")
        if body:
            d.text((x * S, y * S), head, font=H2 if fnt is SMALL else fnt, fill=GOLD)
            y += gap
            ln = body
        for part in textwrap.wrap(ln, width_chars):
            d.text((x * S, y * S), part, font=fnt, fill=fill)
            y += gap - 2
        y += 6
    return y


def page1():
    img, d = new_page("Procurement Red-Flag Monitor", "Where should provincial auditors look first?")
    labels = ["Completed tenders analysed", "Only one bidder", "Won at 99%+ of the estimate", "Contract value with 2+ flags"]
    for i, lab in enumerate(labels):
        x = 32 + i * 306
        panel(d, x, 86, 298, 92, accent=(i == 3))
        d.text(((x + 16) * S, (86 + 12) * S), lab.upper(), font=LABEL, fill=MUTED)
    panel(d, 32, 190, 800, 486, "Which provinces carry the most risk?",
          "Share of completed tenders with 2 or more red flags. Longer bar = more tenders worth a closer look.")
    panel(d, 844, 190, 404, 290, "How risky is the portfolio?", "Completed tenders by number of red flags")
    panel(d, 844, 492, 404, 184)
    text_block(d, 860, 504, [
        "How to read this report|Each tender is checked against 6 red flags. One flag is common and often innocent; "
        "tenders with 2+ flags, and those the model marks as unusual, are the best candidates for a human review.",
    ], width_chars=66)
    img.save(OUT / "p1_overview.png")


def page2():
    img, d = new_page("Red flags explained", "Which warning signs appear most often, and what do they mean?")
    panel(d, 32, 86, 740, 490, "How often each red flag fires", "Share of completed tenders that trigger each flag")
    panel(d, 784, 86, 464, 490, "What each flag means")
    text_block(d, 800, 122, [
        "Single bidder|Only one company submitted a price, so there was no price competition.",
        "Won at 99%+ of estimate|The winning bid was within 1% of the owner's estimate (HPS): little price pressure.",
        "Cheapest bid did not win|A lowest-price tender went to someone other than the cheapest bidder. Often the cheapest "
        "was disqualified, but it is worth checking why.",
        "Bids suspiciously close|3 or more bids within 1% of each other, a pattern linked to cover bidding.",
        "Repeat winner|The same company won 3+ tenders from the same work unit in the year.",
        "Possible package split|Same work unit, same winner and same budget, created within 30 days.",
    ], width_chars=70, gap=14)
    panel(d, 32, 588, 1216, 88, accent=True)
    d.text((48 * S, 598 * S), "SYSTEMIC FINDING", font=LABEL, fill=GOLD)
    text_block(d, 48, 616, ["In most tenders the owner's estimate (HPS) simply copies the budget ceiling (pagu) instead of "
                            "coming from a market price survey. Because it appears almost everywhere, it is reported here as a "
                            "system-wide issue and is not counted in the tender risk score."], width_chars=120)
    img.save(OUT / "p2_flags.png")


def page3():
    img, d = new_page("Where is the risk concentrated?", "Which provinces and work units stand out?")
    panel(d, 32, 86, 620, 590, "Provinces ranked by risk",
          "Darker cells = higher share of tenders with that warning sign")
    panel(d, 664, 86, 584, 290, "Work units with the most flagged contract value",
          "Contract value of tenders with 2+ red flags, top 10 work units")
    panel(d, 664, 388, 584, 288, "Repeat winners",
          "Companies winning 3+ tenders from the same work unit in 2025")
    img.save(OUT / "p3_where.png")


def page4():
    img, d = new_page("Audit shortlist", "Which individual tenders should be reviewed first?")
    panel(d, 32, 86, 1216, 60)
    panel(d, 32, 158, 1216, 518, "Priority tenders, ranked by the anomaly model",
          "Unusual on several risk dimensions at once. The reason column explains why each one was selected.")
    img.save(OUT / "p4_shortlist.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (page1, page2, page3, page4):
        f()
    print("saved", sorted(p.name for p in OUT.glob("*.png")))
