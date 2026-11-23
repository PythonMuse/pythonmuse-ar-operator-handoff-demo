# Operator Guide: AR Aging Review

*One page. If something here doesn't match what you see, stop and escalate.*

## Before you run

- [ ] I have the approved AR open-items export from the ERP, for the as-of date I'm reviewing (for the demo: 2026-10-31).
- [ ] It is saved in the approved input folder (for the demo: `sample_data/`).
- [ ] It is named `AR_Open_Items_YYYY-MM-DD.csv`, with the as-of date in the name.
- [ ] I have the AR control balance for the same date from the general ledger (for the demo: 60,490.75).
- [ ] The run log (`output/run_log.csv`) and any earlier workpaper are closed in Excel.

## Run

1. Open **AR Review** (the desktop window) or the terminal launcher.
2. Enter the as-of date, choose the input file with **Browse** (rather than typing the path), enter the AR control balance and your name.
3. Click **Check file** and read every line. **STOP (red) = stop. WARN (amber) = read, then decide. PASS (green) = continue.**
4. Only when nothing is red, click **Run analysis**. If you change any field, check the file again.

## After the run: what I must check

- [ ] The run status says **CHECKS PASSED - READY FOR REVIEW**, and the aging total reconciles to the control balance (difference 0.00).
- [ ] The line count and customer count look right for the month (demo: 15 lines, 7 customers).
- [ ] Every row on the **Exceptions** sheet has a disposition in my words: credits, missing due dates, items over 90 days, customers above the threshold.
- [ ] On the **Detail** sheet, I spot-checked at least three *unflagged* lines from different buckets against the source report. (Demo tip: INV-10007 is exactly 90 days past due, one day short of the flag.)
- [ ] The **Run Info** sheet shows the as-of date, the input file's fingerprint, the rules version, and the code version.

A green check means the configured checks passed. It does **not** mean the accounting is correct. That judgment is the reviewer's, and I don't review my own run.

## Stop and escalate when

- Any check is red, or a check fails that I don't understand.
- The total doesn't reconcile.
- The output looks wrong even though every check passed.
- The window says the file differs from one already used for this as-of date.
- The window says a workpaper already exists but isn't in the run log. (If it only says the run log can't be used, close it in Excel and try again first.)
- I'm asked to change a rule, a threshold, or the file layout. Operators don't change rules; the maintainer does, after the rules owner approves.

**Escalate to:** the workflow maintainer (for the file, the checks, or the tool) and the AR reviewer (for the accounting).

## Where things go

- **Workpaper:** `output/<as-of date>/AR_Aging_Workpaper_<as-of date>-runNN.xlsx`. Each run gets a new file; nothing is overwritten.
- **Run log:** `output/run_log.csv`, one line per completed run.
- **Sign-off:** the reviewer completes *Reviewed by*, *Review date*, and *Reviewer conclusion* on the Run Info sheet, or in your team's usual review record.
