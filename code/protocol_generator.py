import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import shutil
import re
import numpy as np
import pandas as pd
from scipy import signal


# ============================================================
# PATHS
# ============================================================

EEG_DIR = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky\stimulation\stimulation-data"
)

BEHAV_DIR = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky\data folder used in protocol_generator.py"
)

TEMPLATE = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky\stimulation\protocols\PROTOCOL_TEMPLATE.neprot"
)

OUTPUT_DIR = TEMPLATE.parent


# ============================================================
# FIND FILES
# ============================================================

def find_latest_file(directory, pattern):

    files = list(directory.glob(pattern))

    if not files:
        raise FileNotFoundError(
            f"No files found matching:\n{pattern}"
        )

    def get_date(file):

        match = re.search(
            r"(\d{8})",
            file.name
        )

        if match:
            return int(match.group(1))

        return 0


    files.sort(
        key=get_date,
        reverse=True
    )

    return files[0]


def find_latest_behavior(subject):

    return find_latest_file(
        BEHAV_DIR,
        f"*sub-{subject}_*.csv"
    )


def find_latest_eeg(subject):

    return find_latest_file(
        EEG_DIR,
        f"*sub-{subject}_*.easy"
    )


# ============================================================
# EEG ANALYSIS
# ============================================================

def extract_epochs(eeg, event_times, srate, tmin, tmax):

    epochs = []

    pre = int(abs(tmin) * srate)
    post = int(tmax * srate)

    for event in event_times:

        center = int(event * srate)

        start = center - pre
        end = center + post

        if start >= 0 and end < len(eeg):

            epochs.append(
                eeg[start:end]
            )

    if len(epochs) == 0:
        raise RuntimeError(
            "No usable EEG epochs found."
        )

    return np.array(epochs)



def band_peak(epoch_data, srate, band):

    # average across trials and channels
    signal_avg = np.mean(
        epoch_data,
        axis=(0,2)
    )


    freqs, power = signal.welch(
        signal_avg,
        fs=srate,
        nperseg=srate
    )


    mask = (
        (freqs >= band[0]) &
        (freqs <= band[1])
    )


    peak_freq = freqs[mask][
        np.argmax(
            power[mask]
        )
    ]

    return float(peak_freq)



def estimate_frequencies(easy_file, csv_file):

    SRATE = 500
    N_CHANNELS = 7


    # ----------------------------
    # Load EEG
    # ----------------------------

    raw = np.loadtxt(
        easy_file
    )

    eeg = raw[:, :N_CHANNELS]

    # nV -> uV
    eeg = eeg * 1e-3


    # frontal ROI:
    # F3, Fp1, FCz, F4

    frontal = eeg[:, [0,1,2,4]]


    # ----------------------------
    # Load behavior
    # ----------------------------

    df = pd.read_csv(
        csv_file
    )


    if "rt" not in df.columns:
        raise RuntimeError(
            "CSV missing rt column"
        )

    if "trial_start_time" not in df.columns:
        raise RuntimeError(
            "CSV missing trial_start_time column"
        )


    df["rt_sec"] = (
        df["rt"] / 1000
    )


    # Decision moment

    df["decision_time"] = (
        df["trial_start_time"]
        +
        df["rt_sec"]
    )


    # Outcome/feedback moment
    # Based on your previous notebook:
    # response + 2 seconds

    df["outcome_time"] = (
        df["decision_time"]
        +
        2.0
    )


    # ----------------------------
    # Extract epochs
    # ----------------------------


    # Theta:
    # feedback window
    # 0.1 - 1.5 sec after outcome

    theta_epochs = extract_epochs(
        frontal,
        df["outcome_time"].values,
        SRATE,
        0.1,
        1.5
    )


    # Beta:
    # decision window
    # -1 to -0.1 sec before response

    beta_epochs = extract_epochs(
        frontal,
        df["decision_time"].values,
        SRATE,
        -1.0,
        -0.1
    )


    theta = band_peak(
        theta_epochs,
        SRATE,
        (4,8)
    )


    beta = band_peak(
        beta_epochs,
        SRATE,
        (13,30)
    )


    return theta, beta



# ============================================================
# NEPROT CREATION
# ============================================================

def replace_frequency(file_path, frequency):

    text = file_path.read_text(
        encoding="utf-8"
    )


    text = re.sub(
        r"<ftacsValue>.*?</ftacsValue>",
        f"<ftacsValue>{frequency:.2f}</ftacsValue>",
        text,
        flags=re.DOTALL
    )


    file_path.write_text(
        text,
        encoding="utf-8"
    )



def create_protocol(subject, visit, frequency):

    output = OUTPUT_DIR / (
        f"sub-{subject}_visit{visit}.neprot"
    )


    shutil.copy2(
        TEMPLATE,
        output
    )


    replace_frequency(
        output,
        frequency
    )


    return output



# ============================================================
# GUI
# ============================================================

def generate():

    subject_text = subject_entry.get().strip()


    if not subject_text.isdigit():

        messagebox.showerror(
            "Error",
            "Subject ID must be an integer."
        )

        return


    subject = int(subject_text)


    try:

        eeg_file = find_latest_eeg(
            subject
        )

        csv_file = find_latest_behavior(
            subject
        )


        theta, beta = estimate_frequencies(
            eeg_file,
            csv_file
        )


        created = []


        # Visit 1 = sham

        created.append(
            create_protocol(
                subject,
                1,
                0
            )
        )


        # Visit 2 = beta

        created.append(
            create_protocol(
                subject,
                2,
                beta
            )
        )


        # Visit 3 = theta

        created.append(
            create_protocol(
                subject,
                3,
                theta
            )
        )


        messagebox.showinfo(
            "Complete",
            f"""
Subject: {subject}

EEG:
{eeg_file.name}

Behavior:
{csv_file.name}

Theta:
{theta:.2f} Hz

Beta:
{beta:.2f} Hz


Created:

{created[0].name}
{created[1].name}
{created[2].name}
"""
        )


    except Exception as e:

        messagebox.showerror(
            "Error",
            str(e)
        )



root = tk.Tk()

root.title(
    "tACS Protocol Generator"
)

root.geometry(
    "400x220"
)


tk.Label(
    root,
    text="Subject ID:"
).pack(
    pady=10
)


subject_entry = tk.Entry(
    root
)

subject_entry.pack()



tk.Button(
    root,
    text="Generate Protocols",
    command=generate
).pack(
    pady=30
)


root.mainloop()