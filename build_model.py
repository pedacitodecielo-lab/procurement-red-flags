"""Build the analysis tables and the rule-based red flags with DuckDB SQL.

Inputs:  data/tenders.csv, data/bids.csv (from parse_spse.py)
Outputs: model/*.csv and procurement.duckdb

Red flags are risk indicators for audit prioritisation, not evidence of
wrongdoing. Each one is adapted from published screens: the Open Contracting
Partnership's "Red Flags for Integrity" and the World Bank's procurement fraud
indicators. Thresholds are set in THRESHOLDS so they are easy to review.
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).parent
DATA = ROOT / "data"
MODEL = ROOT / "model"

THRESHOLDS = {
    "near_hps": 0.99,         # winning bid at or above 99% of the owner's estimate (HPS)
    "hps_equals_pagu": 0.999, # HPS at or above 99.9% of the budget ceiling (pagu)
    "tight_spread_cv": 0.01,  # coefficient of variation of bids below 1% (3+ bids)
    "repeat_wins": 3,         # same vendor wins 3+ tenders from the same work unit
    "split_days": 30,         # packages from one work unit to one vendor within 30 days
}

# Month names on SPSE are Indonesian; DuckDB's strptime expects English.
MONTHS = {"Januari": "January", "Februari": "February", "Maret": "March", "April": "April",
          "Mei": "May", "Juni": "June", "Juli": "July", "Agustus": "August",
          "September": "September", "Oktober": "October", "November": "November",
          "Desember": "December"}


def build(con):
    t = THRESHOLDS
    month_case = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in MONTHS.items())
    con.execute(f"""
    CREATE OR REPLACE TABLE tenders AS
    WITH raw AS (SELECT * FROM read_csv_auto('{DATA.as_posix()}/tenders.csv', header = true, all_varchar = true))
    SELECT
        portal, province, CAST(year AS INTEGER) AS year, tender_id, tender_name, agency, work_unit, status,
        procurement_method, evaluation_method, qualification_method,
        split_part(category_years, ' - ', 1) AS category, procurement_type, funding_source, business_class,
        TRY_CAST(pagu AS DOUBLE) AS pagu, TRY_CAST(hps AS DOUBLE) AS hps,
        TRY_CAST(contract_value AS DOUBLE) AS contract_value,
        TRY_CAST(n_registered AS INTEGER) AS n_registered,
        winner_name, winner_address,
        TRY_CAST(winner_bid AS DOUBLE) AS winner_bid,
        TRY_CAST(winner_negotiated_price AS DOUBLE) AS winner_negotiated_price,
        TRY_CAST(strptime(
            split_part(created_date, ' ', 1) || ' ' ||
            CASE split_part(created_date, ' ', 2) {month_case} END || ' ' ||
            split_part(created_date, ' ', 3), '%d %B %Y') AS DATE) AS created_on,
        status = 'Tender Sudah Selesai' AS completed,
        status LIKE '%Batal' OR status LIKE '%Gagal' AS failed_or_cancelled,
        evaluation_method LIKE 'Harga Terendah%' OR evaluation_method = 'Biaya Terendah' AS price_based
    FROM raw;

    CREATE OR REPLACE TABLE bids AS
    SELECT portal, tender_id, bidder_name, tax_id_masked,
           TRY_CAST(bid AS DOUBLE) AS bid,
           CAST(evaluated AS BOOLEAN) AS evaluated, CAST(is_winner AS BOOLEAN) AS is_winner,
           reason, administrative, technical, price_evaluation,
           TRY_CAST(final_score AS DOUBLE) AS final_score
    FROM read_csv_auto('{DATA.as_posix()}/bids.csv', header = true, all_varchar = true);

    -- Bid statistics per tender (only bidders that actually submitted a price).
    CREATE OR REPLACE TABLE tender_bid_stats AS
    SELECT tender_id,
           count(*) AS n_participants,
           count(bid) AS n_bids,
           min(bid) AS lowest_bid,
           arg_min(bidder_name, bid) AS lowest_bidder,
           stddev_samp(bid) / avg(bid) AS bid_cv,
           count(*) FILTER (WHERE administrative = 'fail' OR technical = 'fail'
                            OR price_evaluation = 'fail') AS n_disqualified
    FROM bids
    GROUP BY tender_id;

    CREATE OR REPLACE TABLE tender_flags AS
    SELECT t.*,
           s.n_participants, s.n_bids, s.lowest_bid, s.lowest_bidder, s.bid_cv, s.n_disqualified,
           t.winner_bid / NULLIF(t.hps, 0) AS winner_to_hps,
           t.hps / NULLIF(t.pagu, 0) AS hps_to_pagu,
           -- 1. Only one bid submitted: no price competition.
           t.completed AND s.n_bids = 1 AS flag_single_bid,
           -- 2. Winning bid within 1% of the owner's estimate: little price competition.
           t.completed AND t.winner_bid >= {t['near_hps']} * t.hps AS flag_near_hps,
           -- 3. Lowest-price tender won by someone other than the lowest bidder.
           t.completed AND t.price_based AND s.n_bids >= 2
               AND t.winner_bid > s.lowest_bid AS flag_lowest_not_winner,
           -- 4. Bids suspiciously close together (possible cover bidding).
           t.completed AND s.n_bids >= 3 AND s.bid_cv < {t['tight_spread_cv']} AS flag_tight_bid_spread,
           -- 5. Owner's estimate copied from the budget ceiling: weak cost estimation.
           t.completed AND t.hps >= {t['hps_equals_pagu']} * t.pagu AS flag_hps_equals_pagu
    FROM tenders t
    LEFT JOIN tender_bid_stats s USING (tender_id);

    -- 6. Repeat winner: vendor wins 3+ tenders from the same work unit in the year.
    CREATE OR REPLACE TABLE repeat_winners AS
    SELECT portal, province, work_unit, winner_name, count(*) AS wins, sum(contract_value) AS contract_value
    FROM tender_flags
    WHERE completed AND winner_name IS NOT NULL
    GROUP BY ALL
    HAVING count(*) >= {t['repeat_wins']};

    -- 7. Possible package splitting: same work unit and vendor, same budget ceiling,
    --    tenders created within 30 days of each other.
    CREATE OR REPLACE TABLE split_pairs AS
    SELECT a.tender_id AS tender_a, b.tender_id AS tender_b, a.portal, a.work_unit, a.winner_name, a.pagu
    FROM tender_flags a JOIN tender_flags b
      ON a.portal = b.portal AND a.work_unit = b.work_unit AND a.winner_name = b.winner_name
     AND a.pagu = b.pagu AND a.tender_id < b.tender_id
     AND abs(date_diff('day', a.created_on, b.created_on)) <= {t['split_days']}
    WHERE a.completed AND b.completed;

    CREATE OR REPLACE TABLE tender_risk AS
    SELECT f.*,
           EXISTS (SELECT 1 FROM repeat_winners r WHERE r.portal = f.portal AND r.work_unit = f.work_unit
                   AND r.winner_name = f.winner_name) AS flag_repeat_winner,
           EXISTS (SELECT 1 FROM split_pairs p WHERE f.tender_id IN (p.tender_a, p.tender_b)) AS flag_possible_split
    FROM tender_flags f;

    CREATE OR REPLACE TABLE tender_risk AS
    SELECT *,
           coalesce(flag_single_bid::INT, 0) + coalesce(flag_near_hps::INT, 0)
         + coalesce(flag_lowest_not_winner::INT, 0) + coalesce(flag_tight_bid_spread::INT, 0)
         + flag_repeat_winner::INT + flag_possible_split::INT AS n_flags
         -- flag_hps_equals_pagu is left out: it fires on most tenders, so it is
         -- reported as a system-wide finding instead of a per-tender risk.
    FROM tender_risk;

    CREATE OR REPLACE TABLE province_summary AS
    SELECT province,
           count(*) AS tenders,
           count(*) FILTER (WHERE completed) AS completed,
           avg(failed_or_cancelled::INT) AS failed_or_cancelled_rate,
           sum(contract_value) AS contract_value,
           avg(n_bids) FILTER (WHERE completed) AS avg_bids,
           avg(flag_single_bid::INT) FILTER (WHERE completed) AS single_bid_rate,
           avg(flag_near_hps::INT) FILTER (WHERE completed) AS near_hps_rate,
           avg((n_flags >= 2)::INT) FILTER (WHERE completed) AS multi_flag_rate,
           sum(contract_value) FILTER (WHERE n_flags >= 2) / NULLIF(sum(contract_value), 0) AS multi_flag_value_share
    FROM tender_risk
    GROUP BY province
    ORDER BY multi_flag_rate DESC;
    """)


def export(con):
    MODEL.mkdir(exist_ok=True)
    for table in ["tender_risk", "province_summary", "repeat_winners", "split_pairs"]:
        con.execute(f"COPY {table} TO '{(MODEL / table).as_posix()}.csv' (HEADER)")


def main():
    con = duckdb.connect(str(ROOT / "procurement.duckdb"))
    build(con)
    export(con)
    print(con.sql("""
        SELECT count(*) FILTER (WHERE completed) AS completed,
               sum(flag_single_bid::INT) AS single_bid, sum(flag_near_hps::INT) AS near_hps,
               sum(flag_lowest_not_winner::INT) AS lowest_not_winner,
               sum(flag_tight_bid_spread::INT) AS tight_spread, sum(flag_hps_equals_pagu::INT) AS hps_eq_pagu,
               sum(flag_repeat_winner::INT) AS repeat_winner, sum(flag_possible_split::INT) AS possible_split,
               count(*) FILTER (WHERE n_flags >= 2) AS two_plus_flags
        FROM tender_risk WHERE completed AND hps IS NOT NULL
    """))


if __name__ == "__main__":
    main()
