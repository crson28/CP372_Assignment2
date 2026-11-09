"""
run_experiments.py
CP372 Assignment 2 - runs all the Part D tests automatically

For every loss rate and file size, this script starts the receiver,
runs the sender 5 times, and saves each result to a CSV file. At the end
it averages the 5 runs and prints the tables we need for the report
(transfer time, throughput and retransmissions).

How to run it (put it in the same folder as the sender/receiver files):
    python3 run_experiments.py                     # Stop-and-Wait, all tests
    python3 run_experiments.py --protocol gbn      # Go-Back-N, all tests

Useful options:
    --sizes 10KB 50KB 100KB    only test these file sizes
    --losses 0 0.1             only test these loss rates
    --runs 5                   tests per file size per loss rate
    --summary-only             don't run anything, just print the tables
                               from the results already saved

If the script is stopped part way (Ctrl+C), just run it again. It checks
the CSV and skips any tests that are already done.

Note for Go-Back-N: this script expects sender_gbn.py and receiver_gbn.py
to accept the same options as the Stop-and-Wait files
(--port, --loss, --outdir, --generate, --csv, --label).
"""

import argparse
import csv
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict

SIZES = ["10KB", "50KB", "100KB", "500KB", "1MB", "5MB", "10MB", "50MB", "100MB"]
LOSSES = ["0", "0.1", "0.2", "0.3"]


def size_in_bytes(text):
    text = text.upper()
    if text.endswith("KB"):
        return int(float(text[:-2]) * 1024)
    if text.endswith("MB"):
        return int(float(text[:-2]) * 1024 * 1024)
    return int(text)


def load_results(csv_path):
    """Read the CSV and return its rows (empty list if it doesn't exist yet)."""
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def count_done(rows, protocol, loss, size):
    """How many runs of this (loss, size) are already saved?"""
    return sum(1 for r in rows
               if r["protocol"] == protocol and r["label"] == loss
               and int(r["bytes"]) == size_in_bytes(size))


def run_tests(args):
    sender = f"sender_{args.protocol}.py"
    receiver = f"receiver_{args.protocol}.py"
    for f in (sender, receiver):
        if not os.path.exists(f):
            sys.exit(f"Can't find {f} -- run this script from the project folder.")

    outdir = f"received_{args.protocol}_test"

    for loss in args.losses:
        rows = load_results(args.csv)
        todo = [s for s in args.sizes
                if count_done(rows, args.protocol, loss, s) < args.runs]
        if not todo:
            print(f"loss {float(loss):.0%}: already done, skipping")
            continue

        # start the receiver for this loss rate
        print(f"\n=== {args.protocol}  loss {float(loss):.0%} ===")
        recv = subprocess.Popen(
            [sys.executable, receiver, "--port", str(args.port),
             "--loss", loss, "--outdir", outdir],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)  # give the receiver time to start listening

        try:
            for size in todo:
                done = count_done(load_results(args.csv), args.protocol, loss, size)
                for run in range(done + 1, args.runs + 1):
                    start = time.time()
                    result = subprocess.run(
                        [sys.executable, sender, "--generate", size,
                         "--port", str(args.port), "--csv", args.csv, "--label", loss],
                        capture_output=True, text=True)
                    took = time.time() - start
                    if result.returncode != 0:
                        print(f"  {size:>6} run {run}: FAILED")
                        print("   ", result.stdout.strip().splitlines()[-1:] or result.stderr)
                    else:
                        print(f"  {size:>6} run {run}/{args.runs}: {took:7.2f} s")
        finally:
            recv.terminate()
            recv.wait()
            shutil.rmtree(outdir, ignore_errors=True)  # received copies use lots of disk


def print_summary(args):
    rows = [r for r in load_results(args.csv) if r["protocol"] == args.protocol]
    if not rows:
        print("No results saved yet.")
        return

    # group the runs by (loss, size) and average them
    groups = defaultdict(list)
    for r in rows:
        groups[(r["label"], int(r["bytes"]))].append(r)

    def avg(loss, size, column):
        runs = groups.get((loss, size_in_bytes(size)))
        if not runs:
            return None
        return sum(float(r[column]) for r in runs) / len(runs)

    tables = [("Average transfer time (s)", "time_s", "{:.3f}"),
              ("Average throughput (bytes/s)", "throughput_Bps", "{:,.0f}"),
              ("Average retransmissions", "retransmissions", "{:.1f}")]

    summary_path = f"summary_{args.protocol}.csv"
    with open(summary_path, "w", newline="") as f:
        w = csv.writer(f)
        for title, column, fmt in tables:
            print(f"\n{args.protocol} -- {title}")
            header = ["Loss"] + SIZES
            print("  ".join(f"{h:>12}" for h in header))
            w.writerow([title])
            w.writerow(header)
            for loss in LOSSES:
                cells = []
                for size in SIZES:
                    value = avg(loss, size, column)
                    cells.append("-" if value is None else fmt.format(value))
                label = f"{float(loss):.0%}"
                print("  ".join(f"{c:>12}" for c in [label] + cells))
                w.writerow([label] + [c.replace(",", "") for c in cells])
            w.writerow([])
    print(f"\nTables also saved to {summary_path} (open it in Excel/Sheets for the report)")


def main():
    ap = argparse.ArgumentParser(description="Run the Part D experiments")
    ap.add_argument("--protocol", choices=["stopwait", "gbn"], default="stopwait")
    ap.add_argument("--sizes", nargs="+", default=SIZES)
    ap.add_argument("--losses", nargs="+", default=LOSSES)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--port", type=int, default=12500)
    ap.add_argument("--csv", default="results.csv")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    args.sizes = [s.upper() for s in args.sizes]
    for s in args.sizes:
        if s not in SIZES:
            sys.exit(f"Unknown size {s}. Choose from: {' '.join(SIZES)}")
    for loss in args.losses:
        if loss not in LOSSES:
            sys.exit(f"Unknown loss rate {loss}. Choose from: {' '.join(LOSSES)}")

    if not args.summary_only:
        try:
            run_tests(args)
        except KeyboardInterrupt:
            print("\nStopped. Run the script again to continue where it left off.")
    print_summary(args)


if __name__ == "__main__":
    main()