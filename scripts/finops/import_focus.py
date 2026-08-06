"""Import a FOCUS CSV through the trusted billing ingestion API."""

from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.request
import uuid
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--base-url", default=os.getenv("FINOPS_BASE_URL", ""))
    parser.add_argument("--tenant-id", default=os.getenv("FINOPS_TENANT_ID", ""))
    parser.add_argument("--watermark", required=True)
    args = parser.parse_args()
    if not args.base_url or not args.tenant_id:
        print("BLOCKED: set --base-url/FINOPS_BASE_URL and --tenant-id/FINOPS_TENANT_ID")
        return 2

    lines: list[dict[str, str]] = []
    with args.csv_file.open(newline="", encoding="utf-8-sig") as stream:
        for index, row in enumerate(csv.DictReader(stream), start=1):
            source_id = row.get("BillingAccountId") or row.get("LineItem/Reference") or f"focus-{index}"
            amount = row.get("BilledCost") or row.get("EffectiveCost")
            currency = row.get("BillingCurrency") or row.get("Currency")
            if not amount or not currency:
                raise ValueError(f"FOCUS row {index} lacks BilledCost/EffectiveCost or BillingCurrency")
            lines.append({
                "source_id": source_id,
                "currency": currency,
                "unit": row.get("ServiceName") or "cost",
                "amount": amount,
                "watermark": args.watermark,
                "raw_ref": f"focus-csv://{args.csv_file.name}#row-{index}",
            })

    payload = json.dumps({"watermark": args.watermark, "raw_lines": lines}).encode("utf-8")
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/billing-ingestions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Tenant-Id": args.tenant_id,
            "X-Role": "billing-admin",
            "X-Request-Id": "focus-import-" + uuid.uuid4().hex,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        print(response.read().decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
