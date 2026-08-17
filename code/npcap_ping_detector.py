import ctypes
import time
from datetime import datetime

from scapy.all import AsyncSniffer, IP, ICMP, get_if_list, conf


# ============================================================
# CONFIGURATION
# ============================================================

SOURCE_IP = "192.168.50.1"
DEST_IP = "192.168.50.2"

DUPLICATE_WINDOW = 0.100


# ============================================================
# WINDOWS KEYBOARD API
# ============================================================

user32 = ctypes.windll.user32

VK_RETURN = 0x0D
VK_SPACE = 0x20
VK_OEM_PLUS = 0xBB

KEYEVENTF_KEYUP = 0x0002


def press_key(vk):
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def type_equals():
    """Generate =, SPACE, ENTER."""

    press_key(VK_OEM_PLUS)
    time.sleep(0.01)

    press_key(VK_SPACE)
    time.sleep(0.01)

    press_key(VK_RETURN)


# ============================================================
# PACKET DETECTION
# ============================================================

last_trigger_time = 0.0


def packet_callback(packet):

    global last_trigger_time

    if not packet.haslayer(IP):
        return

    if not packet.haslayer(ICMP):
        return

    ip = packet[IP]

    # Only accept:
    #
    # 192.168.50.1 -> 192.168.50.2
    #
    if ip.src != SOURCE_IP:
        return

    if ip.dst != DEST_IP:
        return

    # ICMP type 8 = Echo Request
    if packet[ICMP].type != 8:
        return

    now = time.perf_counter()

    # Prevent duplicate packet detections
    if now - last_trigger_time < DUPLICATE_WINDOW:
        return

    last_trigger_time = now

    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    print()
    print("=" * 70)
    print(">>> NIC2 PING DETECTED <<<")
    print("=" * 70)
    print(f"Source:      {SOURCE_IP}")
    print(f"Destination: {DEST_IP}")
    print(f"Time:        {timestamp}")
    print()
    print(">>> GENERATING KEYBOARD TRIGGER <<<")

    type_equals()

    print("    Sent: = SPACE ENTER")
    print("=" * 70)
    print()


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("NPCAP ALL-ADAPTER NIC2 PING DETECTOR")
    print("=" * 70)
    print()

    print(f"Watching for:")
    print(f"    {SOURCE_IP} -> {DEST_IP}")
    print()
    print("Keyboard trigger:")
    print("    =")
    print("    SPACE")
    print("    ENTER")
    print()

    # Tell Scapy to use Npcap/libpcap.
    conf.use_pcap = True

    # --------------------------------------------------------
    # Find all Npcap interfaces
    # --------------------------------------------------------

    interfaces = get_if_list()

    print(f"Found {len(interfaces)} capture interfaces.")
    print()

    for i, iface in enumerate(interfaces):
        print(f"  {i}: {iface}")

    print()
    print("=" * 70)
    print("STARTING CAPTURE ON ALL ADAPTERS")
    print("=" * 70)
    print()
    print("Waiting for NIC2 ping...")
    print("Press Ctrl+C to stop.")
    print()

    sniffers = []

    try:

        # ----------------------------------------------------
        # Start one sniffer for every interface
        # ----------------------------------------------------

        for iface in interfaces:

            # Skip loopback.
            if "Loopback" in iface or "loopback" in iface.lower():
                continue

            print(f"Starting capture on: {iface}")

            sniffer = AsyncSniffer(
                iface=iface,
                filter=(
                    f"icmp and "
                    f"src host {SOURCE_IP} and "
                    f"dst host {DEST_IP}"
                ),
                prn=packet_callback,
                store=False
            )

            sniffer.start()
            sniffers.append(sniffer)

        print()
        print("ALL ADAPTERS ARE NOW BEING MONITORED.")
        print()

        # ----------------------------------------------------
        # Keep program alive
        # ----------------------------------------------------

        while True:
            time.sleep(0.25)

    except KeyboardInterrupt:

        print()
        print("Stopping all packet monitors...")

    except Exception as e:

        print()
        print("=" * 70)
        print("ERROR")
        print("=" * 70)
        print(e)
        print()

    finally:

        for sniffer in sniffers:

            try:
                sniffer.stop()
            except Exception:
                pass

        print()
        print("All packet monitors stopped.")
        print()


if __name__ == "__main__":
    main()