import sqlite3

from detect.models import FoodRiskResult, RegulatoryEntry


class FoodRiskQuery:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(
        self, food_category: str, contaminant: str | None = None
    ) -> FoodRiskResult | list[FoodRiskResult] | None:
        resolved = self._resolve_category(food_category)

        sql = "SELECT * FROM app_food_overview WHERE food_category = ?"
        params: list = [resolved]

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

    def _resolve_category(self, name: str) -> str:
        """Resolve a user-provided category name to the canonical form in the DB.

        Tries in order:
        1. Exact match in app_food_overview
        2. Lookup via category_aliases table
        3. Singular/plural variations (strip/add 's', 'es', 'ies'→'y')
        4. Case-insensitive LIKE match in app_food_overview
        5. Return original as-is (will yield empty results)
        """
        # 1. Exact match
        row = self._conn.execute(
            "SELECT 1 FROM app_food_overview WHERE food_category = ? LIMIT 1",
            (name,),
        ).fetchone()
        if row:
            return name

        # 2. Category aliases lookup
        alias_row = self._conn.execute(
            "SELECT canonical_key FROM category_aliases WHERE alias = ?",
            (name.lower(),),
        ).fetchone()
        if alias_row:
            canonical = alias_row["canonical_key"]
            # Check if canonical key exists in the view
            row = self._conn.execute(
                "SELECT 1 FROM app_food_overview WHERE food_category = ? LIMIT 1",
                (canonical,),
            ).fetchone()
            if row:
                return canonical

        # 3. Singular/plural variations
        variants = set()
        lower = name.lower().strip()
        variants.add(lower)
        # Strip trailing 's' (strawberries → strawberry)
        if lower.endswith("ies"):
            variants.add(lower[:-3] + "y")  # berries → berry
        if lower.endswith("es"):
            variants.add(lower[:-2])  # tomatoes → tomato
        if lower.endswith("s") and not lower.endswith("ss"):
            variants.add(lower[:-1])  # oats → oat
        # Add trailing 's' (strawberry → strawberries)
        if not lower.endswith("s"):
            variants.add(lower + "s")
            if lower.endswith("y"):
                variants.add(lower[:-1] + "ies")  # berry → berries

        for v in variants:
            if v == name:
                continue
            row = self._conn.execute(
                "SELECT 1 FROM app_food_overview WHERE food_category = ? LIMIT 1",
                (v,),
            ).fetchone()
            if row:
                return v

        # 4. Case-insensitive LIKE match
        like_row = self._conn.execute(
            "SELECT food_category FROM app_food_overview "
            "WHERE LOWER(food_category) = ? LIMIT 1",
            (lower,),
        ).fetchone()
        if like_row:
            return like_row["food_category"]

        # 5. Give up — return original
        return name

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
