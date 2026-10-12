"""Generate explicitly offline V10 research snapshot."""
from v10.core import run
if __name__ == "__main__":
    print(run()["release_id"])
