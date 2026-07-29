"""Make the 03-VETTING engine modules (norm_contracts, make_rankings_xlsx) importable."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
