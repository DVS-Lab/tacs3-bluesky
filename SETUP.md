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

- [ ] LSL trigger sync between the task computer and the stimulation computer (in progress).
- [ ] NIC-2 LSL marker output configuration.
- [ ] Windows Firewall rules for LSL traffic across the two machines (not yet hit/confirmed).
