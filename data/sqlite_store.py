"""
data/sqlite_store.py
SqliteDataStore — implements the DataStore protocol using sqlite3.
Extracts all SQL from the existing query modules so they can be retired.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

# Shared commodity resolver. Dual-root import: this module is loaded as
# ``data.sqlite_store`` (project root on path) in tests and as ``sqlite_store``
# (data/ on path) at runtime, so neither prefix is universally valid.
try:  # project-root / test context
    from data.commodity_resolver import resolve_commodity, extract_forms
except ImportError:  # runtime context: data/ is the path root
    from commodity_resolver import resolve_commodity, extract_forms


_DEFAULT_DB_PATH = Path(__file__).parent / "residueiq.db"


# `app_food_overview` is defined as a VIEW in schema.sql, but reading it
# re-aggregates the entire category_summaries table (~730k rows: window
# functions + 5 CTEs) on every call -> ~12s. This parameterized inline query
# pushes the food_category/contaminant filter into each CTE so SQLite uses
# indexes -> ~7ms (single contaminant) / ~130ms (all). Verified byte-identical
# to the view across 8 cases (single + all-contaminant, populated + empty) on
# 2026-07-16. The view stays as the source-of-truth/reference and is still used
# by _resolve_category's existence check (on the base table, below).
_FOOD_OVERVIEW_SQL = """
WITH best_summary AS (
    SELECT cs.food_category, cs.contaminant, cs.source_name, cs.report_label,
           cs.data_year, cs.samples_total, cs.samples_detected, cs.detection_rate,
           cs.avg_ppb, cs.max_ppb, cs.confidence,
           CASE WHEN cs.detection_rate >= 0.66 THEN 'high'
                WHEN cs.detection_rate >= 0.31 THEN 'medium'
                WHEN cs.detection_rate >  0.0  THEN 'low'
                ELSE 'none' END AS detection_frequency,
           ROW_NUMBER() OVER (
               PARTITION BY cs.food_category, cs.contaminant
               ORDER BY CASE cs.source_name WHEN 'FDA' THEN 3 WHEN 'CFIA' THEN 2
                            WHEN 'EFSA' THEN 1 ELSE 0 END DESC, cs.data_year DESC) AS rn
    FROM category_summaries cs
    WHERE cs.food_category = :fc {cont_cs}
),
product_stats AS (
    SELECT pt.food_category, pt.contaminant,
           COUNT(DISTINCT pt.product_name) AS total_products_tested,
           COUNT(DISTINCT CASE WHEN pt.below_detection = 0 THEN pt.product_name END) AS products_with_detection,
           ROUND(AVG(pt.measured_ppb), 1) AS avg_product_ppb,
           MAX(pt.measured_ppb) AS max_product_ppb
    FROM product_tests pt
    WHERE pt.food_category = :fc {cont_pt}
    GROUP BY pt.food_category, pt.contaminant
),
tolerance_data AS (
    SELECT food_category, contaminant, MIN(tolerance_ppb) AS min_tolerance_ppb,
           MIN(source) AS tolerance_source
    FROM tolerance_limits
    WHERE tolerance_ppb > 0 AND food_category = :fc {cont_tl}
    GROUP BY food_category, contaminant
),
mrl_data AS (
    SELECT food_category, pesticide AS contaminant, MIN(mrl_ppb) AS min_mrl_ppb,
           MIN(regulatory_body) AS mrl_source
    FROM international_mrls
    WHERE mrl_ppb > 0 AND food_category = :fc {cont_mrl}
    GROUP BY food_category, pesticide
)
SELECT bs.contaminant, bs.food_category, bs.source_name AS best_source,
       bs.data_year AS best_data_year, bs.detection_rate, bs.avg_ppb, bs.max_ppb,
       bs.samples_total, bs.samples_detected,
       CASE WHEN bs.max_ppb IS NULL OR bs.max_ppb <= 0 THEN 'none'
            WHEN td.min_tolerance_ppb IS NOT NULL AND td.min_tolerance_ppb > 0 THEN
                CASE WHEN bs.max_ppb / td.min_tolerance_ppb >= 2.0 THEN 'high'
                     WHEN bs.max_ppb / td.min_tolerance_ppb >= 1.0 THEN 'medium'
                     ELSE 'low' END
            WHEN md.min_mrl_ppb IS NOT NULL AND md.min_mrl_ppb > 0 THEN
                CASE WHEN bs.max_ppb / md.min_mrl_ppb >= 2.0 THEN 'high'
                     WHEN bs.max_ppb / md.min_mrl_ppb >= 1.0 THEN 'medium'
                     ELSE 'low' END
            ELSE 'unknown' END AS risk_level,
       bs.detection_frequency, bs.confidence,
       COALESCE(ps.total_products_tested, 0) AS total_products_tested,
       COALESCE(ps.products_with_detection, 0) AS products_with_detection,
       COALESCE(ps.avg_product_ppb, 0) AS avg_product_ppb,
       COALESCE(ps.max_product_ppb, 0) AS max_product_ppb,
       COALESCE((SELECT COUNT(*) FROM certified_products cp
                  WHERE cp.food_category = bs.food_category AND cp.contaminant IS NULL)
              + (SELECT COUNT(*) FROM certified_products cp
                  WHERE cp.food_category = bs.food_category AND cp.contaminant = bs.contaminant), 0)
           AS certified_products_available,
       COALESCE(td.min_tolerance_ppb, md.min_mrl_ppb) AS tolerance_ppb,
       COALESCE(td.tolerance_source, md.mrl_source) AS tolerance_source
