"""Refresh official HKJC results and regenerate the v9 report."""

from v9.pipeline import run


if __name__ == "__main__":
    import json

    print(json.dumps(run(), ensure_ascii=False, indent=2))
