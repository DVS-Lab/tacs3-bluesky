from pylsl import resolve_streams

print("Searching for ANY LSL streams...")
print("Waiting 15 seconds...\n")

streams = resolve_streams(wait_time=15)

if not streams:
    print("NO LSL STREAMS FOUND")
else:
    print(f"FOUND {len(streams)} STREAM(S):\n")

    for s in streams:
        print(
            f"Name={s.name()} | "
            f"Type={s.type()} | "
            f"Channels={s.channel_count()} | "
            f"Rate={s.nominal_srate()} | "
            f"Source={s.source_id()}"
        )