CP372 Assignment 2 - Reliable Data Transfer over UDP
=====================================================

Files
-----
  sender_stopwait.py     Stop-and-Wait sender
  receiver_stopwait.py   Stop-and-Wait receiver (also has the packet loss simulation for Part B)
  sender_gbn.py          Go-Back-N sender
  receiver_gbn.py        Go-Back-N receiver
  run_experiments.py     runs all the Stop-and-Wait tests for Part D
  automate_gbn.py        runs all the Go-Back-N tests for Part D
  report.pdf             our report


Before you start
----------------
- You need Python 3. Only standard Python libraries are used, so nothing
  needs to be installed.
- On a Mac, type "python3" instead of "python".
- Run every command from inside the project folder.
- The sender and receiver run on the same computer (127.0.0.1), each in
  its own terminal window.
- Always start the receiver first, then the sender.


1. Stop-and-Wait
----------------
Terminal 1 (receiver):
    python3 receiver_stopwait.py

Terminal 2 (sender), send a real file:
    python3 sender_stopwait.py myfile.txt

or let the program make random data of a certain size:
    python3 sender_stopwait.py --generate 1MB

The received file is saved in the "received" folder. When the transfer is
done the sender prints the transfer time, throughput and number of
retransmissions.

Useful options:
    --loss 0.2       (receiver) randomly drop 20% of packets
    --verbose        (both) print every packet sent, received or dropped
    --port 12000     (both) port number, must be the same on both sides
    --timeout 0.05   (sender) how long to wait for an ACK in seconds
    --chunk 4096     (sender) bytes of the file in each packet

Press Ctrl+C to stop the receiver.


2. Packet loss (Part B)
-----------------------
Start the receiver with a loss rate, then run the sender like normal:
    python3 receiver_stopwait.py --loss 0.3 --verbose
    python3 sender_stopwait.py --generate 100KB --verbose

You will see dropped packets on the receiver side and timeouts and
retransmissions on the sender side. The file still arrives complete.


3. Go-Back-N
------------
Terminal 1 (receiver):
    python3 receiver_gbn.py
    python3 receiver_gbn.py --loss 0.1      (with 10% packet loss)

Terminal 2 (sender):
    python3 sender_gbn.py myfile.txt --window 4

The received file is saved in the "received_gbn" folder.

Useful options:
    --window 4       (sender) window size
    --timeout        (sender) timeout in seconds
    --payload        (sender) bytes of the file in each packet
    --verbose        (both) print packet details
    --port 12001     (both) port number, must be the same on both sides


4. Running all the tests (Part D)
---------------------------------
These scripts start the receiver themselves, so close any receiver you
have running first. Each one runs every file size (10KB to 100MB) at
every loss rate (0%, 10%, 20%, 30%), 5 times each, and averages the results.

Stop-and-Wait:
    python3 run_experiments.py
    Results: stopwait_results.csv (every run) and summary_stopwait.csv (averages)

Go-Back-N:
    python3 automate_gbn.py
    Results: gbn_automation_metrics.csv (every run) and gbn_averages.csv (averages)

The full tests take a few hours because the big files at high loss rates
are slow. If a test gets stopped, run the same command again and it
continues where it left off.


Settings we used for our results
--------------------------------
    Packet payload size:   4096 bytes
    Timeout:               0.05 seconds
    GBN window size:       4
    Header size:           11 bytes
    Sender and receiver on the same computer (127.0.0.1)


Assumptions
-----------
- Packet loss is simulated at the receiver: it randomly throws away
  incoming packets before reading them. ACKs going back to the sender
  are not dropped.
- Both programs run on one computer, so there is no real network delay.
  Almost all of the extra time at higher loss rates comes from waiting
  for timeouts.
- The test files are random data made by the programs. 1KB = 1024 bytes
  and 1MB = 1024 x 1024 bytes.
- The receiver handles one transfer at a time.
- On macOS, packets bigger than about 9KB can't be sent over UDP by
  default, so the packet size should stay at 8192 bytes or less. 