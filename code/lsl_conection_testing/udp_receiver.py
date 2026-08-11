import socket

PORT = 50000

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", PORT))

print(f"Listening for UDP messages on port {PORT}...")
print("Waiting for Computer A...")

while True:
    data, address = sock.recvfrom(1024)

    print(
        f"Received from {address[0]}:{address[1]} -> "
        f"{data.decode()}"
    )