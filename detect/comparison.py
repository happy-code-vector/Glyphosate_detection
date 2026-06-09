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

        rows = self._conn.execute(
            "SELECT * FROM app_international_comparison "
            "WHERE food_category = ? AND contaminant = ?",
            (food_category, contaminant),
        ).fetchall()

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
