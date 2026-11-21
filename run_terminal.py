"""Start the guided terminal launcher: python run_terminal.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from ar_handoff.launcher import main  # noqa: E402

sys.exit(main())
