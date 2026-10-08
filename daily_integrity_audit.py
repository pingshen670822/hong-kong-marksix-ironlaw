"""Compatibility integrity audit; only the v9 official-source audit is active."""

from v9.verify import verify


if __name__ == "__main__":
    import json

    print(json.dumps(verify(), ensure_ascii=False, indent=2))
