"""
sender_stopwait.py
CP372 Assignment 2 - Stop-and-Wait sender (Parts A and B)

This program sends a file to the receiver using UDP. UDP doesn't make sure
packets arrive, so we add our own reliability: every packet gets a sequence
number, and the sender waits for an ACK before sending the next one. If no
ACK comes back before the timer runs out, the packet is sent again.

How to run it (start receiver_stopwait.py first):
    python3 sender_stopwait.py myfile.txt        # send a real file
    python3 sender_stopwait.py --generate 1MB    # send random data instead

Other options you can add:
    --port 12000      port the receiver is listening on
    --timeout 0.05    how long to wait for an ACK (in seconds)
    --chunk 4096      how many bytes of the file go in each packet
    --csv results.csv save the results to a CSV file for Part D
    --verbose         print every packet that is sent or received

What the sender does, step by step:
  1. Reads the file (or makes random data)
  2. Sends a START packet so the receiver knows a file is coming
  3. Splits the file into DATA packets
  4. Sends one packet and starts the timer
  5. Waits for the ACK for that packet
  6. If the timer runs out, sends the same packet again
  7. Repeats until every packet has been ACKed
  8. Sends an END packet to say the transfer is done

At the end it prints the transfer time, throughput and number of
retransmissions, which we need for Part D.

The packet format is the same as in receiver_stopwait.py (see the
comment at the top of that file).
"""

import argparse
import csv
import os
import socket
import struct
import sys
import time

# ---------------------------------------------------------------- packet format
HEADER_FMT = "!BIIH"                      # type, seq, ack, payload length
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 11 bytes

TYPE_START = 1
TYPE_DATA = 2
TYPE_ACK = 3
TYPE_END = 4
TYPE_NAMES = {TYPE_START: "START", TYPE_DATA: "DATA", TYPE_ACK: "ACK", TYPE_END: "END"}

MAX_CONSECUTIVE_TIMEOUTS = 500   # give up if the receiver seems to be gone


def make_packet(ptype, seq=0, ack=0, payload=b""):
    return struct.pack(HEADER_FMT, ptype, seq, ack, len(payload)) + payload


def parse_packet(raw):
    if len(raw) < HEADER_SIZE:
        return None
    ptype, seq, ack, length = struct.unpack(HEADER_FMT, raw[:HEADER_SIZE])
    payload = raw[HEADER_SIZE:HEADER_SIZE + length]
    if len(payload) != length or ptype not in TYPE_NAMES:
        return None
    return ptype, seq, ack, payload


def parse_size(text):
    """'10KB' -> 10240, '1MB' -> 1048576, '500' -> 500"""
    text = text.strip().upper()
    for suffix, mult in (("KB", 1024), ("MB", 1024 ** 2), ("GB", 1024 ** 3),
                         ("K", 1024), ("M", 1024 ** 2), ("B", 1)):
        if text.endswith(suffix):
            return int(float(text[:-len(suffix)]) * mult)
    return int(text)


