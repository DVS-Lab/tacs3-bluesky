from pylsl import StreamInfo, StreamOutlet
import time

info = StreamInfo(
    'TestStream',
    'Markers',
    1,
    0,
    'string',
    'direct_test'
)

outlet = StreamOutlet(info)

print("Stream created.")
print()
print("Stream information:")
print("Name:", info.name())
print("Type:", info.type())
print("Source ID:", info.source_id())
print("Hostname:", info.hostname())
print("Stream info XML:")
print(info.as_xml())
print()
print("Sending TEST messages...")

i = 1

while True:
    outlet.push_sample([f"TEST_{i}"])
    print(f"Sent TEST_{i}")
    i += 1
    time.sleep(1)