"""Audit the official-source v9 data, forecast ledger and cloud mirrors."""

from v9.verify import verify


if __name__ == "__main__":
    import json

    print(json.dumps(verify(), ensure_ascii=False, indent=2))
