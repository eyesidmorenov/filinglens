import sys
from pathlib import Path

# Make "src" importable when pytest runs from etl/ or from the repository root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
