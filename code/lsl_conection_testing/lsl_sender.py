from pylsl import StreamInfo, StreamOutlet
import time

info = StreamInfo(
    'TestStream',
    'Markers',
    1,
    0,
    'string',
    'test123'
)

outlet = StreamOutlet(info)

print("LSL stream created.")
print("Sending messages every second...")

i = 1

while True:
    message = f"TEST_{i}"
    outlet.push_sample([message])
    print(f"Sent: {message}")
    i += 1
    time.sleep(1)