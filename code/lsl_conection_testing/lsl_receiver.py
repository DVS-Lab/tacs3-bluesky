from pylsl import resolve_streams

print("Scanning for ANY LSL streams...")

streams = resolve_streams()

print(f"Found {len(streams)} streams.")

for stream in streams:
    print(
        f"Name: {stream.name()} | "
        f"Type: {stream.type()} | "
        f"Host: {stream.hostname()}"
    )