FROM best_summary bs
LEFT JOIN product_stats ps ON bs.food_category = ps.food_category AND bs.contaminant = ps.contaminant
LEFT JOIN tolerance_data td ON bs.food_category = td.food_category AND bs.contaminant = td.contaminant
LEFT JOIN mrl_data md ON bs.food_category = md.food_category AND bs.contaminant = md.contaminant
WHERE bs.rn = 1
"""


class SqliteDataStore:
    """SQLite-backed DataStore. Reads from the same database the pipeline writes to."""

    def __init__(self, db_path: Optional[str] = None, *,
                 read_only: bool = False,
                 check_same_thread: Optional[bool] = None):
        """Open the SQLite connection.

        Defaults preserve the original behavior (read-write, default
        ``check_same_thread``). The API server passes ``read_only=True`` (safer
        for a shared, image/GCS-served DB) and ``check_same_thread=False`` (the
        connection is guarded by a Lock in the API layer so it may be touched by
        FastAPI's threadpool).
        """
        path = str(db_path or _DEFAULT_DB_PATH)
        connect_kwargs: dict = {}
        if read_only:
            # SQLite file: URI with mode=ro; absolute path via as_uri() (cross-platform).
            target = Path(path).resolve().as_uri() + "?mode=ro"
            connect_kwargs["uri"] = True
        else:
            target = path
        if check_same_thread is not None:
            connect_kwargs["check_same_thread"] = check_same_thread
        self._conn = sqlite3.connect(target, **connect_kwargs)
        self._conn.row_factory = sqlite3.Row

    # ── helpers ─────────────────────────────────────────────────────────

    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _row(self, sql: str, params: tuple = ()) -> Optional[dict]:
        r = self._conn.execute(sql, params).fetchone()
        return dict(r) if r else None

    # ── App-facing views ────────────────────────────────────────────────

    def get_food_overview(
        self, food_category: str, contaminant: Optional[str] = None
    ) -> list[dict]:
        resolved = self._resolve_category(food_category)
        if contaminant is not None:
            sql = _FOOD_OVERVIEW_SQL.format(
                cont_cs="AND cs.contaminant = :cont",
                cont_pt="AND pt.contaminant = :cont",
                cont_tl="AND contaminant = :cont",
                cont_mrl="AND pesticide = :cont",
            )
            params: dict | tuple = {"fc": resolved, "cont": contaminant}
        else:
            sql = _FOOD_OVERVIEW_SQL.format(
                cont_cs="", cont_pt="", cont_tl="", cont_mrl=""
            )
            params = {"fc": resolved}
        return self._rows(sql, params)

    def get_product_lookup(
        self, query: str, contaminant: Optional[str] = None
    ) -> list[dict]:
        sql = "SELECT * FROM app_product_lookup WHERE product_name LIKE ?"
        params: list = [f"%{query}%"]
        if contaminant is not None:
            sql += " AND contaminant = ?"
            params.append(contaminant)
        return self._rows(sql, tuple(params))

    def get_water_overview(
        self,
        state: Optional[str] = None,
        contaminant: Optional[str] = None,
        water_type: Optional[str] = None,
    ) -> list[dict]:
        conditions = []
        params: list = []
        if state is not None:
            conditions.append("state = ?")
            params.append(state)
        if contaminant is not None:
            conditions.append("contaminant = ?")
            params.append(contaminant)
        if water_type is not None:
            conditions.append("water_type = ?")
            params.append(water_type)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return self._rows(f"SELECT * FROM app_water_overview{where}", tuple(params))

    def get_international_comparison(
        self, food_category: str, contaminant: Optional[str] = None
    ) -> list[dict]:
        resolved = resolve_commodity(food_category, self._conn) or food_category
        sql = "SELECT * FROM app_international_comparison WHERE food_category = ?"
        params: list = [resolved]
        if contaminant is not None:
            sql += " AND contaminant = ?"
            params.append(contaminant)
        return self._rows(sql, tuple(params))

    # ── Raw table reads ─────────────────────────────────────────────────

    def get_product_tests(
        self, product_name: str, contaminant: str
    ) -> Optional[dict]:
        return self._row(
            "SELECT product_name, measured_ppb, below_detection, is_grf_certified, "
            "is_organic, food_category, source_name, data_year "
            "FROM product_tests "
            "WHERE product_name LIKE ? AND contaminant = ? "
            "ORDER BY data_year DESC LIMIT 1",
            (f"%{product_name}%", contaminant),
        )

    def get_category_summaries(
        self,
        food_category: str,
        contaminant: str,
        source_priority: Optional[str] = None,
    ) -> Optional[dict]:
        if source_priority is None:
            source_priority = (
                "CASE source_name "
                "WHEN 'FDA' THEN 3 "
                "WHEN 'CFIA' THEN 2 "
                "WHEN 'EFSA' THEN 1 "
                "ELSE 0 END"
            )
        return self._row(
            "SELECT food_category, detection_rate, avg_ppb, max_ppb, "
            "source_name, data_year, confidence "
            "FROM category_summaries "
            "WHERE food_category = ? AND contaminant = ? "
            f"ORDER BY {source_priority} DESC, data_year DESC LIMIT 1",
            (food_category, contaminant),
        )

    def get_biomonitoring(
        self, analyte: Optional[str] = None, cycle: Optional[str] = None
    ) -> list[dict]:
        conditions = []
        params: list = []
        if analyte:
            conditions.append("analyte = ?")
            params.append(analyte)
        if cycle:
            conditions.append("cycle = ?")
            params.append(cycle)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return self._rows(
            f"SELECT * FROM biomonitoring{where} ORDER BY analyte, cycle",
            tuple(params),
        )

    def get_ingredient(
        self,
        ingredient_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[dict]:
        if ingredient_id:
            row = self._row(
                "SELECT * FROM ingredients WHERE ingredient_id = ?",
                (ingredient_id,),
            )
            if row:
                return row

        if name:
            name_lower = name.lower()
            candidates = self._rows(
                "SELECT * FROM ingredients WHERE aliases LIKE ?",
                (f"%{name_lower}%",),
            )
            for c in candidates:
                try:
                    alias_list = json.loads(c["aliases"]) if c["aliases"] else []
                    if name_lower in [a.lower() for a in alias_list]:
                        return c
                except (json.JSONDecodeError, TypeError):
                    pass

        return None

    def get_regulatory_flags(self, ingredient_id: str) -> list[dict]:
        return self._rows(
            "SELECT * FROM regulatory_flags WHERE ingredient_id = ?",
            (ingredient_id,),
        )

    def get_commodity(self, commodity_slug: str) -> Optional[dict]:
        return self._row(
            "SELECT * FROM commodities WHERE commodity_slug = ?",
            (commodity_slug.lower(),),
        )

    def get_all_commodities_with_aliases(self) -> list[dict]:
        return self._rows(
            "SELECT commodity_slug, ingredient_aliases FROM commodities "
            "WHERE ingredient_aliases IS NOT NULL"
        )

    def get_plu(self, plu_code: str) -> Optional[dict]:
        return self._row(
            "SELECT * FROM plu_codes WHERE plu = ?",
            (str(plu_code),),
        )

    def get_plu_by_commodity(self, commodity_slug: str) -> list[dict]:
        return self._rows(
            "SELECT * FROM plu_codes WHERE commodity_slug = ? ORDER BY plu",
            (commodity_slug,),
        )

    def get_alternatives(
        self, product_name: str, brand: Optional[str] = None
    ) -> Optional[dict]:
        # 1. Exact match on product name + brand
        if brand:
            row = self._row(
                "SELECT * FROM alternatives WHERE flagged_product_name = ? AND LOWER(flagged_brand) = ?",
                (product_name, brand.lower().strip()),
            )
            if row:
                return row

        # 2. Exact match on product name
        row = self._row(
            "SELECT * FROM alternatives WHERE flagged_product_name = ?",
            (product_name,),
        )
        if row:
            return row

        return None

    def get_alternatives_case_insensitive(self, product_name: str) -> Optional[dict]:
        return self._row(
            "SELECT * FROM alternatives WHERE LOWER(flagged_product_name) = ?",
            (product_name.lower(),),
        )

    def get_alternatives_by_brand_word(
        self, brand: str, word: str
    ) -> Optional[dict]:
        return self._row(
            "SELECT * FROM alternatives WHERE LOWER(flagged_brand) = ? "
            "AND LOWER(flagged_product_name) LIKE ?",
            (brand.lower().strip(), f"%{word}%"),
        )

    def get_alternatives_by_word(self, word: str) -> Optional[dict]:
        return self._row(
            "SELECT * FROM alternatives WHERE LOWER(flagged_product_name) LIKE ?",
            (f"%{word}%",),
        )

    def get_alternatives_by_brand(self, brand: str) -> Optional[dict]:
        return self._row(
            "SELECT * FROM alternatives WHERE LOWER(flagged_brand) = ?",
            (brand.lower().strip(),),
        )

    def get_certified_products(self) -> list[dict]:
        return self._rows('''
            SELECT product_name, brand, certification, raw_category
            FROM certified_products
            ORDER BY
                CASE certification
                    WHEN 'Glyphosate Residue Free' THEN 1
                    WHEN 'Clean Label Project Certified' THEN 2
                    WHEN 'USDA Organic' THEN 3
                    WHEN 'EU Organic' THEN 4
                    WHEN 'Canada Organic' THEN 5
                    WHEN 'Soil Association Organic' THEN 6
                    WHEN 'Non-GMO Project Verified' THEN 7
                    ELSE 8
                END
        ''')

    def get_all_ingredients(self) -> list[dict]:
        return self._rows("SELECT * FROM ingredients ORDER BY ingredient_id")

    def get_all_commodities(self) -> list[dict]:
        return self._rows("SELECT * FROM commodities ORDER BY commodity_slug")

    # ── Regulatory / benchmark lookups ──────────────────────────────────

    def get_category_aliases(self) -> list[dict]:
        return self._rows("SELECT alias, canonical_key FROM category_aliases")

    def get_category_alias(self, alias: str) -> Optional[str]:
        row = self._row(
            "SELECT canonical_key FROM category_aliases WHERE alias = ?",
            (alias.lower(),),
        )
        return row["canonical_key"] if row else None

    def get_tolerance_limit(
        self, contaminant: str, food_category: str, raw: Optional[str] = None
    ) -> Optional[dict]:
        resolved = self.resolve_benchmark_category(
            food_category, "tolerance_limits", raw
        )
        return self._row(
            "SELECT tolerance_ppb, source FROM tolerance_limits "
            "WHERE LOWER(contaminant) = ? AND LOWER(food_category) = ? "
            "AND tolerance_ppb > 0 "
            "ORDER BY tolerance_ppb ASC LIMIT 1",
            (contaminant.lower(), resolved.lower()),
        )

    def get_all_tolerance_limits(
        self, contaminant: str, food_category: str, raw: Optional[str] = None
    ) -> list[dict]:
        resolved = self.resolve_benchmark_category(
            food_category, "tolerance_limits", raw
        )
        return self._rows(
            "SELECT source, tolerance_ppb, regulation_reference "
            "FROM tolerance_limits "
            "WHERE food_category = ? AND contaminant = ?",
            (resolved, contaminant),
        )

    def get_strictest_mrl(
        self, contaminant: str, food_category: str, raw: Optional[str] = None
    ) -> Optional[dict]:
        resolved = self.resolve_benchmark_category(
            food_category, "international_mrls", raw
        )
        return self._row(
            "SELECT mrl_ppb, country_region FROM international_mrls "
            "WHERE LOWER(pesticide) = ? AND LOWER(food_category) = ? "
            "AND mrl_ppb > 0 "
            "ORDER BY mrl_ppb ASC LIMIT 1",
            (contaminant.lower(), resolved.lower()),
        )

    def get_consumption_tier(self, food_category: str) -> Optional[str]:
        row = self._row(
            "SELECT consumption_tier FROM commodities WHERE commodity_slug = ?",
            (food_category,),
        )
        return row["consumption_tier"] if row else None

    def get_contaminant_type(self, contaminant: str) -> Optional[str]:
        # Try ingredients table first
        row = self._row(
            "SELECT contaminant_type FROM ingredients WHERE ingredient_id = ?",
            (contaminant.lower().replace(" ", "_"),),
        )
        if row and row["contaminant_type"]:
            return row["contaminant_type"]

        # Try contaminants.py registry
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from contaminants import CONTAMINANTS
            config = CONTAMINANTS.get(contaminant.lower())
            if config:
                return config.get("type", "unknown")
        except ImportError:
            pass

        # Infer from name
        _HEAVY_METALS = frozenset({
            "lead", "inorganic_arsenic", "cadmium", "mercury", "arsenic",
        })
        if contaminant.lower() in _HEAVY_METALS:
            return "heavy_metal"
        return "pesticide"

    def get_all_contaminants_for_category(
        self, food_category: str, source_priority_sql: str
    ) -> list[dict]:
        return self._rows(
            f"""
            SELECT contaminant, detection_rate, avg_ppb, max_ppb,
                   samples_total, samples_detected, source_name, data_year
            FROM (
                SELECT contaminant, detection_rate, avg_ppb, max_ppb,
                       samples_total, samples_detected, source_name, data_year,
                       ROW_NUMBER() OVER (
                           PARTITION BY contaminant
                           ORDER BY {source_priority_sql} DESC, data_year DESC
                       ) AS rn
                FROM category_summaries
                WHERE food_category = ?
                AND detection_rate > 0
            )
            WHERE rn = 1
            ORDER BY detection_rate DESC
            """,
            (food_category,),
        )

    def resolve_benchmark_category(
        self, food_category: str, table: str, raw: Optional[str] = None
    ) -> str:
        fc = food_category.strip()
        candidates = [fc]

        if fc.endswith("s"):
            candidates.append(fc[:-1])
        else:
            candidates.append(fc + "s")
        if fc.endswith("ies"):
            candidates.append(fc[:-3] + "y")
        elif fc.endswith("es"):
            candidates.append(fc[:-2])
        if "_" in fc:
            candidates.append(fc.replace("_", " "))
        if " " in fc:
            candidates.append(fc.replace(" ", "_"))

        # Reverse alias lookup
        alias_rows = self._rows(
            "SELECT alias FROM category_aliases WHERE canonical_key = ?",
            (fc,),
        )
        for r in alias_rows:
            candidates.append(r["alias"])

        lower_set = set()
        final = []
        for c in candidates:
            cl = c.lower()
            if cl not in lower_set:
                lower_set.add(cl)
                final.append(c)

        placeholders = ",".join("?" * len(final))
        row = self._row(
            f"SELECT DISTINCT food_category FROM {table} "
            f"WHERE LOWER(food_category) IN ({placeholders}) LIMIT 1",
            tuple(c.lower() for c in final),
        )
        base_match = row["food_category"] if row else fc

        # Form-aware refinement: when ``raw`` carries a form token (dried/fresh/
        # juice) and the benchmark table has form-specific rows for this
        # commodity (e.g. ``basil, dried leaves`` vs ``basil, fresh leaves``,
        # whose EPA tolerances diverge up to 6.7x), prefer the form that
        # matches the raw. No raw, or no form token, => current behavior.
        raw_forms = extract_forms(raw)
        if not raw_forms:
            return base_match
        base_lowers = {c.lower() for c in final}
        scored = []
        for r in self._rows(
            f"SELECT DISTINCT food_category FROM {table} "
            f"WHERE food_category IS NOT NULL"
        ):
            fcat = r["food_category"]
            head = fcat.split(",", 1)[0].strip().lower()
            if head not in base_lowers:
                continue
            suffix = fcat.split(",", 1)[1].lower() if "," in fcat else ""
            cand_forms = extract_forms(suffix)
            primary = (
                1 if (cand_forms & raw_forms) else (-1 if cand_forms else 0)
            )
            scored.append((primary, len(fcat), fcat))
        if not scored:
            return base_match
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return scored[0][2]

    # ── Internal helpers (from database.py) ─────────────────────────────

    def _resolve_category(self, name: str) -> str:
        """Resolve a user-provided category name to a canonical key that exists
        in the food overview view, via the shared resolver.

        Delegates to data.commodity_resolver.resolve_commodity (which handles
        exact, singular/plural, and first-segment group-string matching), then
        confirms the resolved key is present in category_summaries so callers
        never receive a phantom key. Falls back to the input name.

        Existence is checked on category_summaries (indexed) rather than the
        app_food_overview view: the view's food_category set is exactly
        category_summaries' set (its rn=1 filter dedups per contaminant but
        removes no category), and reading the view re-aggregates ~730k rows."""
        if not name:
            return name
        resolved = resolve_commodity(name, self._conn)
        for candidate in (resolved, name):
            if not candidate:
                continue
            row = self._row(
                "SELECT 1 FROM category_summaries WHERE food_category = ? LIMIT 1",
                (candidate,),
            )
            if row:
                return candidate
        return name

    # ── Lifecycle ───────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()
