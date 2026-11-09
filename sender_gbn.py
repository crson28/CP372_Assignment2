import socket
import time
import argparse
import csv
import os
import struct



HEADER_FMT = '!BIIH'
HEADER_SIZE = struct.calcsize(HEADER_FMT)

TYPE_START = 1
TYPE_DATA = 2
TYPE_ACK = 3
TYPE_END = 4


import argparse
import csv
import os
import socket
import struct
import time

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
        description='Go-Back-N UDP sender'
    )
    parser.add_argument('filename')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=12001)
    parser.add_argument('--window', type=int, default=4)
    parser.add_argument('--timeout', type=float, default=0.2)
    parser.add_argument('--payload', type=int, default=1024)
    parser.add_argument('--csv', default='gbn_results.csv')
    parser.add_argument('--loss-label', default='unspecified')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    if (args.window < 1 or args.timeout <= 0
            or not 1 <= args.payload <= 65507 - HEADER_SIZE):
        parser.error('Invalid window, timeout or payload size')

    # Read file and divide into packets
    file_size = os.path.getsize(args.filename)

    with open(args.filename, 'rb') as file:
        file_data = file.read()

    chunks = [
        file_data[i:i + args.payload]
        for i in range(0, file_size, args.payload)
    ]

    total_packets = len(chunks)
    end_seq = total_packets + 1
    target = (args.host, args.port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(min(args.timeout / 10, 0.05))

    transmissions = 0
    retransmissions = 0
    timeouts = 0
    wire_bytes = 0

    def transmit(packet, retransmission=False):
        nonlocal transmissions, retransmissions, wire_bytes

        sock.sendto(packet, target)
        transmissions += 1
        wire_bytes += len(packet)

        if retransmission:
            retransmissions += 1

    start = time.monotonic()

    try:
        # START handshake
        start_payload = (
            f'{os.path.basename(args.filename)}|{file_size}'
        ).encode('utf-8')

        start_packet = make_packet(
            TYPE_START, seq=0, payload=start_payload
        )

        start_retries = 0

        while True:
            transmit(
                start_packet,
                retransmission=(start_retries > 0)
            )

            deadline = time.monotonic() + args.timeout
            acknowledged = False

            while time.monotonic() < deadline:
                try:
                    raw, addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue

                parsed = parse_packet(raw)

                if (addr == target and parsed
                        and parsed[0] == TYPE_ACK
                        and parsed[2] == 0):
                    acknowledged = True
                    break

            if acknowledged:
                break

            timeouts += 1
            start_retries += 1

            if args.verbose:
                print('[sender] START timeout; retrying')

        # Go-Back-N sliding window
        base = 1
        nextseqnum = 1
        sent_at = {}

        while base <= total_packets:

            # Send multiple packets without waiting
            while (nextseqnum < base + args.window
                   and nextseqnum <= total_packets):

                packet = make_packet(
                    TYPE_DATA,
                    seq=nextseqnum,
                    payload=chunks[nextseqnum - 1]
                )

                transmit(packet)
                sent_at[nextseqnum] = time.monotonic()

                if args.verbose:
                    print(f'[sender] DATA {nextseqnum} sent')

                nextseqnum += 1

            # Receive cumulative acknowledgments
            try:
                raw, addr = sock.recvfrom(65535)
                parsed = parse_packet(raw)

                if (addr == target and parsed
                        and parsed[0] == TYPE_ACK):

                    ack = parsed[2]

                    if base <= ack < nextseqnum:
                        if args.verbose:
                            print(
                                f'[sender] cumulative ACK{ack}: '
                                f'base {base} -> {ack + 1}'
                            )

                        base = ack + 1

                        for seq in list(sent_at):
                            if seq < base:
                                del sent_at[seq]

            except socket.timeout:
                pass

            # Timer for oldest unacknowledged packet
            if (base < nextseqnum
                    and time.monotonic() - sent_at[base]
                    >= args.timeout):

                timeouts += 1

                if args.verbose:
                    print(
                        f'[sender] TIMEOUT: retransmit '
                        f'{base}..{nextseqnum - 1}'
                    )

                # Retransmit entire outstanding window
                for seq in range(base, nextseqnum):
                    packet = make_packet(
                        TYPE_DATA,
                        seq=seq,
                        payload=chunks[seq - 1]
                    )

                    transmit(packet, retransmission=True)
                    sent_at[seq] = time.monotonic()

        # END handshake
        end_packet = make_packet(TYPE_END, seq=end_seq)
        end_retries = 0

        while True:
            transmit(
                end_packet,
                retransmission=(end_retries > 0)
            )

            deadline = time.monotonic() + args.timeout
            acknowledged = False

            while time.monotonic() < deadline:
                try:
                    raw, addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue

                parsed = parse_packet(raw)

                if (addr == target and parsed
                        and parsed[0] == TYPE_ACK
                        and parsed[2] == end_seq):
                    acknowledged = True
                    break

            if acknowledged:
                break

            timeouts += 1
            end_retries += 1

            if args.verbose:
                print('[sender] END timeout; retrying')

        # Performance measurements
        elapsed = time.monotonic() - start
        throughput = file_size / elapsed if elapsed > 0 else 0
        efficiency = file_size / wire_bytes if wire_bytes else 0

        print(f'File: {args.filename} ({file_size} bytes)')
        print(f'Transfer time: {elapsed:.6f} seconds')
        print(f'Throughput: {throughput:.2f} bytes/second')
        print(f'Total transmissions: {transmissions}')
        print(f'Retransmissions: {retransmissions}')
        print(f'Timeouts: {timeouts}')
        print(f'Payload efficiency: {efficiency:.2%}')

        # Save results to CSV
        fields = [
            'protocol', 'file', 'file_size_bytes',
            'loss_rate', 'window_size', 'timeout_s',
            'transfer_time_s', 'throughput_Bps',
            'retransmissions', 'timeouts',
            'transmitted_bytes', 'payload_efficiency'
        ]

        row = [
            'GBN', os.path.basename(args.filename),
            file_size, args.loss_label, args.window,
            args.timeout, elapsed, throughput,
            retransmissions, timeouts, wire_bytes, efficiency
        ]

        write_header = (
            not os.path.exists(args.csv)
            or os.path.getsize(args.csv) == 0
        )

        with open(args.csv, 'a', newline='') as csvfile:
            writer = csv.writer(csvfile)

            if write_header:
                writer.writerow(fields)

            writer.writerow(row)

        print(f'Results appended to {args.csv}')

    except KeyboardInterrupt:
        print('\n[sender] interrupted')

    finally:
        sock.close()


if __name__ == '__main__':
    main()


              
      
                      
          


          









