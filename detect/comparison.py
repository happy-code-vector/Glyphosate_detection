import sqlite3

from detect.models import InternationalComparisonEntry, InternationalComparisonResult

VALID_CONTAMINANTS = {"glyphosate", "lead", "atrazine"}


class ComparisonQuery:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(
        self, food_category: str, contaminant: str = "glyphosate"
    ) -> InternationalComparisonResult:
        if contaminant not in VALID_CONTAMINANTS:
            raise ValueError(
                f"Invalid contaminant '{contaminant}'. "
                f"Valid options: {sorted(VALID_CONTAMINANTS)}"
            )

        if contaminant == "glyphosate":
            rows = self._conn.execute(
                "SELECT * FROM app_international_comparison WHERE food_category = ?",
                (food_category,),
            ).fetchall()
        else:
            rows = self._query_multi_contaminant(food_category, contaminant)

        entries = [
            InternationalComparisonEntry(
                country_region=r["country_region"],
                mrl_ppb=r["mrl_ppb"],
                regulatory_body=r["regulatory_body"] if r["regulatory_body"] is not None else None,
                measured_max_ppb=r["measured_max_ppb"] if r["measured_max_ppb"] is not None else None,
                pct_of_mrl=r["pct_of_mrl"] if r["pct_of_mrl"] is not None else None,
            )
            for r in rows
        ]

        return InternationalComparisonResult(
            food_category=food_category,
            contaminant=contaminant,
            entries=entries,
        )

    def _query_multi_contaminant(
        self, food_category: str, contaminant: str
    ) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT im.food_category, im.country_region, im.mrl_ppb, "
            "im.regulatory_body, im.source_url, "
            "cs.max_ppb AS measured_max_ppb, "
            "CASE WHEN im.mrl_ppb > 0 AND cs.max_ppb IS NOT NULL "
            "THEN ROUND(cs.max_ppb / im.mrl_ppb * 100, 1) END AS pct_of_mrl "
            "FROM international_mrls im "
            "LEFT JOIN category_summaries cs "
            "ON im.food_category = cs.food_category AND cs.contaminant = ? "
            "WHERE im.food_category = ? AND im.pesticide = ? "
            "ORDER BY im.mrl_ppb ASC",
            (contaminant, food_category, contaminant),
        ).fetchall()