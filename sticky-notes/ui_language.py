"""Use only the translations bundled with this independent application."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'i18n'))
import ui_i18n as ui
