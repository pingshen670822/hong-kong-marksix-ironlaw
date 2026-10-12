"""Isolated V10 runner; leaves original root data and V9 ledger untouched."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'v10_system'))
from v10.ci import main
if __name__=='__main__': raise SystemExit(main())
