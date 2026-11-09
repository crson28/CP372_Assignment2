import socket
import time


HOST = '127.0.0.1'

PORT = 5001


window_size = 4

total_packets = 10
timeout = 2


sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sender.settimeout(0.1)

base = 0
nextseqnum = 0
timer_start = None

transmissions = 0
retransmissions = 0
timeouts = 0

print('sender started')


while base < total_packets:
    while (nextseqnum < base + window_size
           and nextseqnum < total_packets):


      sender.sendto(
            str(nextseqnum).encode(), (HOST, PORT)
        )

      print(f'sent packet {nextseqnum}')
      transmissions += 1


      if base == nextseqnum:
            timer_start = time.monotonic()   #this starts a timer for the oldest unacked packet

      nextseqnum += 1




    try:
        data, address = sender.recvfrom(1024)
        ack = int(data.decode())
        print(f'received ack: {ack}')

        if base <= ack  < nextseqnum:
            base = ack + 1   
            print(f'Window slides to {base}')   
            if base == nextseqnum:
                  timer_start = None
            else:
                  timer_start = time.monotonic()

    except socket.timeout:
        pass


    if (timer_start is not None and time.monotonic() - timer_start >= timeout):
      print(f'\ntimeout, retransmitting packets {base} to {nextseqnum - 1}')
      timeouts +=1   #checking timeout for oldest unacked packet

      for packet in range (base, nextseqnum):
          sender.sendto(str(packet).encode(), (HOST, PORT))
          print(f'retransmitted packet {packet}')  # retransmits all outstanding packets 
          transmissions+=1
          retransmissions+=1
      timer_start = time.monotonic()



sender.sendto(b"END", (HOST, PORT))

print('\n transmission compete')
print(f'total transmissions: {transmissions}')
print(f'retransmissions: {retransmissions}')
print(f'timeouts: {timeouts}')



sender.close()




              
      
                      
          


          









