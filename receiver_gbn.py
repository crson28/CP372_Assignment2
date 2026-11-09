"""
sender_gbn.py
CP372 Assignment 2 - Go-Back-N Sender

This program transfers files using UDP and the Go-Back-N
sliding window protocol.

The sender divides a file into packets and sends multiple
packets without waiting for individual acknowledgments.

It maintains:
    base        - oldest unacknowledged packet
    nextseqnum  - next packet to send
    window_size - maximum outstanding packets

When an ACK is received, the sender slides its window
forward. If a timeout occurs, all unacknowledged packets
in the window are retransmitted.

The sender also measures transfer time, throughput,
retransmissions, and protocol efficiency. Results are
saved to a CSV file for performance analysis.

How to run (start the receiver first):
    python sender_gbn.py test_10kb.bin

Specify a window size:
    python sender_gbn.py test_10kb.bin --window 4

Run with a loss-rate label:
    python sender_gbn.py test_10kb.bin --window 4 --loss-label 10%

Other options:
    --host        Receiver IP address (default: 127.0.0.1)
    --port        Receiver port (default: 12001)
    --window      Sliding window size (default: 4)
    --timeout     Timeout in seconds (default: 0.2)
    --payload     Packet payload size (default: 1024 bytes)
    --csv         Results CSV file (default: gbn_results.csv)
    --verbose     Print individual packet events

Note: --loss-label only labels the results. Actual packet
loss is configured on the receiver.

Packet format:
    Type (1 byte)
    Sequence Number (4 bytes)
    ACK Number (4 bytes)
    Payload Length (2 bytes)
    Payload (up to 1024 bytes by default)

Packet types:
    START (1) - begins a file transfer
    DATA  (2) - contains file data
    ACK   (3) - acknowledges received packets
    END   (4) - completes the transfer

Sequence numbers:
    START = 0
    DATA  = 1, 2, 3, ... N
    END   = N + 1
"""

import argparse
import os
import random
import socket
import struct

HEADER_FMT = '!BIIH'
HEADER_SIZE = struct.calcsize(HEADER_FMT)

TYPE_START = 1
TYPE_DATA = 2
TYPE_ACK = 3
TYPE_END = 4


def make_packet(ptype, seq=0, ack=0, payload=b''):
    return struct.pack(
        HEADER_FMT, ptype, seq, ack, len(payload)
    ) + payload


def parse_packet(raw):
    if len(raw) < HEADER_SIZE:
        return None

    ptype, seq, ack, length = struct.unpack(
        HEADER_FMT, raw[:HEADER_SIZE]
    )

    if (ptype not in (TYPE_START, TYPE_DATA, TYPE_ACK, TYPE_END)
            or len(raw) != HEADER_SIZE + length):
        return None

    return ptype, seq, ack, raw[HEADER_SIZE:]


def main():
    parser = argparse.ArgumentParser(
        description='Go-Back-N UDP receiver'
    )
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=12001)
    parser.add_argument('--loss', type=float, default=0.0)
    parser.add_argument('--outdir', default='received_gbn')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    if not 0 <= args.loss <= 1:
        parser.error('--loss must be between 0 and 1')

    os.makedirs(args.outdir, exist_ok=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))

    print(
        f'[receiver] listening on {args.host}:{args.port}; '
        f'loss={args.loss:.0%}',
        flush=True
    )

    # Receiver state
    active = False
    expected = 0
    last_ack = None
    outfile = None
    filename = None
    filesize = 0
    received_bytes = 0
    peer = None
    completed_peer = None
    completed_end = None

    def send_ack(addr, seq):
        sock.sendto(make_packet(TYPE_ACK, ack=seq), addr)

        if args.verbose:
            print(f'  -> ACK{seq}')

    try:
        while True:
            raw, addr = sock.recvfrom(65535)

            # Simulate packet loss
            if random.random() < args.loss:
                if args.verbose:
                    print('  xx packet dropped')
                continue

            parsed = parse_packet(raw)

            if parsed is None:
                continue

            ptype, seq, _ack, payload = parsed

            if args.verbose:
                print(
                    f'  <- type={ptype} seq={seq} '
                    f'bytes={len(payload)}'
                )

            if active and addr != peer:
                continue

            # START packet
            if ptype == TYPE_START and seq == 0:

                if active:
                    # Duplicate START: resend ACK0
                    send_ack(addr, 0)
                    continue

                try:
                    name, size = payload.decode(
                        'utf-8'
                    ).rsplit('|', 1)

                    size = int(size)

                    if size < 0:
                        continue

                except (UnicodeDecodeError, ValueError):
                    continue

                filename = os.path.basename(name)

                if filename in ('', '.', '..'):
                    continue

                outfile = open(
                    os.path.join(args.outdir, filename), 'wb'
                )

                peer = addr
                active = True
                expected = 1
                last_ack = 0
                filesize = size
                received_bytes = 0
                completed_peer = None
                completed_end = None

                print(
                    f'[receiver] START {filename} '
                    f'({filesize} bytes)',
                    flush=True
                )

                send_ack(addr, 0)
                continue

            if active:

                # Accept only the expected DATA packet
                if ptype == TYPE_DATA and seq == expected:

                    if received_bytes + len(payload) > filesize:
                        continue

                    outfile.write(payload)
                    received_bytes += len(payload)

                    last_ack = seq
                    expected += 1

                    # Cumulative ACK
                    send_ack(addr, last_ack)

                # END packet
                elif (ptype == TYPE_END
                      and seq == expected
                      and received_bytes == filesize):

                    outfile.close()
                    outfile = None
                    active = False

                    last_ack = seq
                    completed_end = seq
                    completed_peer = addr

                    send_ack(addr, seq)

                    print(
                        f'[receiver] END {filename}: '
                        f'{received_bytes}/{filesize} bytes OK',
                        flush=True
                    )

                else:
                    # Discard out-of-order packets
                    # Send cumulative ACK for last in-order packet
                    if last_ack is not None:
                        send_ack(addr, last_ack)

                    if args.verbose:
                        print(
                            f'  discarded seq={seq}, '
                            f'expected={expected}'
                        )

            elif (ptype == TYPE_END
                  and addr == completed_peer
                  and seq == completed_end):

                # Resend ACK if final ACK was lost
                send_ack(addr, seq)

    except KeyboardInterrupt:
        print('\n[receiver] stopped')

    finally:
        if outfile is not None:
            outfile.close()

        sock.close()


if __name__ == '__main__':
    main()
