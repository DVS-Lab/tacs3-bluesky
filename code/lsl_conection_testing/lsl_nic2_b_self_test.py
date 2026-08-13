from pylsl import StreamInfo, StreamOutlet
import time

info = StreamInfo(
    name="TEST_STREAM",
    type="Markers",
    channel_count=1,
    nominal_srate=0,
    channel_format="string",
    source_id="TEST_SOURCE"
)

outlet = StreamOutlet(info)

print("TEST_STREAM is running.")
print("Sending a marker every 2 seconds...")

i = 0

while True:
    marker = f"TEST_{i}"
    outlet.push_sample([marker])
    print("Sent:", marker)
    i += 1
    time.sleep(2)