"""
receiver_stopwait.py
CP372 Assignment 2 - Stop-and-Wait receiver (Parts A and B)

This program waits for packets from the sender and saves the file.
It only accepts the packet it's expecting next. For every packet it
accepts, it sends back an ACK. If a packet is a duplicate (the sender
sent it again because our ACK got lost), we don't save it twice, we
just send the ACK again.

For Part B, the receiver can randomly drop packets to pretend the
network lost them. Use --loss to set how often (0.1 = 10%).

How to run it (start this before the sender):
    python3 receiver_stopwait.py
    python3 receiver_stopwait.py --loss 0.2      # drop 20% of packets

Other options:
    --port 12000        port to listen on (must match the sender)
    --outdir received   folder where received files are saved
    --verbose           print every packet that comes in or goes out

The receiver keeps running after a file is done, so you can send
lots of files in a row for testing. Press Ctrl+C to stop it.

Our packet format:
Every packet starts with an 11-byte header, and the file data
(the payload) comes after it.

    +--------+-------------+-------------+-------------+---------------+
    | Type   | Seq Number  | ACK Number  | Length      | Payload       |
    | 1 byte | 4 bytes     | 4 bytes     | 2 bytes     | Length bytes  |
    +--------+-------------+-------------+-------------+---------------+

Packet types:
    START (1)  tells the receiver a file is coming. The payload holds the
               file name and size, like "notes.txt|5000"
    DATA  (2)  one piece of the file
    ACK   (3)  sent back by the receiver. The ACK Number says which
               packet it's acknowledging
    END   (4)  tells the receiver the whole file has been sent

Sequence numbers:
    START is 0, the DATA packets are 1, 2, 3 ... N, and END is N+1.
"""

import argparse
import os
import random
import socket
import struct

# ---------------------------------------------------------------- packet format
HEADER_FMT = "!BIIH"                      # type, seq, ack, payload length
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 11 bytes

TYPE_START = 1
TYPE_DATA = 2
TYPE_ACK = 3
TYPE_END = 4
TYPE_NAMES = {TYPE_START: "START", TYPE_DATA: "DATA", TYPE_ACK: "ACK", TYPE_END: "END"}


def make_packet(ptype, seq=0, ack=0, payload=b""):
    return struct.pack(HEADER_FMT, ptype, seq, ack, len(payload)) + payload


def parse_packet(raw):
    """Return (type, seq, ack, payload) or None if the packet is malformed."""
    if len(raw) < HEADER_SIZE:
        return None
    ptype, seq, ack, length = struct.unpack(HEADER_FMT, raw[:HEADER_SIZE])
    payload = raw[HEADER_SIZE:HEADER_SIZE + length]
    if len(payload) != length or ptype not in TYPE_NAMES:
        return None
    return ptype, seq, ack, payload


# ---------------------------------------------------------------- receiver
def main():
    ap = argparse.ArgumentParser(description="Stop-and-Wait UDP receiver")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=12000)
    ap.add_argument("--loss", type=float, default=0.0,
                    help="probability of dropping each incoming packet (0.0-1.0), Part B")
    ap.add_argument("--outdir", default="received", help="folder for received files")
    ap.add_argument("--verbose", action="store_true", help="print every packet event")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    print(f"[receiver] listening on {args.host}:{args.port}  loss={args.loss:.0%}")

    # Transfer state
    active = False      # True between START and END
    expected = 0        # next in-order sequence number we will accept
    last_ack = None     # seq of last in-order packet ACKed (re-sent for duplicates)
    outfile = None
    filename = None
    filesize = 0
    received_bytes = 0
    dropped = 0

    def send_ack(addr, seq):
        sock.sendto(make_packet(TYPE_ACK, ack=seq), addr)
        if args.verbose:
            print(f"  -> ACK {seq}")

    try:
        while True:
            raw, addr = sock.recvfrom(65535)

            # ---- Part B: simulated packet loss (drop before any processing)
            if random.random() < args.loss:
                dropped += 1
                if args.verbose:
                    print("  xx dropped incoming packet")
                continue

            pkt = parse_packet(raw)
            if pkt is None:
                continue                          # malformed -> ignore
            ptype, seq, _ack, payload = pkt
            if args.verbose:
                print(f"  <- {TYPE_NAMES[ptype]} seq={seq} len={len(payload)}")

            # ---- New transfer: START with seq 0 while idle
            if ptype == TYPE_START and seq == 0 and not active:
                name, size = payload.decode("utf-8").rsplit("|", 1)
                filename = os.path.basename(name)       # strip any path
                filesize = int(size)
                outfile = open(os.path.join(args.outdir, filename), "wb")
                active = True
                received_bytes = 0
                dropped = 0
                expected = 1
                last_ack = 0
                print(f"[receiver] START  '{filename}' ({filesize} bytes) from {addr[0]}:{addr[1]}")
                send_ack(addr, 0)
                continue

            # ---- In-order packet of the current transfer
            if active and seq == expected:
                if ptype == TYPE_DATA:
                    outfile.write(payload)
                    received_bytes += len(payload)
                    send_ack(addr, seq)
                    last_ack = seq
                    expected += 1
                elif ptype == TYPE_END:
                    outfile.close()
                    outfile = None
                    active = False
                    send_ack(addr, seq)
                    last_ack = seq
                    expected += 1
                    status = "OK" if received_bytes == filesize else "SIZE MISMATCH"
                    print(f"[receiver] END    '{filename}' saved {received_bytes}/{filesize} bytes "
                          f"[{status}]  packets dropped by loss sim: {dropped}")
                continue

            # ---- Duplicate or out-of-order packet: ignore its content, but
            # re-ACK the last in-order packet so the sender can recover if our
            # previous ACK was lost (rdt 3.0 behaviour).
            if last_ack is not None and seq < expected:
                send_ack(addr, seq)
            # anything else (e.g. seq > expected) is simply ignored
    except KeyboardInterrupt:
        print("\n[receiver] stopped")
    finally:
        if outfile:
            outfile.close()
        sock.close()


if __name__ == "__main__":
    main()