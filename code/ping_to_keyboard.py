import ctypes
import subprocess
import re
import sys
import time
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

SOURCE_IP = "192.168.50.1"
DEST_IP = "192.168.50.2"

# Ignore duplicate copies of the same packet for this long.
# pktmon can report the same ICMP packet multiple times.
DUPLICATE_WINDOW = 0.100  # seconds

# ============================================================
# WINDOWS KEYBOARD API
# ============================================================

user32 = ctypes.windll.user32

VK_RETURN = 0x0D
VK_SPACE = 0x20

KEYEVENTF_KEYUP = 0x0002


def press_key(vk):
    """Press and release a Windows virtual key."""
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def type_equals():
    """Generate =, Space, Enter."""
    
    # '=' requires the '=' key (VK_OEM_PLUS = 0xBB)
    VK_OEM_PLUS = 0xBB

    press_key(VK_OEM_PLUS)
    time.sleep(0.01)

    press_key(VK_SPACE)
    time.sleep(0.01)

    press_key(VK_RETURN)


# ============================================================
# PING DETECTION
# ============================================================

PING_PATTERN = re.compile(
    rf"{re.escape(SOURCE_IP)}\s*>\s*{re.escape(DEST_IP)}:\s*ICMP echo request",
    re.IGNORECASE,
)


def start_pktmon():
    """
    Start pktmon and return its stdout stream.

    pktmon is used because Windows/Python does not normally expose
    raw ICMP packet capture without additional drivers/libraries.
    """

    # Remove any existing filters first.
    subprocess.run(
        ["pktmon", "filter", "remove"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # Filter for traffic from Computer A.
    subprocess.run(
        ["pktmon", "filter", "add", "-i", SOURCE_IP],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    print("Starting packet monitor...")
    print(f"Watching: {SOURCE_IP} -> {DEST_IP}")
    print()
    print("Waiting for NIC2 trigger...")
    print("=" * 60)

    process = subprocess.Popen(
        ["pktmon", "start", "--etw", "-m", "real-time"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    return process


def stop_pktmon():
    """Stop pktmon cleanly."""
    subprocess.run(
        ["pktmon", "stop"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def main():

    print("=" * 60)
    print("NIC2 PING -> KEYBOARD TRIGGER")
    print("=" * 60)
    print()
    print(f"Source:      {SOURCE_IP}")
    print(f"Destination: {DEST_IP}")
    print()
    print("Keyboard sequence:")
    print("    =")
    print("    SPACE")
    print("    ENTER")
    print()
    print("Starting detector...")
    print()

    last_trigger_time = 0.0

    process = None

    try:
        process = start_pktmon()

        for line in process.stdout:

            # Look specifically for:
            #
            # 192.168.50.1 > 192.168.50.2: ICMP echo request

            if not PING_PATTERN.search(line):
                continue

            now = time.perf_counter()

            # pktmon can output multiple copies of the same packet.
            if now - last_trigger_time < DUPLICATE_WINDOW:
                continue

            last_trigger_time = now

            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            print()
            print(">>> PING FROM A RECEIVED <<<")
            print(f"    {timestamp}")

            print(">>> GENERATING KEYBOARD TRIGGER <<<")

            type_equals()

            print("    Sent: = SPACE ENTER")
            print()

    except KeyboardInterrupt:
        print()
        print("Stopping detector...")

    except Exception as e:
        print()
        print("ERROR:")
        print(e)
        print()
        print("Press Enter to exit.")
        input()

    finally:
        stop_pktmon()

        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()