
"""
run_experiments.py
CP372 Assignment 2 - Automated Protocol Testing

Runs Stop-and-Wait and Go-Back-N experiments.

For each file size and loss rate, the script:
    1. Starts the receiver
    2. Runs the sender 5 times
    3. Verifies received files for GBN
    4. Saves results to CSV
    5. Prints average performance tables

How to run:
    python run_experiments.py --protocol gbn
    python run_experiments.py --protocol stopwait

Useful options:
    --sizes 10KB 50KB
    --losses 0 0.1
    --runs 5
    --summary-only

Completed trials are skipped when restarting.
"""

import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent

SIZES = [
    "10KB", "50KB", "100KB", "500KB",
    "1MB", "5MB", "10MB", "50MB", "100MB"
]

LOSSES = ["0", "0.1", "0.2", "0.3"]

FIELDS = [
    "protocol", "label", "bytes", "time_s",
    "throughput_Bps", "retransmissions"
]


def size_in_bytes(text):
    text = text.upper()

    if text.endswith("KB"):
        return int(float(text[:-2]) * 1024)

    if text.endswith("MB"):
        return int(float(text[:-2]) * 1024 * 1024)

    return int(text)


def create_file(size):
    folder = BASE / "test_files"
    folder.mkdir(exist_ok=True)

    filename = folder / f"test_{size}.bin"
    expected_size = size_in_bytes(size)

    if (filename.exists()
            and filename.stat().st_size == expected_size):
        return filename

    with open(filename, "wb") as file:
        remaining = expected_size

        while remaining > 0:
            amount = min(1024 * 1024, remaining)
            file.write(os.urandom(amount))
            remaining -= amount

    return filename


def sha256(path):
    digest = hashlib.sha256()

    with open(path, "rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024), b""
        ):
            digest.update(chunk)

    return digest.hexdigest()


def load_results(csv_path):
    if not os.path.exists(csv_path):
        return []

    with open(csv_path, newline="") as file:
        return list(csv.DictReader(file))


def count_done(rows, protocol, loss, size):
    return sum(
        1 for row in rows
        if row["protocol"] == protocol
        and row["label"] == loss
        and int(row["bytes"]) == size_in_bytes(size)
    )


def save_result(csv_path, row):
    needs_header = (
        not os.path.exists(csv_path)
        or os.path.getsize(csv_path) == 0
    )

    with open(csv_path, "a", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=FIELDS
        )

        if needs_header:
            writer.writeheader()

        writer.writerow(row)


def parse_gbn_output(output):
    values = {}

    names = {
        "Transfer time:": "time_s",
        "Throughput:": "throughput_Bps",
        "Retransmissions:": "retransmissions"
    }

    for line in output.splitlines():
        line = line.strip()

        for prefix, key in names.items():
            if line.startswith(prefix):
                number = line[len(prefix):].strip().split()[0]
                values[key] = float(number)

    for key in names.values():
        if key not in values:
            raise RuntimeError(
                f"GBN sender did not report {key}"
            )

    return values


