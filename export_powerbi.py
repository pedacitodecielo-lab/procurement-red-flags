"""Shape the model outputs into tidy tables for the Power BI report.

Inputs:  model/tender_risk.csv, model/anomalies.csv
Outputs: model/pbi_tenders.csv   one row per completed provincial tender
         model/pbi_flags.csv     one row per tender x red flag (for "which flags fire most")
         model/pbi_priority.csv  the audit shortlist: model anomalies with plain-language reasons

Decision carried over from the study notes: "HPS equals pagu" fires on most tenders, so it cannot
separate risky from ordinary tenders. It is shown as a systemic finding and is NOT counted in the
tender risk score.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
MODEL = ROOT / "model"

FLAGS = {
    "flag_single_bid": ("Single bidder", "Only one company submitted a price, so there was no price competition."),
    "flag_near_hps": ("Won at 99%+ of estimate", "The winning bid was within 1% of the owner's estimate (HPS): little price pressure."),
    "flag_lowest_not_winner": ("Cheapest bid did not win", "A lowest-price tender was won by someone other than the cheapest bidder."),
    "flag_tight_bid_spread": ("Bids suspiciously close", "3+ bids within 1% of each other, a pattern linked to cover bidding."),
    "flag_repeat_winner": ("Repeat winner", "The same company won 3+ tenders from the same work unit in the year."),
    "flag_possible_split": ("Possible package split", "Same work unit, same winner, same budget, created within 30 days."),
    "flag_hps_equals_pagu": ("Estimate copied from budget", "The owner's estimate equals the budget ceiling (systemic, not scored)."),
}
SCORED = [k for k in FLAGS if k != "flag_hps_equals_pagu"]


def to_bool(s):
    return s.astype(str).str.lower().isin(["true", "1"])


def main():
    t = pd.read_csv(MODEL / "tender_risk.csv", low_memory=False)
    t = t[to_bool(t["completed"])].copy()
    for k in FLAGS:
        t[k] = to_bool(t[k])
    t["has_details"] = t["hps"].notna() & t["n_bids"].notna()
    t["risk_score"] = t[SCORED].sum(axis=1)
    t["risk_tier"] = pd.cut(t["risk_score"], [-1, 0, 1, 2, 99],
                            labels=["0 flags: clear", "1 flag: watch", "2 flags: review", "3+ flags: priority"]).astype(str)
    t.loc[~t["has_details"], "risk_tier"] = "Not yet scraped"
    t["family"] = t["procurement_method"].map({"Seleksi": "Consultant selection"}).fillna("Works & goods tender")
    t["discount_to_hps"] = 1 - t["winner_to_hps"]
    keep = ["tender_id", "portal", "province", "work_unit", "tender_name", "family", "category", "procurement_method",
            "evaluation_method", "created_on", "pagu", "hps", "contract_value", "winner_name", "n_registered", "n_bids",
            "winner_to_hps", "discount_to_hps", "hps_to_pagu", "has_details", "risk_score", "risk_tier"] + list(FLAGS)
    t[keep].to_csv(MODEL / "pbi_tenders.csv", index=False)

    long = t[t["has_details"]].melt(id_vars=["tender_id", "province"], value_vars=list(FLAGS),
                                    var_name="flag_key", value_name="flagged")
    long["flag"] = long["flag_key"].map(lambda k: FLAGS[k][0])
    long["meaning"] = long["flag_key"].map(lambda k: FLAGS[k][1])
    long["scored"] = long["flag_key"].isin(SCORED)
    long.to_csv(MODEL / "pbi_flags.csv", index=False)

    a = pd.read_csv(MODEL / "anomalies.csv")
    a = a[to_bool(a["is_anomaly"])].merge(t[["tender_id", "risk_score", "hps"]], on="tender_id", how="left")
    a = a.sort_values(["anomaly_score"], ascending=False)
    a.insert(0, "priority_rank", range(1, len(a) + 1))
    a.to_csv(MODEL / "pbi_priority.csv", index=False)

    print(f"tenders: {len(t)} completed, {int(t['has_details'].sum())} with details")
    print(t.loc[t["has_details"], "risk_tier"].value_counts().to_string())
    print(f"priority list: {len(a)} anomalies")


if __name__ == "__main__":
    main()
