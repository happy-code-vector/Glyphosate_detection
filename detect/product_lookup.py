import sqlite3

from detect.models import ProductResult

VALID_CONTAMINANTS = {"glyphosate", "lead", "atrazine"}


class ProductLookupQuery:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(
        self, query: str, contaminant: str | None = None
    ) -> list[ProductResult]:
        if contaminant is not None and contaminant not in VALID_CONTAMINANTS:
            raise ValueError(
                f"Invalid contaminant '{contaminant}'. "
                f"Valid options: {sorted(VALID_CONTAMINANTS)}"
            )

        sql = "SELECT * FROM app_product_lookup WHERE product_name LIKE ?"
        params: list = [f"%{query}%"]

        if contaminant is not None:
            sql += " AND contaminant = ?"
            params.append(contaminant)

        rows = self._conn.execute(sql, params).fetchall()

        return [self._build_result(row) for row in rows]

    def _build_result(self, row: sqlite3.Row) -> ProductResult:
        d = dict(row)
        below_det = d.get("below_detection", 0)
        ppb = d.get("measured_ppb")
        risk = self._classify_risk(d.get("contaminant", "glyphosate"), ppb, below_det)

        return ProductResult(
            product_name=d["product_name"],
            food_category=d["food_category"],
            contaminant=d["contaminant"],
            source_name=d["source_name"],
            report_label=d["report_label"],
            data_year=d["data_year"],
            measured_ppb=ppb,
            below_detection=bool(below_det),
            is_organic=bool(d.get("is_organic", 0)),
            is_grf_certified=bool(d.get("is_grf_certified", 0)),
            risk_level=risk,
            confidence=d["confidence"],
            source_url=d.get("source_url"),
        )

    @staticmethod
    def _classify_risk(contaminant: str, ppb: float | None, below_detection: int) -> str:
        if below_detection:
            return "none"
        if ppb is None or ppb <= 0:
            return "unknown"
        thresholds = {
            "glyphosate": {"high": 500, "medium": 100},
            "lead": {"high": 15, "medium": 5},
            "atrazine": {"high": 3, "medium": 1},
        }
        t = thresholds.get(contaminant, thresholds["glyphosate"])
        if ppb >= t["high"]:
            return "high"
        if ppb >= t["medium"]:
            return "medium"
        return "low"