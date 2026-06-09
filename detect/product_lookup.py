import sqlite3

from detect.models import ProductResult


class ProductLookupQuery:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(
        self, query: str, contaminant: str | None = None
    ) -> list[ProductResult]:
        sql = "SELECT * FROM app_product_lookup WHERE product_name LIKE ?"
        params: list = [f"%{query}%"]

        if contaminant is not None:
            sql += " AND contaminant = ?"
            params.append(contaminant)

        rows = self._conn.execute(sql, params).fetchall()
        return [self._build_result(row) for row in rows]

    def _build_result(self, row: sqlite3.Row) -> ProductResult:
        d = dict(row)
        return ProductResult(
            product_name=d["product_name"],
            food_category=d["food_category"],
            contaminant=d["contaminant"],
            source_name=d["source_name"],
            report_label=d["report_label"],
            data_year=d["data_year"],
            measured_ppb=d.get("measured_ppb"),
            below_detection=bool(d["below_detection"]),
            is_organic=bool(d["is_organic"]),
            is_grf_certified=bool(d["is_grf_certified"]),
            risk_level=d.get("risk_level", "unknown"),
            confidence=d["confidence"],
            source_url=d.get("source_url"),
        )
