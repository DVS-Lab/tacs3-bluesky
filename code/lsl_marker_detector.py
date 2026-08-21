from pylsl import resolve_byprop, StreamInlet
import subprocess
import time

STREAM_NAME = "LSLOutletStreamName-test-Markers"
B_IP = "192.168.50.2"
TARGET_MARKER = "203"

print("NIC2 LSL marker detector starting...")
print()

while True:
    print("Looking for NIC2 LSL marker stream...")

    streams = resolve_byprop("name", STREAM_NAME, timeout=10)

    if streams:
        break

    print("NIC2 marker stream not found.")
    print("Retrying in 5 seconds...")
    print()
    time.sleep(5)

stream = streams[0]

print("FOUND:", stream.name())
print("Waiting for marker 203...")
print("Detector is running.")
print()

inlet = StreamInlet(stream)

while True:
    sample, timestamp = inlet.pull_sample(timeout=1)

    if sample:
        marker = str(sample[0])

        print("LSL MARKER:", marker, "TIME:", timestamp)

        if marker == TARGET_MARKER:
            print()
            print(">>> MARKER 203 RECEIVED <<<")
            print(">>> PINGING", B_IP, "<<<")

            start = time.perf_counter()

            result = subprocess.run(
                ["ping", "-n", "1", "-w", "1000", B_IP],
                capture_output=True,
                text=True
            )

            elapsed = (time.perf_counter() - start) * 1000

            if result.returncode == 0:
                print("PING SENT/SUCCEEDED")
            else:
                print("PING FAILED")

            print("Ping command completed in %.2f ms" % elapsed)
            print()