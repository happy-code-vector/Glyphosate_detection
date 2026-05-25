import sys

from db import init_db, insert_rows
from fetch_cfia import fetch as fetch_cfia
from fetch_efsa import fetch as fetch_efsa
from fetch_fda import fetch as fetch_fda
from fetch_ewg import fetch as fetch_ewg
from fetch_florida import fetch as fetch_florida


def main():
    # Allow --fallback flag to skip live downloads and use hardcoded data
    use_fallback = "--fallback" in sys.argv

    init_db()

    sources = [
        ("CFIA", lambda: fetch_cfia()),
        ("EFSA", lambda: fetch_efsa(use_fallback=use_fallback)),
        ("FDA", lambda: fetch_fda(use_fallback=use_fallback)),
        ("EWG", lambda: fetch_ewg() if not use_fallback else []),
        ("Florida HFF", lambda: fetch_florida()),
    ]

    total = 0
    for name, fetcher in sources:
        print(f"\n{'='*50}")
        print(f"Fetching: {name}")
        print(f"{'='*50}")
        try:
            rows = fetcher()
            print(f"  Got {len(rows)} rows from {name}")
            insert_rows(rows)
            total += len(rows)
        except Exception as e:
            print(f"  ERROR fetching {name}: {e}")
            if "--strict" in sys.argv:
                raise

    print(f"\n{'='*50}")
    print(f"Pipeline complete. Total rows processed: {total}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
