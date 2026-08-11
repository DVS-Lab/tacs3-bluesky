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



PS C:\Users\tur74001> & "C:/Program Files/Python314/python.exe" "c:/Users/Public/LAB PROJECTS/Smith-Lab/tacs3-bluesky/code/lsl_conection_testing/lsl_a_direct_senderpy.py"
2026-08-11 11:34:50.529 (   0.009s) [        1619A283]      netinterfaces.cpp:36    INFO| netif '{1BB5E06F-6FF9-4021-9478-8BF056EEFB1D}' (status: 1, multicast: 1
2026-08-11 11:34:50.529 (   0.009s) [        1619A283]      netinterfaces.cpp:58    INFO|       IPv6 ifindex 6
2026-08-11 11:34:50.529 (   0.009s) [        1619A283]      netinterfaces.cpp:36    INFO| netif '{251CA87D-2D41-4FCC-86C5-E2C82347E6B9}' (status: 2, multicast: 1
2026-08-11 11:34:50.530 (   0.009s) [        1619A283]      netinterfaces.cpp:36    INFO| netif '{79E9A897-8DA6-438A-AA39-1467EFDE7A73}' (status: 2, multicast: 1
2026-08-11 11:34:50.530 (   0.010s) [        1619A283]      netinterfaces.cpp:36    INFO| netif '{7E3F0C55-7CC4-4280-BECF-732E93446E43}' (status: 2, multicast: 1
2026-08-11 11:34:50.530 (   0.010s) [        1619A283]      netinterfaces.cpp:36    INFO| netif '{68F793B2-9A22-42C2-974E-C25EFE0727D7}' (status: 2, multicast: 1
2026-08-11 11:34:50.530 (   0.010s) [        1619A283]      netinterfaces.cpp:36    INFO| netif '{7EAE784A-4126-19EE-95B3-806E6F6E6963}' (status: 1, multicast: 1
2026-08-11 11:34:50.530 (   0.010s) [        1619A283]      netinterfaces.cpp:58    INFO|       IPv6 ifindex 1
2026-08-11 11:34:50.530 (   0.010s) [        1619A283]         api_config.cpp:126   INFO| Loaded default config
2026-08-11 11:34:50.530 (   0.010s) [        1619A283]             common.cpp:78    INFO| git:64988c6a14b8dc3b3f270ece58eab4f480bfab43/branch:refs/tags/v1.17.7/build:Release/compiler:MSVC-19.29.30159.0/link:SHARED
Stream created.

Stream information:
Name: TestStream
Type: Markers
Source ID: direct_test
Hostname:
Stream info XML:
<?xml version="1.0"?>
<info>
        <name>TestStream</name>
        <type>Markers</type>
        <channel_count>1</channel_count>
        <channel_format>string</channel_format>
        <source_id>direct_test</source_id>
        <nominal_srate>0.000000000000000</nominal_srate>
        <version>1.100000000000000</version>
        <created_at>0.000000000000000</created_at>
        <uid></uid>
        <session_id></session_id>
        <hostname></hostname>
        <v4address></v4address>
        <v4data_port>0</v4data_port>
        <v4service_port>0</v4service_port>
        <v6address></v6address>
        <v6data_port>0</v6data_port>
        <v6service_port>0</v6service_port>
        <desc />
</info>