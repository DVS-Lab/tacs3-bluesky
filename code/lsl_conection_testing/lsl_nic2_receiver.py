from pylsl import resolve_byprop, StreamInlet

STREAM_NAME = "LSLOutletStreamName-test-Markers"

print(f"Looking for: {STREAM_NAME}")

streams = resolve_byprop("name", STREAM_NAME, timeout=10)

if not streams:
    print("ERROR: Stream not found.")
    input("Press Enter to exit...")
    raise SystemExit

stream = streams[0]

print("Connected!")
print("Stream:", stream.name())
print("Type:", stream.type())
print()
print("Waiting for markers...")
print("Click START in NIC2 on Computer A.")
print("Press Ctrl+C to stop.")
print()

inlet = StreamInlet(stream)

while True:
    sample, timestamp = inlet.pull_sample(timeout=1)

    if sample:
        print(f"RECEIVED: {sample}  |  LSL timestamp: {timestamp}")