from psychopy import gui
from pylsl import resolve_streams

# Look for LSL streams on the network
streams = resolve_streams(wait_time=5.0)

if not streams:
    message = "NO LSL STREAMS FOUND.\n\nCheck the network connection and NIC2."
else:
    message = "LSL STREAMS FOUND:\n\n"

    for stream in streams:
        message += (
            f"Name: {stream.name()}\n"
            f"Type: {stream.type()}\n"
            f"Channels: {stream.channel_count()}\n"
            f"Source ID: {stream.source_id()}\n"
            f"Hostname: {stream.hostname()}\n\n"
        )

dlg = gui.Dlg(title="LSL Stream Check")
dlg.addText(message)
dlg.show()