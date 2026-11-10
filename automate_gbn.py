
"""
automate_gbn.py
CP372 Assignment 2 - Automated Go-Back-N Testing

Runs Go-Back-N file transfer experiments automatically.

File sizes:
    10KB, 50KB, 100KB, 500KB,
    1MB, 5MB, 10MB, 50MB, 100MB

Packet loss rates:
    0%, 10%, 20%, 30%

Five trials per configuration:
    9 file sizes x 4 loss rates x 5 trials = 180 tests

Features:
    - Generates test files automatically
    - Starts and stops the UDP receiver
    - Runs the sender for each experiment
    - Verifies received files using SHA-256
    - Records individual trial results
    - Calculates average performance metrics
    - Resumes completed trials after interruption

How to run:
    python automate_gbn.py

Stop any manually running receiver before starting.
"""

import csv
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

# ------------------------------------------------ Configuration

BASE_DIR = Path(__file__).resolve().parent

SENDER = BASE_DIR / "sender_gbn.py"
RECEIVER = BASE_DIR / "receiver_gbn.py"

TEST_DIR = BASE_DIR / "test_files"
OUTPUT_DIR = BASE_DIR / "received_gbn"

RESULTS_FILE = BASE_DIR / "gbn_automation_metrics.csv"
AVERAGES_FILE = BASE_DIR / "gbn_averages.csv"

FILE_SIZES = {
    "10KB": 10 * 1024,
    "50KB": 50 * 1024,
    "100KB": 100 * 1024,
    "500KB": 500 * 1024,
    "1MB": 1024 * 1024,
    "5MB": 5 * 1024 * 1024,
    "10MB": 10 * 1024 * 1024,
    "50MB": 50 * 1024 * 1024,
    "100MB": 100 * 1024 * 1024
}

LOSS_RATES = [0.0, 0.10, 0.20, 0.30]

TRIALS = 5
WINDOW_SIZE = 4
TIMEOUT = 0.05
PORT = 12001

TRANSFER_LIMIT = 3600

TEST_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


# ------------------------------------------------ Generate files

def create_test_files():
    print("\nGenerating test files...")

    for name, size in FILE_SIZES.items():
        path = TEST_DIR / f"test_{name}.bin"

        if path.exists() and path.stat().st_size == size:
            print(f"  {name}: already exists")
            continue

        with open(path, "wb") as file:
            remaining = size

            while remaining > 0:
                chunk_size = min(1024 * 1024, remaining)
                file.write(os.urandom(chunk_size))
                remaining -= chunk_size

        print(f"  Created {name}")

    print("Test files ready.\n")


# ------------------------------------------------ SHA-256 verification

def file_hash(path):
    sha = hashlib.sha256()

    with open(path, "rb") as file:
        while True:
            chunk = file.read(1024 * 1024)

            if not chunk:
                break

            sha.update(chunk)

    return sha.hexdigest()


def verify_file(original, received):
    if not received.exists():
        return False

    if original.stat().st_size != received.stat().st_size:
        return False

    return file_hash(original) == file_hash(received)


# ------------------------------------------------ CSV functions

FIELDS = [
    "file_size",
    "file_size_bytes",
    "loss_rate",
    "trial",
    "transfer_time_s",
    "throughput_Bps",
    "retransmissions",
    "timeouts",
    "transmitted_bytes",
    "payload_efficiency"
]


def read_results():
    if not RESULTS_FILE.exists():
        return []

    with open(RESULTS_FILE, newline="") as file:
        return list(csv.DictReader(file))


