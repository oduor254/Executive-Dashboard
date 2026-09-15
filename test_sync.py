from __future__ import annotations

from datetime import date, timedelta
from dotenv import load_dotenv
import sys

load_dotenv()

try:
    from lib import db, queries, deals, sheets_sync
except Exception as exc:
    print("Failed importing app modules:", exc)
    sys.exit(2)

start_date = date.today() - timedelta(days=7)
end_date = date.today()
print(f"Testing sync for {start_date} -> {end_date}")

try:
    df = db.run_query(queries.PRODUCT_LINE_ITEMS, {"start_date": start_date, "end_date": end_date})
    print(f"Queried {len(df)} rows")
except Exception as exc:
    print("DB query failed:", exc)
    sys.exit(3)

try:
    classified = deals.classify(df)
    print(f"Classified {len(classified)} rows")
except Exception as exc:
    print("Classification failed:", exc)
    sys.exit(4)

try:
    result = sheets_sync.sync(classified, start_date, end_date)
    print("Sheets sync result:", result)
except Exception as exc:
    print("Sheets sync failed:", exc)
    sys.exit(5)

print("Test completed successfully")
