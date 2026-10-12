"""V10 compatibility entry point; fail closed on update failure."""
from v10.core import run
if __name__ == "__main__":
    print(run(online=True)["release_id"])
