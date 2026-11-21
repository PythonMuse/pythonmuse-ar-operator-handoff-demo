"""AR aging review: a small, tested demo of handing a workflow to an operator.

Part of a PythonMuse Lab. The modules are deliberately separate:

- config.py     loads the approved rules (outside the code and the interface)
- validate.py   the input contract: what blocks a run and what only warns
- engine.py     the aging calculation and reconciliation, no interface code
- workpaper.py  the Excel workpaper with run metadata
- runlog.py     the append-only run log (the output manifest)
- runner.py     check, then run: the only module the interfaces call
- launcher.py   guided terminal interface (thin)
- desktop.py    Tkinter desktop interface (thin)

No network calls and no AI model calls happen at runtime.
"""

__version__ = "1.0.0"
