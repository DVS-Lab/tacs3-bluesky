from pylsl import resolve_streams, StreamInlet
import time

print("Looking for LSL streams from NIC2...")
print("Make sure NIC2's LSL Server is ON.\n")

while True:
    streams = resolve_streams()

    if streams:
        print(f"Found {len(streams)} stream(s):\n")

        for i, stream in enumerate(streams):
            print(f"[{i}]")
            print(f"    Name: {stream.name()}")
            print(f"    Type: {stream.type()}")
            print(f"    Channels: {stream.channel_count()}")
            print(f"    Format: {stream.channel_format()}")
            print(f"    Source ID: {stream.source_id()}")
            print()

        break

    print("No streams found. Trying again...")
    time.sleep(2)


# For now, use the first stream we find
stream = streams[0]

print(f"Connecting to: {stream.name()}")
print("Waiting for samples...\n")

inlet = StreamInlet(stream)

while True:
    sample, timestamp = inlet.pull_sample(timeout=1.0)

    if sample is not None:
        print(f"RECEIVED: {sample}   timestamp={timestamp}")