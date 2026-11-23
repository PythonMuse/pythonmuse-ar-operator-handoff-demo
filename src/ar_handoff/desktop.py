"""Small Tkinter desktop app for the AR aging review. Deliberately thin.

The operator picks the as-of date and the input file, enters the AR control
balance, clicks Check file, reads the results (red = stop, amber = read, then
decide, green = continue), and only then can click Run analysis. Changing any
field after a check switches Run off again until the file is re-checked.

No accounting logic lives here: the window only calls runner.check() and
runner.run(), exactly like the terminal launcher. Operators can't change rules
or run a corrected export from this window; those are maintainer actions.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog

from . import __version__
from . import runner
from .launcher import last_month_end

DEEP_NAVY = "#002639"
WARM_GLOW = "#F5D384"
OCEAN_TEAL = "#005F6F"
BRIGHT_TEAL = "#3ABFB9"
WHITE = "#FFFFFF"
STATUS_STYLE = {  # (label, background, foreground)
    "PASS": ("PASS", "#DCEFDB", DEEP_NAVY),
    "WARN": ("WARN", "#FFE9A8", DEEP_NAVY),
    "BLOCK": ("STOP", "#F6C9C9", DEEP_NAVY),
}
FONT = ("Segoe UI", 12)
FONT_BOLD = ("Segoe UI", 12, "bold")


class ARReviewApp:
    def __init__(self, root: tk.Tk, settings: runner.Settings):
        self.root = root
        self.settings = settings
        self.checked_ok = False
        self.last_outcome = None
        root.title("AR Aging Review")
        root.configure(bg=WHITE)

        head = tk.Frame(root, bg=DEEP_NAVY, padx=16, pady=10)
        head.pack(fill="x")
        tk.Label(head, text="AR Aging Review", bg=DEEP_NAVY, fg=WHITE,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(head, text=f"Approved workflow v{__version__}   |   "
                            f"rules {settings.rules.version}",
                 bg=DEEP_NAVY, fg=WARM_GLOW, font=FONT).pack(anchor="w")

        form = tk.Frame(root, bg=WHITE, padx=16, pady=12)
        form.pack(fill="x")
        self.as_of = tk.StringVar(value=last_month_end().isoformat())
        self.input_path = tk.StringVar()
        self.control = tk.StringVar()
        self.prepared_by = tk.StringVar()
        fields = [("As-of date (YYYY-MM-DD)", self.as_of),
                  ("Input file", self.input_path),
                  ("AR control balance (GL)", self.control),
                  ("Prepared by", self.prepared_by)]
        for r, (text, var) in enumerate(fields):
            tk.Label(form, text=text, bg=WHITE, fg=DEEP_NAVY, font=FONT_BOLD,
                     anchor="w").grid(row=r, column=0, sticky="w", pady=4)
            tk.Entry(form, textvariable=var, font=FONT, width=52).grid(
                row=r, column=1, sticky="we", padx=(8, 0), pady=4)
            var.trace_add("write", self._invalidate)
        tk.Button(form, text="Browse...", font=FONT, command=self.browse).grid(
            row=1, column=2, padx=(8, 0))

        buttons = tk.Frame(root, bg=WHITE, padx=16)
        buttons.pack(fill="x")
        self.check_btn = tk.Button(buttons, text="Check file", font=FONT_BOLD,
                                   bg=BRIGHT_TEAL, fg=DEEP_NAVY, width=14,
                                   command=self.on_check)
        self.check_btn.pack(side="left")
        self.run_btn = tk.Button(buttons, text="Run analysis", font=FONT_BOLD,
                                 bg=DEEP_NAVY, fg=WHITE, width=14,
                                 state="disabled", command=self.on_run)
        self.run_btn.pack(side="left", padx=8)
        tk.Button(buttons, text="Open output folder", font=FONT,
                  command=self.open_output).pack(side="left")

        self.panel = tk.Text(root, font=FONT, height=20, width=90, wrap="word",
                             bg=WHITE, fg=DEEP_NAVY, relief="flat", padx=16, pady=10)
        self.panel.pack(fill="both", expand=True)
        for status, (_, bg, fg) in STATUS_STYLE.items():
            self.panel.tag_configure(status, background=bg, foreground=fg,
                                     font=FONT_BOLD)
        self.panel.tag_configure("bold", font=FONT_BOLD)
        self.panel.tag_configure("note", foreground=OCEAN_TEAL,
                                 font=("Segoe UI", 12, "italic"))
        self._write([("Pick the as-of date and the input file, then click "
                      "Check file.", None)])

        tk.Label(root, text=runner.GREEN_CHECK_NOTE, bg=WHITE, fg=OCEAN_TEAL,
                 font=("Segoe UI", 11, "italic"), wraplength=820,
                 justify="left", padx=16, pady=8).pack(anchor="w")

    # -- helpers ---------------------------------------------------------------
    def _write(self, parts):
        self.panel.configure(state="normal")
        self.panel.delete("1.0", "end")
        for text, tag in parts:
            self.panel.insert("end", text, tag or ())
        self.panel.configure(state="disabled")

    def _show_error(self, exc):
        if isinstance(exc, runner.RunError):
            message = str(exc)
        else:
            message = (f"Something went wrong: {exc}. Nothing was run. "
                       f"Escalate to the maintainer.")
        self._write([(" STOP ", "BLOCK"), (f"  {message}\n", None)])

    def _invalidate(self, *_):
        self.checked_ok = False
        self.run_btn.configure(state="disabled")

    def _inputs(self):
        as_of = runner.parse_as_of(self.as_of.get())
        control = runner.parse_amount(self.control.get())
        return as_of, self.input_path.get().strip(), control

    def browse(self):
        path = filedialog.askopenfilename(
            title="Select the AR open-items export",
            initialdir=str(self.settings.approved_root),
            filetypes=[("CSV files", "*.csv")])
        if path:
            self.input_path.set(path)

    def open_output(self):
        folder = self.settings.output_dir
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(folder)  # opens Explorer on this one folder only
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open",
                            str(folder)], check=False)

    # -- actions ---------------------------------------------------------------
    def on_check(self):
        try:
            as_of, path, control = self._inputs()
        except ValueError as exc:
            self._write([("STOP  ", "BLOCK"), (f"{exc}\n", None)])
            self._invalidate()
            return None
        try:
            report = runner.check(self.settings, path, as_of, control)
        except Exception as exc:  # show it; never fail silently in the window
            self._show_error(exc)
            return None
        parts = []
        for c in report.checks:
            label = STATUS_STYLE[c.status][0]
            parts += [(f" {label} ", c.status), (f"  {c.name}: ", "bold"),
                      (f"{c.message}\n", None)]
        if report.can_run:
            parts.append(("\nChecks complete. Read any WARN items, then click "
                          "Run analysis.", "note"))
        else:
            parts.append(("\nStop: fix the items marked STOP, or escalate. "
                          "Nothing can run yet.", "note"))
        self._write(parts)
        self.checked_ok = report.can_run
        self.run_btn.configure(state="normal" if report.can_run else "disabled")
        return report

    def on_run(self):
        if not self.checked_ok:
            return None
        try:
            as_of, path, control = self._inputs()
            outcome = runner.run(self.settings, path, as_of, control,
                                 self.prepared_by.get())
        except Exception as exc:  # show it; never fail silently in the window
            self._invalidate()
            self._show_error(exc)
            return None
        self.last_outcome = outcome
        self._invalidate()
        if outcome.workpaper is None:
            self._write([(" STOP ", "BLOCK"),
                         ("  The file changed after it was checked. Nothing was "
                          "run. Check it again.\n", None)])
            return outcome
        r, rec = outcome.result, outcome.recon
        tag = "PASS" if outcome.exit_code == runner.EXIT_OK else "BLOCK"
        lines = [(f" {outcome.status} ", tag), ("\n\n", None),
                 (f"Run {outcome.run_id}\n", "bold"),
                 (f"Aging total:      {r.total:,.2f}\n", None)]
        if rec.control_total is not None:
            lines += [(f"Control balance:  {rec.control_total:,.2f}\n", None),
                      (f"Difference:       {rec.difference:,.2f}\n", None)]
        lines += [(f"Lines {r.row_count}, customers {r.customer_count}, "
                   f"exceptions to review {len(r.exceptions)}\n", None),
                  (f"Workpaper: {outcome.workpaper}\n", None),
                  ("\nNext: open the workpaper, give each exception a "
                   "disposition, and spot-check unflagged lines on the Detail "
                   "sheet.", "note")]
        self._write(lines)
        return outcome


def main(argv=None) -> int:
    try:
        settings = runner.load_settings()
    except Exception as exc:
        print(f"Cannot start: {exc}\nEscalate to the maintainer.")
        return runner.EXIT_ERROR
    root = tk.Tk()
    ARReviewApp(root, settings)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