def append_result(row):
    write_header = (
        not RESULTS_FILE.exists()
        or RESULTS_FILE.stat().st_size == 0
    )

    with open(RESULTS_FILE, "a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)

        if write_header:
            writer.writeheader()

        writer.writerow(row)


def save_averages():
    rows = read_results()
    averages = []

    for name, size in FILE_SIZES.items():
        for loss in LOSS_RATES:
            label = f"{loss:.0%}"

            matching = [
                row for row in rows
                if row["file_size"] == name
                and row["loss_rate"] == label
            ]

            if not matching:
                continue

            count = len(matching)

            def avg(column):
                return sum(
                    float(row[column]) for row in matching
                ) / count

            averages.append({
                "file_size": name,
                "file_size_bytes": size,
                "loss_rate": label,
                "trials": count,
                "avg_transfer_time_s": avg("transfer_time_s"),
                "avg_throughput_Bps": avg("throughput_Bps"),
                "avg_retransmissions": avg("retransmissions"),
                "avg_timeouts": avg("timeouts"),
                "avg_payload_efficiency": avg("payload_efficiency")
            })

    if not averages:
        return

    with open(AVERAGES_FILE, "w", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=averages[0].keys()
        )

        writer.writeheader()
        writer.writerows(averages)


# ------------------------------------------------ Receiver management

def start_receiver(loss):
    command = [
        sys.executable,
        str(RECEIVER),
        "--host", "127.0.0.1",
        "--port", str(PORT),
        "--loss", str(loss),
        "--outdir", str(OUTPUT_DIR)
    ]

    process = subprocess.Popen(
        command,
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(0.5)

    if process.poll() is not None:
        raise RuntimeError(
            "Receiver failed to start. Check whether port 12001 is in use."
        )

    return process


def stop_receiver(process):
    if process.poll() is not None:
        return

    process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


# ------------------------------------------------ Sender output parsing

def parse_sender_results(output):
    values = {}

    labels = {
        "Transfer time:": "transfer_time_s",
        "Throughput:": "throughput_Bps",
        "Retransmissions:": "retransmissions",
        "Timeouts:": "timeouts",
        "Payload efficiency:": "payload_efficiency"
    }

    for line in output.splitlines():
        line = line.strip()

        for prefix, key in labels.items():
            if line.startswith(prefix):
                value = line[len(prefix):].strip().split()[0]

                if key == "payload_efficiency":
                    values[key] = float(value.rstrip("%")) / 100
                else:
                    values[key] = float(value)

    required = [
        "transfer_time_s",
        "throughput_Bps",
        "retransmissions",
        "timeouts",
        "payload_efficiency"
    ]

    for key in required:
        if key not in values:
            raise RuntimeError(
                f"Missing sender measurement: {key}"
            )

    return values


# ------------------------------------------------ Run one trial

def run_trial(filename, loss, trial):
    received_file = OUTPUT_DIR / filename.name

    # Remove old output so verification cannot use stale data
    if received_file.exists():
        received_file.unlink()

    receiver = start_receiver(loss)

    try:
        command = [
            sys.executable,
            str(SENDER),
            str(filename),
            "--host", "127.0.0.1",
            "--port", str(PORT),
            "--window", str(WINDOW_SIZE),
            "--timeout", str(TIMEOUT),
            "--loss-label", f"{loss:.0%}",
            "--csv", str(BASE_DIR / "gbn_sender_raw.csv")
        ]

        result = subprocess.run(
            command,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=TRANSFER_LIMIT
        )

        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            raise RuntimeError("Sender failed")

        if not verify_file(filename, received_file):
            raise RuntimeError(
                f"SHA-256 verification failed: {filename.name}"
            )

        measurements = parse_sender_results(result.stdout)

        return measurements

    finally:
        stop_receiver(receiver)


# ------------------------------------------------ Main

def main():
    print("=" * 55)
    print("GO-BACK-N AUTOMATED TESTING")
    print("=" * 55)

    create_test_files()

    completed = {
        (
            row["file_size"],
            row["loss_rate"],
            int(row["trial"])
        )
        for row in read_results()
    }

    total = len(FILE_SIZES) * len(LOSS_RATES) * TRIALS

    print(f"Total experiments: {total}")
    print(f"Already completed: {len(completed)}")
    print(f"Remaining: {total - len(completed)}")

    progress = len(completed)

    for name, size in FILE_SIZES.items():
        filename = TEST_DIR / f"test_{name}.bin"

        for loss in LOSS_RATES:
            label = f"{loss:.0%}"

            for trial in range(1, TRIALS + 1):
                key = (name, label, trial)

                if key in completed:
                    continue

                print(
                    f"[{progress + 1}/{total}] "
                    f"{name} | Loss {label} | Trial {trial}",
                    flush=True
                )

                measurements = run_trial(
                    filename, loss, trial
                )

                row = {
                    "file_size": name,
                    "file_size_bytes": size,
                    "loss_rate": label,
                    "trial": trial,
                    "transfer_time_s":
                        measurements["transfer_time_s"],
                    "throughput_Bps":
                        measurements["throughput_Bps"],
                    "retransmissions":
                        int(measurements["retransmissions"]),
                    "timeouts":
                        int(measurements["timeouts"]),
                    "transmitted_bytes": "",
                    "payload_efficiency":
                        measurements["payload_efficiency"]
                }

                append_result(row)
                save_averages()

                completed.add(key)
                progress += 1

                print(
                    f"  PASS - "
                    f"{measurements['transfer_time_s']:.4f}s, "
                    f"{int(measurements['retransmissions'])} retransmissions",
                    flush=True
                )

    print("\nAll 180 experiments completed!")
    print(f"Results: {RESULTS_FILE}")
    print(f"Averages: {AVERAGES_FILE}")


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\nTesting interrupted. Run again to resume.")

    except Exception as error:
        print(f"\nERROR: {error}")
        sys.exit(1)
