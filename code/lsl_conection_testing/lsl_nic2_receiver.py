from pylsl import resolve_byprop

print("Looking for TEST_STREAM...")

streams = resolve_byprop(
    "name",
    "TEST_STREAM",
    timeout=10
)

print("Found:", len(streams))

for s in streams:
    print("Name:", s.name())
    print("Hostname:", s.hostname())
    print("Source:", s.source_id())