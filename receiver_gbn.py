
import socket
import random

HOST ='127.0.0.1'
PORT = 5001

loss_rate = 0.10 #change to 0, 0.10, 0.20, 0.30 as needed for testing

receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
receiver.bind((HOST, PORT))

expected = 0

print("receiver started")

print(f"packet loss rate: {LOSS_RATE * 100:.0f}%")

while True:
  data, address = receiver.recvfrom(1024)
  message = data.decode()

  if message == "END":
    print("transmission completed")
    break


  packet = int(message)

  if random.random() < LOSS_RATE:
    print(f'packet {packet} has been lost)
    continue



  if packet == expected:
    print(f'accepted packet {packet}')
    expected +=1

  else:
    print(f'discarded out of order packet {packet}')



  ack = expected - 1    #culmulative ack

  receiver.sendto(str(ack).encode(), address)



  print(f'sent ack {ack}')




receiver.close()



  















