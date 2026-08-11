import socket
import time

B_IP = "155.247.66.140"
PORT = 50000

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"Sending UDP messages to {B_IP}:{PORT}")

for i in range(1, 11):
    message = f"UDP_TEST_{i}"

    sock.sendto(message.encode(), (B_IP, PORT))

    print(f"Sent: {message}")

    time.sleep(1)

sock.close()

print("Done.")