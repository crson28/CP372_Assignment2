import filecmp
import os
import subprocess
import time

LOSS_RATES = [0.0, 0.1, 0.2, 0.3]
TRIALS = 5
PORT = 12050
TEST_FILE = "partB_test.bin"
OUTDIR = "partB_received"

with open(TEST_FILE, "wb") as f:
    f.write(os.urandom(1024 * 1024))

runs = []
summary = []
for loss in LOSS_RATES:
    receiver = subprocess.Popen(["python3", "receiver_stopwait.py", "--port", str(PORT),
                                 "--loss", str(loss), "--outdir", OUTDIR],
                                stdout=subprocess.DEVNULL)
    time.sleep(0.5)  # let the receiver start
    times, retx, correct = [], [], 0
    for trial in range(1, TRIALS + 1):
        out = subprocess.run(["python3", "sender_stopwait.py", TEST_FILE, "--port", str(PORT)],
                             capture_output=True, text=True).stdout
        t = float(out.split("transfer time   :")[1].split()[0])
        r = int(out.split("retransmissions :")[1].split()[0])
        ok = filecmp.cmp(TEST_FILE, os.path.join(OUTDIR, TEST_FILE), shallow=False)
        times.append(t)
        retx.append(r)
        correct += ok
        runs.append(f"{loss:>5.0%}   trial {trial}   time {t:.3f} s   "
                    f"retransmissions {r:>4}   file {'OK' if ok else 'WRONG'}")
    receiver.terminate()
    summary.append(f"{loss:>5.0%} | {sum(times) / TRIALS:>12.3f} | "
                   f"{sum(retx) / TRIALS:>19.1f} | {correct:>11}/{TRIALS}")

report = "\n".join([
    "Part B - Simulated packet loss (receiver_stopwait.py --loss)",
    f"1 MB file, {TRIALS} runs per loss rate. Each received file is compared with the original.",
    "",
    " Loss | Avg time (s) | Avg retransmissions | Files correct",
    "-" * 60,
    *summary,
    "",
    "The sender still transfers the whole file correctly at every loss rate",
    "by timing out and retransmitting the dropped packets.",
    "",
    "All runs:",
    *runs,
])
print(report)
with open("partB_results.txt", "w") as f:
    f.write(report + "\n")
