
"""
receiver_gbn.py
CP372 Assignment 2 - Go-Back-N Receiver

This program receives files over UDP using the Go-Back-N
protocol and saves them to a local directory.

The receiver only accepts packets in the correct order.
It maintains an expected sequence number and discards
any packets that arrive out of order.

For every received packet, the receiver sends a cumulative
ACK indicating the highest consecutively received packet.

Example:
    Expected packet: 3
    Received packet: 4
    Action: Discard packet 4
    Response: Send ACK2

The receiver can also simulate packet loss by randomly
dropping incoming packets based on a specified loss rate.

How to run (start before the sender):
    python receiver_gbn.py

Simulate 10% packet loss:
    python receiver_gbn.py --loss 0.10

Simulate 20% packet loss:
    python receiver_gbn.py --loss 0.20

Show detailed packet information:
    python receiver_gbn.py --loss 0.10 --verbose

Other options:
    --host       IP address (default: 127.0.0.1)
    --port       Listening port (default: 12001)
    --loss       Packet loss probability (default: 0.0)
    --outdir     Output folder (default: received_gbn)
    --verbose    Print packet and ACK information

Packet loss testing:
    0.00 = 0% loss
    0.10 = 10% loss
    0.20 = 20% loss
    0.30 = 30% loss

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

The receiver reconstructs the original file by writing
accepted DATA packets to the output directory.

Duplicate and out-of-order DATA packets are discarded.
The receiver responds with the most recent cumulative ACK.

The receiver continues running after a transfer finishes,
allowing multiple files to be tested without restarting.

Press Ctrl+C to stop the receiver.
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