def start_receiver(protocol, loss, port, outdir):
    command = [
        sys.executable,
        str(BASE / f"receiver_{protocol}.py"),
        "--port", str(port),
        "--loss", loss,
        "--outdir", str(outdir)
    ]

    process = subprocess.Popen(
        command,
        cwd=BASE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(0.5)

    if process.poll() is not None:
        raise RuntimeError(
            "Receiver failed to start. "
            "Check whether the port is already in use."
        )

    return process


def stop_receiver(process):
    if process.poll() is None:
        process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run_gbn(size, loss, args, outdir):
    filename = create_file(size)
    received = outdir / filename.name

    if received.exists():
        received.unlink()

    command = [
        sys.executable,
        str(BASE / "sender_gbn.py"),
        str(filename),
        "--port", str(args.port),
        "--window", str(args.window),
        "--timeout", str(args.timeout),
        "--loss-label", f"{float(loss):.0%}",
        "--csv", str(BASE / "gbn_sender_raw.csv")
    ]

    result = subprocess.run(
        command,
        cwd=BASE,
        capture_output=True,
        text=True,
        timeout=args.limit
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr or result.stdout
        )

    if not received.exists():
        raise RuntimeError("Received file is missing")

    if sha256(filename) != sha256(received):
        raise RuntimeError("File integrity check failed")

    return parse_gbn_output(result.stdout)


def run_tests(args):
    sender = BASE / f"sender_{args.protocol}.py"
    receiver = BASE / f"receiver_{args.protocol}.py"

    for path in (sender, receiver):
        if not path.exists():
            sys.exit(f"Missing file: {path.name}")

    outdir = BASE / f"received_{args.protocol}_test"
    outdir.mkdir(exist_ok=True)

    for loss in args.losses:
        rows = load_results(args.csv)

        todo = [
            size for size in args.sizes
            if count_done(
                rows, args.protocol, loss, size
            ) < args.runs
        ]

        if not todo:
            print(f"Loss {float(loss):.0%}: already done")
            continue

        print(
            f"\n=== {args.protocol.upper()} "
            f"LOSS {float(loss):.0%} ===",
            flush=True
        )

        recv = start_receiver(
            args.protocol, loss, args.port, outdir
        )

        try:
            for size in todo:
                rows = load_results(args.csv)

                done = count_done(
                    rows, args.protocol, loss, size
                )

                for trial in range(done + 1, args.runs + 1):
                    print(
                        f"{size:>6} | "
                        f"Loss {float(loss):.0%} | "
                        f"Trial {trial}/{args.runs}",
                        flush=True
                    )

                    if recv.poll() is not None:
                        raise RuntimeError(
                            "Receiver stopped unexpectedly"
                        )

                    if args.protocol == "gbn":
                        measurements = run_gbn(
                            size, loss, args, outdir
                        )

                        row = {
                            "protocol": "gbn",
                            "label": loss,
                            "bytes": size_in_bytes(size),
                            "time_s": measurements["time_s"],
                            "throughput_Bps":
                                measurements["throughput_Bps"],
                            "retransmissions":
                                int(measurements["retransmissions"])
                        }

                        save_result(args.csv, row)

                        print(
                            f"  PASS: "
                            f"{measurements['time_s']:.3f}s, "
                            f"{int(measurements['retransmissions'])} "
                            f"retransmissions",
                            flush=True
                        )

                    else:
                        # Stop-and-Wait sender generates
                        # the file and writes its own CSV row.
                        command = [
                            sys.executable,
                            str(sender),
                            "--generate", size,
                            "--port", str(args.port),
                            "--csv", args.csv,
                            "--label", loss
                        ]

                        result = subprocess.run(
                            command,
                            cwd=BASE,
                            capture_output=True,
                            text=True,
                            timeout=args.limit
                        )

                        if result.returncode != 0:
                            raise RuntimeError(
                                result.stderr or result.stdout
                            )

                        print("  PASS", flush=True)

        finally:
            stop_receiver(recv)
            shutil.rmtree(outdir, ignore_errors=True)


def print_summary(args):
    rows = [
        row for row in load_results(args.csv)
        if row["protocol"] == args.protocol
    ]

    if not rows:
        print("No results saved yet.")
        return

    groups = defaultdict(list)

    for row in rows:
        key = (row["label"], int(row["bytes"]))
        groups[key].append(row)

    def average(loss, size, column):
        values = groups.get(
            (loss, size_in_bytes(size)), []
        )

        if not values:
            return None

        return sum(
            float(row[column]) for row in values
        ) / len(values)

    tables = [
        ("Average transfer time (s)", "time_s", "{:.3f}"),
        ("Average throughput (bytes/s)",
         "throughput_Bps", "{:,.0f}"),
        ("Average retransmissions",
         "retransmissions", "{:.1f}")
    ]

    summary_path = BASE / f"summary_{args.protocol}.csv"

    with open(summary_path, "w", newline="") as file:
        writer = csv.writer(file)

        for title, column, fmt in tables:
            print(f"\n{args.protocol.upper()} - {title}")

            header = ["Loss"] + SIZES
            print("  ".join(f"{h:>12}" for h in header))

            writer.writerow([title])
            writer.writerow(header)

            for loss in LOSSES:
                cells = []

                for size in SIZES:
                    value = average(loss, size, column)

                    cells.append(
                        "-" if value is None
                        else fmt.format(value)
                    )

                label = f"{float(loss):.0%}"

                print(
                    "  ".join(
                        f"{c:>12}"
                        for c in [label] + cells
                    )
                )

                writer.writerow(
                    [label] +
                    [c.replace(",", "") for c in cells]
                )

            writer.writerow([])

    print(f"\nSummary saved: {summary_path}")


def main():
    parser = argparse.ArgumentParser(
        description="CP372 Part D experiments"
    )

    parser.add_argument(
        "--protocol",
        choices=["stopwait", "gbn"],
        default="stopwait"
    )

    parser.add_argument(
        "--sizes", nargs="+", default=SIZES
    )

    parser.add_argument(
        "--losses", nargs="+", default=LOSSES
    )

    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--port", type=int, default=12500)
    parser.add_argument("--window", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=0.2)
    parser.add_argument("--limit", type=int, default=3600)
    parser.add_argument("--csv", default="results.csv")
    parser.add_argument(
        "--summary-only", action="store_true"
    )

    args = parser.parse_args()

    args.sizes = [s.upper() for s in args.sizes]

    for size in args.sizes:
        if size not in SIZES:
            parser.error(f"Unknown size: {size}")

    for loss in args.losses:
        if loss not in LOSSES:
            parser.error(f"Unknown loss rate: {loss}")

    if args.runs < 1 or args.limit < 1:
        parser.error("--runs and --limit must be positive")

    if not args.summary_only:
        try:
            run_tests(args)
        except KeyboardInterrupt:
            print("\nStopped. Run again to resume.")
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            print(f"\nExperiment stopped: {error}")

    print_summary(args)


if __name__ == "__main__":
    main()
