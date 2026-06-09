import sqlite3

from detect.models import WaterQualityResult

VALID_CONTAMINANTS = {"glyphosate", "lead", "atrazine"}


class WaterQualityQuery:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(
        self,
        state: str | None = None,
        contaminant: str | None = None,
        water_type: str | None = None,
    ) -> list[WaterQualityResult]:
        if contaminant is not None and contaminant not in VALID_CONTAMINANTS:
            raise ValueError(
                f"Invalid contaminant '{contaminant}'. "
                f"Valid options: {sorted(VALID_CONTAMINANTS)}"
            )

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
        sql = f"SELECT * FROM app_water_overview{where}"

        rows = self._conn.execute(sql, params).fetchall()

        return [self._build_result(row) for row in rows]

    def _build_result(self, row: sqlite3.Row) -> WaterQualityResult:
        d = dict(row)
        return WaterQualityResult(
            state=d["state"],
            contaminant=d["contaminant"],
            water_type=d["water_type"],
            source_name=d["source_name"],
            data_year=d["data_year"],
            detection_rate=d.get("detection_rate"),
            avg_ppb=d.get("avg_ppb"),
            max_ppb=d.get("max_ppb"),
            samples_total=d.get("samples_total"),
            epa_mcl_ppb=d.get("epa_mcl_ppb"),
            pct_of_mcl=d.get("pct_of_mcl"),
        )