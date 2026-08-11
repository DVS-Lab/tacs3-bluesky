from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_streams
import time

# Create an LSL stream
info = StreamInfo(
    'TestStream',
    'Markers',
    1,
    0,
    'string',
    'self_test'
)

outlet = StreamOutlet(info)

print("LSL stream created.")
print("Waiting for the stream to become discoverable...")

# Find our own stream
streams = []
while not streams:
    streams = [
        s for s in resolve_streams()
        if s.name() == "TestStream"
    ]
    time.sleep(0.5)

print("SUCCESS: A can discover its own LSL stream.")

# Connect to it
inlet = StreamInlet(streams[0])

print("Sending 5 test messages...")

for i in range(1, 6):
    message = f"TEST_{i}"

    outlet.push_sample([message])
    print(f"Sent: {message}")

    # Try to receive the message ourselves
    sample, timestamp = inlet.pull_sample(timeout=2.0)

    if sample:
        print(f"  RECEIVED: {sample[0]} | timestamp={timestamp}")
    else:
        print("  ERROR: Did not receive the message.")

    time.sleep(1)

print("Test complete.")