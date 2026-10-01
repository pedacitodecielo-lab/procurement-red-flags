"""Render the page backgrounds for the Power BI report (editorial light design).

Static design only: titles, section headings, hairline rules, explanatory text and footer. Every
number on the report comes from Power BI visuals placed on top, so the backgrounds never go out of
date when the data refreshes. Canvas is 1280 x 720 in Power BI; images are drawn at 2x for sharp text.

Design: warm paper background, serif headings (Georgia), one accent colour (oxblood) used only for
the highest-risk items, and hairline rules instead of boxed panels.
"""
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "backgrounds"
S = 2  # render scale
W, H = 1280, 720

PAPER = "#F4F0E8"
INK = "#17181C"
MUTED = "#6E6A62"
RULE = "#D9D2C5"
ACCENT = "#8E2A33"
F = "C:/Windows/Fonts/"


def font(name, size):
    return ImageFont.truetype(F + name, int(size * S))


SERIF_TITLE = font("georgia.ttf", 30)
SERIF_H2 = font("georgia.ttf", 17)
SERIF_H3 = font("georgiab.ttf", 12.5)
SANS = font("segoeui.ttf", 10.5)
SANS_LIGHT = font("segoeuil.ttf", 11.5)
SANS_SUB = font("segoeuil.ttf", 13)
KICKER = font("segoeui.ttf", 9.5)
TINY = font("segoeuil.ttf", 9.5)


def text(d, x, y, s, fnt, fill):
    d.text((x * S, y * S), s, font=fnt, fill=fill)


def hline(d, x0, x1, y):
    d.line([x0 * S, y * S, x1 * S, y * S], fill=RULE, width=S)


def vline(d, x, y0, y1):
    d.line([x * S, y0 * S, x * S, y1 * S], fill=RULE, width=S)


def section(d, x, y, title, subtitle=None):
    text(d, x, y, title, SERIF_H2, INK)
    if subtitle:
        text(d, x, y + 26, subtitle, SANS_LIGHT, MUTED)


def paragraph(d, x, y, s, width_chars, fnt=SANS_LIGHT, fill=INK, gap=17):
    for line in textwrap.wrap(s, width_chars):
        text(d, x, y, line, fnt, fill)
        y += gap
    return y


def new_page(title, question):
    img = Image.new("RGB", (W * S, H * S), PAPER)
    d = ImageDraw.Draw(img)
    text(d, 48, 28, "AUDIT ANALYTICS  ·  INDONESIA  ·  2025 PROVINCIAL TENDERS", KICKER, MUTED)
    text(d, 48, 44, title, SERIF_TITLE, INK)
    text(d, 48, 88, question, SANS_SUB, MUTED)
    hline(d, 48, W - 48, 118)
    text(d, 48, 690, "Red flags are risk indicators for choosing what to review first. They are not evidence of wrongdoing.",
         TINY, MUTED)
    text(d, 48, 704, "Source: SPSE provincial e-procurement portals (spse.inaproc.id), completed provincial government "
         "tenders, 2025. Analysis: Emelio Exaudi.", TINY, MUTED)
    return img, d


def page1():
    img, d = new_page("Procurement Red-Flag Monitor", "Which provincial tenders should auditors review first?")
    labels = ["TENDERS ANALYSED", "HAD ONLY ONE BIDDER", "WON AT 99%+ OF THE ESTIMATE", "CONTRACT VALUE WITH 2+ RED FLAGS"]
    for i, lab in enumerate(labels):
        x = 48 + i * 296
        text(d, x, 196, lab, KICKER, ACCENT if i == 3 else MUTED)
        if i:
            vline(d, x - 22, 136, 212)
    hline(d, 48, W - 48, 232)
    section(d, 48, 250, "Where risk concentrates",
            "Share of tenders with two or more red flags. Longer bar = more tenders worth a closer look.")
    vline(d, 760, 252, 672)
    section(d, 782, 250, "How risky is the portfolio?", "Tenders by number of red flags")
    text(d, 782, 642, "One flag is common and often innocent. Tenders with two or more",
         TINY, MUTED)
    text(d, 782, 656, "flags, or flagged by the anomaly model, are the ones to review first.", TINY, MUTED)
    img.save(OUT / "p1_overview.png")


def page2():
    img, d = new_page("Red flags explained", "Which warning signs appear most often, and what do they mean?")
    section(d, 48, 138, "How often each red flag fires", "Share of analysed tenders that trigger each flag")
    vline(d, 760, 140, 580)
    section(d, 782, 138, "What each flag means")
    y = 178
    for head, body in [
        ("Single bidder", "Only one company submitted a price, so there was no price competition."),
        ("Won at 99%+ of estimate", "The winning bid was within 1% of the owner's estimate (HPS): little price pressure."),
        ("Cheapest bid did not win", "In a lowest-price tender, someone other than the cheapest bidder won. Often the "
                                     "cheapest was disqualified, but it is worth checking why."),
        ("Bids suspiciously close", "Three or more bids within 1% of each other, a pattern linked to cover bidding."),
        ("Repeat winner", "The same company won three or more tenders from the same work unit in the year."),
        ("Possible package split", "Same work unit, same winner and same budget, created within 30 days."),
    ]:
        text(d, 782, y, head, SERIF_H3, INK)
        y = paragraph(d, 782, y + 19, body, 72, fnt=SANS_LIGHT, fill=MUTED, gap=16) + 10
    hline(d, 48, W - 48, 598)
    text(d, 48, 612, "SYSTEMIC FINDING", KICKER, ACCENT)
    paragraph(d, 48, 630, "In most tenders the owner's estimate (HPS) simply copies the budget ceiling (pagu) instead of "
              "coming from a market price survey. Because it appears almost everywhere, it is reported here as a "
              "system-wide issue and is not counted in the tender risk score.", 118, fnt=SANS_LIGHT, fill=INK, gap=16)
    img.save(OUT / "p2_flags.png")


def page3():
    img, d = new_page("Where is the risk concentrated?", "Which provinces and work units stand out?")
    section(d, 48, 138, "Provinces ranked by risk", "Darker cells = higher share of tenders with that warning sign")
    vline(d, 700, 140, 672)
    section(d, 722, 138, "Work units with the most flagged value", "Contract value of tenders with 2+ red flags, top 10")
    hline(d, 722, W - 48, 414)
    section(d, 722, 428, "Repeat winners", "Companies winning 3+ tenders from the same work unit in 2025")
    img.save(OUT / "p3_where.png")


def page4():
    img, d = new_page("Audit shortlist", "Which individual tenders should be reviewed first?")
    hline(d, 48, W - 48, 206)
    section(d, 48, 222, "Priority tenders, ranked by the anomaly model",
            "Unusual on several risk dimensions at once. The last column explains why each one was selected.")
    img.save(OUT / "p4_shortlist.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (page1, page2, page3, page4):
        f()
    print("saved", sorted(p.name for p in OUT.glob("*.png")))
