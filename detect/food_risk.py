import sqlite3
import sys
from pathlib import Path

from detect.models import FoodRiskResult, RegulatoryEntry

# Add data directory to path for contaminant imports
sys.path.insert(0, str(Path(__file__).parent.parent / "data"))
try:
    from contaminants import CONTAMINANT_KEYS
    VALID_CONTAMINANTS = set(CONTAMINANT_KEYS)
except ImportError:
    VALID_CONTAMINANTS = {"glyphosate", "lead", "atrazine"}


class FoodRiskQuery:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(
        self, food_category: str, contaminant: str | None = None
    ) -> FoodRiskResult | list[FoodRiskResult] | None:
        if contaminant is not None and contaminant not in VALID_CONTAMINANTS:
            raise ValueError(
                f"Invalid contaminant '{contaminant}'. "
                f"Valid options: {sorted(VALID_CONTAMINANTS)}"
            )

        sql = "SELECT * FROM app_food_overview WHERE food_category = ?"
        params: list = [food_category]

        if contaminant is not None:
            sql += " AND contaminant = ?"
            params.append(contaminant)

        rows = self._conn.execute(sql, params).fetchall()

        if not rows:
            return None if contaminant is not None else []

        if contaminant is not None:
            return self._build_result(rows[0])

        return [self._build_result(row) for row in rows]

    def _build_result(self, row: sqlite3.Row) -> FoodRiskResult:
        d = dict(row)
        reg_entries = self._get_regulatory_comparison(
            d["food_category"], d["contaminant"]
        )
        return FoodRiskResult(
            food_category=d["food_category"],
            contaminant=d["contaminant"],
            best_source=d["best_source"],
            data_year=d["best_data_year"],
            detection_rate=d["detection_rate"],
            avg_ppb=d.get("avg_ppb"),
            max_ppb=d.get("max_ppb"),
            samples_total=d["samples_total"],
            samples_detected=d["samples_detected"],
            risk_level=d["risk_level"],
            confidence=d["confidence"],
            total_products_tested=d.get("total_products_tested", 0),
            products_with_detection=d.get("products_with_detection", 0),
            certified_products_available=d.get("certified_products_available", 0),
            regulatory_comparison=reg_entries,
        )

    def _get_regulatory_comparison(
        self, food_category: str, contaminant: str
    ) -> list[RegulatoryEntry]:
        rows = self._conn.execute(
            "SELECT source, tolerance_ppb, regulation_reference "
            "FROM tolerance_limits "
            "WHERE food_category = ? AND contaminant = ?",
            (food_category, contaminant),
        ).fetchall()
        return [
            RegulatoryEntry(
                source=r["source"],
                tolerance_ppb=r["tolerance_ppb"],
                regulation_reference=r["regulation_reference"],
                pct_of_tolerance=None,
            )
            for r in rows
        ]