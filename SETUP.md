# Setup Guide

Steps to get `bandit_main.py` / `sst_main.py` running on a new task-presentation computer. This is a living checklist — add to it whenever a new machine surfaces a new gotcha.

## 1. Install Python 3.11 — not whatever's already there

PsychoPy does not currently publish installable wheels for Python 3.12+. Check what's already installed:

```powershell
py -0p
```

If there's no `3.10` or `3.11` entry, install one:

```powershell
py install 3.11
```

This uses the Python Install Manager (`py`), which ships with recent python.org installs. If `py install` isn't recognized at all, install Python manually from python.org — get **3.11.9** specifically (`https://www.python.org/downloads/release/python-3119/`); every 3.11.x release after 3.11.9 is source-only with no Windows installer, so grabbing "latest 3.11" from the main downloads page will silently give you a file you can't install.

## 2. Get the code

```powershell
git clone https://github.com/DVS-Lab/tacs3-bluesky.git
cd tacs3-bluesky
```

(or `git pull` if already cloned)

## 3. Create the virtual environment with Python 3.11 specifically

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
```

If PowerShell blocks the activation script with an execution-policy error: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then retry the activate command.

## 4. Install dependencies

```powershell
pip install -r requirements.txt
```

Run from the repo root (where `requirements.txt` lives), not `code/`.

## 5. Run the tasks from the `code/` directory

```powershell
cd code
python bandit_main.py --subject 001 --session 001 --localizer
python sst_main.py --subject 001 --session 001 --localizer
```

Config paths and stimulus loading assume this is the working directory.

## Known non-errors — expected output, not a problem

- `No matching EEG stream was found for type='EEG'...` — expected unless a live StarStim/LSL EEG stream is actually running.
- `Stream transmission broke off... re-connecting` printed right at the very end of a run — harmless LSL teardown noise as the process exits.
- Bandit shows colored circles with numbers instead of flower images — expected until PNG stimuli are added to `../stimuli/images`.
- `Monitor specification not found. Creating a temporary one...` — harmless PsychoPy warning, no monitor calibration file exists yet.

## Quick smoke test (no PsychoPy window, no hardware needed)

```powershell
python bandit_main.py --subject 999 --session 001 --localizer --test-mode
python sst_main.py --subject 999 --session 001 --localizer --test-mode
```

Confirms the environment/config are sane before touching a real window. Use a throwaway subject ID like `999`, not a real one.

## Still open / in progress

- [ ] End-to-end test of LSL trigger sync against real NIC-2 hardware (procedure below — nothing past step 2 of that procedure has actually been run against real hardware yet).
- [ ] Windows Firewall rules for LSL traffic across the two machines (not yet hit/confirmed).

## Testing the task ↔ stimulation LSL trigger sync

The task waits at a "press SPACE or wait for stimulation trigger" screen and auto-starts when it sees LSL marker `203` (NIC-2's "stimulation starting" marker) — this lets an experimenter start the task in sync with hitting Go in NIC-2, without the task knowing which condition is running. As of 2026-07-31, this has been verified in isolation (single-machine simulation of both sides) but **never against a real cross-machine NIC-2 broadcast**. Three specific things could still go wrong the first time it's tried for real — this procedure is written to catch which one, if any.

### Setup on the stimulation computer (NIC-2)

1. Open the Protocol Editor → Settings. Near the bottom there's an "LSL Server" toggle — turn it **on**.
2. Note the "Outlet for Lab Streaming Layer" name shown there. As of this writing it's `LSLOutletStreamName`, and `code/config.json`'s `stimulation.lsl.outlet_stream_name` is already set to match. **If your NIC-2 shows a different name, update that config value to match before testing** — the task specifically looks for a stream with this exact name (deliberately, so it doesn't accidentally bind to some other stream on the network) and won't find NIC-2 if the names don't match.
3. Load any stimulation protocol you can hit "Go" on — doesn't need to be a real active/sham condition for this test.

### Setup on the task computer

4. `git pull`, then from `code/`:
   ```powershell
   python .\bandit_main.py --subject 999 --session 001 --windowed
   ```
   (No `--localizer` — that flag skips the LSL wait entirely, since the localizer run happens before any stimulation setup. You want a normal run here so it actually waits on the trigger.)
5. It should print `LSL: connected to marker stream 'LSLOutletStreamName'.` near the start, then sit at the waiting screen. **If it doesn't print that line**, or prints a "no stream named ... found, falling back" warning instead, stop here — that's the network/discovery problem (see Troubleshooting).

### The actual test

6. On the stimulation computer, click Go on the loaded protocol.
7. On the task computer, the waiting screen should immediately advance to the trial sequence within a second or two of clicking Go.

### Troubleshooting, by failure mode

- **Task never prints "LSL: connected to marker stream..." at all, even before you click Go on NIC-2**: this means the task couldn't discover *any* LSL stream on the network — likely a firewall or multicast problem, not a NIC-2 problem specifically. Check Windows Firewall on the task computer for a blocked-connection prompt (may need "Allow" on both Private and Public/Domain profiles), and confirm nothing about the network (VPN, guest WiFi, managed switch) blocks UDP multicast between `.159` and `.140` — note that `ping` working does *not* guarantee multicast works, they're different protocols.
- **Task prints a "no stream named 'LSLOutletStreamName' found... falling back" warning**: LSL discovery itself is working (good sign), but NIC-2 either isn't broadcasting yet (double check the LSL Server toggle actually took effect — may need the protocol loaded/armed first) or is using a different outlet name than what's configured — check what name actually appears in NIC-2's settings and update `config.json` to match.
- **Task connects to the right stream name, but never advances when you click Go**: NIC-2 is broadcasting *something*, but not marker code `203` specifically, or not at the moment you expect (e.g., maybe only on ramp-up-complete, not on Go). Worth checking whether NIC-2 has a way to show/log what it's actually sending on that outlet, to confirm the real marker code and timing.
- **Windows Firewall shows a prompt when you first run the task or start the NIC-2 protocol**: click Allow for both network profile types offered, not just one — labs/university networks are often categorized "Domain" or "Public" rather than "Private," and firewall rules are commonly scoped per-profile.
