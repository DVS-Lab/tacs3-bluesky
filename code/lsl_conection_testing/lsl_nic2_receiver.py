from pylsl import resolve_byprop

print("Searching specifically for NIC marker stream...")

streams = resolve_byprop(
    "name",
    "LSLOutletStreamName-Markers",
    timeout=10
)

print("Found:", len(streams))

for s in streams:
    print("Name:", s.name())
    print("Hostname:", s.hostname())
    print("Source ID:", s.source_id())
    print("UID:", s.uid())