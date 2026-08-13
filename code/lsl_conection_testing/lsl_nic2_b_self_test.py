from pylsl import resolve_byprop

streams = resolve_byprop(
    "name",
    "LSLOutletStreamName-Markers",
    timeout=5
)

s = streams[0]

print("Name:", s.name())
print("Hostname:", s.hostname())
print("Source ID:", s.source_id())
print("UID:", s.uid())