# ---------------------------------------------------------------- sender
class StopAndWaitSender:
    def __init__(self, addr, timeout, verbose=False):
        self.addr = addr
        self.timeout = timeout
        self.verbose = verbose
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.retransmissions = 0
        self.packets_sent = 0

    def send_reliable(self, ptype, seq, payload=b""):
        """Send one packet and block until its ACK arrives (retransmitting on timeout)."""
        packet = make_packet(ptype, seq=seq, payload=payload)
        timeouts_in_a_row = 0

        self.sock.sendto(packet, self.addr)
        self.packets_sent += 1
        deadline = time.monotonic() + self.timeout          # start timer
        if self.verbose:
            print(f"  -> {TYPE_NAMES[ptype]} seq={seq}")

        while True:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                self.sock.settimeout(remaining)
                try:
                    raw, _ = self.sock.recvfrom(65535)
                    pkt = parse_packet(raw)
                    if pkt and pkt[0] == TYPE_ACK and pkt[2] == seq:
                        if self.verbose:
                            print(f"  <- ACK {seq}")
                        return                               # done with this packet
                    # stale/duplicate ACK for an older packet: ignore it and
                    # keep waiting with the SAME timer (don't restart it)
                    continue
                except socket.timeout:
                    pass

            # ---- timeout: retransmit and restart timer
            timeouts_in_a_row += 1
            if timeouts_in_a_row > MAX_CONSECUTIVE_TIMEOUTS:
                raise ConnectionError(f"no ACK for seq {seq} after {MAX_CONSECUTIVE_TIMEOUTS} "
                                      "retransmissions -- is the receiver running?")
            self.sock.sendto(packet, self.addr)
            self.packets_sent += 1
            self.retransmissions += 1
            deadline = time.monotonic() + self.timeout
            if self.verbose:
                print(f"  !! timeout, retransmit {TYPE_NAMES[ptype]} seq={seq}")

    def send_file(self, filename, data, chunk):
        # 2. notify receiver that a file is coming (seq 0)
        self.send_reliable(TYPE_START, 0, f"{filename}|{len(data)}".encode("utf-8"))

        # 3-8. DATA packets, seq 1..N, one at a time
        seq = 1
        for offset in range(0, len(data), chunk):
            self.send_reliable(TYPE_DATA, seq, data[offset:offset + chunk])
            seq += 1

        # 9. completion of file transfer
        self.send_reliable(TYPE_END, seq)
        return seq - 1   # number of DATA packets


def main():
    ap = argparse.ArgumentParser(description="Stop-and-Wait UDP sender")
    ap.add_argument("file", nargs="?", help="file to send (omit when using --generate)")
    ap.add_argument("--generate", metavar="SIZE",
                    help="send random content of this size instead of a file, e.g. 10KB, 1MB")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=12000)
    ap.add_argument("--timeout", type=float, default=0.05, help="retransmission timeout (s)")
    ap.add_argument("--chunk", type=int, default=4096,
                    help="payload bytes per packet (max 8192 on macOS)")
    ap.add_argument("--csv", help="append the results as a row to this CSV file (Part D)")
    ap.add_argument("--label", default="", help="free-text tag stored in the CSV, e.g. loss rate")
    ap.add_argument("--verbose", action="store_true", help="print every packet event")
    args = ap.parse_args()

    # 1. read file or generate content
    if args.generate:
        size = parse_size(args.generate)
        data = os.urandom(size)
        filename = f"generated_{args.generate.upper()}.bin"
    elif args.file:
        with open(args.file, "rb") as f:
            data = f.read()
        filename = os.path.basename(args.file)
    else:
        ap.error("give a file name or --generate SIZE")

    sender = StopAndWaitSender((args.host, args.port), args.timeout, args.verbose)
    print(f"[sender] sending '{filename}' ({len(data)} bytes) to {args.host}:{args.port} "
          f"chunk={args.chunk} timeout={args.timeout}s")

    start = time.perf_counter()
    try:
        n_packets = sender.send_file(filename, data, args.chunk)
    except ConnectionError as e:
        print(f"[sender] FAILED: {e}")
        sys.exit(1)
    elapsed = time.perf_counter() - start
    throughput = len(data) / elapsed if elapsed > 0 else float("inf")

    print(f"[sender] done: {n_packets} data packets, "
          f"{sender.packets_sent} packets sent in total")
    print(f"  transfer time   : {elapsed:.4f} s")
    print(f"  throughput      : {throughput:,.0f} bytes/s")
    print(f"  retransmissions : {sender.retransmissions}")

    if args.csv:
        new_file = not os.path.exists(args.csv)
        with open(args.csv, "a", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["protocol", "label", "file", "bytes", "chunk", "timeout",
                            "time_s", "throughput_Bps", "retransmissions", "packets_sent"])
            w.writerow(["stopwait", args.label, filename, len(data), args.chunk, args.timeout,
                        f"{elapsed:.6f}", f"{throughput:.2f}", sender.retransmissions,
                        sender.packets_sent])


if __name__ == "__main__":
    main()