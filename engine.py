"""Compatibility entry point for the independent, official-source v9 engine.

The legacy model is intentionally unavailable from this active module.
"""

from v9.pipeline import run


if __name__ == "__main__":
    import json

    print(json.dumps(run(), ensure_ascii=False, indent=2))
