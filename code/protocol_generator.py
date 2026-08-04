import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import shutil
import re
import numpy as np
from scipy import signal


# =====================================================
# PATHS
# =====================================================

DATA_DIR = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky\stimulation\stimulation-data"
)

TEMPLATE = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky\stimulation\protocols\PROTOCOL_TEMPLATE.neprot"
)

OUTPUT_DIR = TEMPLATE.parent


# =====================================================
# FIND EEG FILE
# =====================================================

def find_latest_easy(subject_id):

    matches = list(
        DATA_DIR.glob(f"*_sub-{subject_id}_*.easy")
    )

    if not matches:
        raise FileNotFoundError(
            f"No EEG file found for sub-{subject_id}"
        )

    def extract_date(path):

        m = re.search(
            r"(\d{8})",
            path.name
        )

        if m:
            return int(m.group(1))

        return 0


    matches.sort(
        key=extract_date,
        reverse=True
    )

    return matches[0]


# =====================================================
# TEMPORARY EEG FREQUENCY ESTIMATION
# Replace later with CSV locked method
# =====================================================

def estimate_frequencies(easy_file):

    CHANNELS = 7
    SRATE = 500

    raw = np.loadtxt(easy_file)

    eeg = raw[:, :CHANNELS]

    # convert nv -> uV
    eeg = eeg * 1e-3


    # frontal channels:
    # F3, Fp1, FCz, F4
    frontal = eeg[:, [0,1,2,4]]

    frontal_mean = np.mean(
        frontal,
        axis=1
    )


    # Welch PSD
    freqs, psd = signal.welch(
        frontal_mean,
        fs=SRATE,
        nperseg=SRATE*4
    )


    power = 10*np.log10(
        psd + 1e-20
    )


    def peak(low, high):

        mask = (
            (freqs >= low) &
            (freqs <= high)
        )

        f = freqs[mask]
        p = power[mask]

        return float(
            f[np.argmax(p)]
        )


    theta = peak(4,8)
    beta = peak(13,30)


    return theta, beta



# =====================================================
# NEPROT GENERATION
# =====================================================

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

    outfile = OUTPUT_DIR / (
        f"sub-{subject}_visit{visit}.neprot"
    )


    shutil.copy2(
        TEMPLATE,
        outfile
    )


    replace_frequency(
        outfile,
        frequency
    )


    return outfile



# =====================================================
# GUI
# =====================================================

def generate():

    value = subject_entry.get().strip()


    if not value.isdigit():

        messagebox.showerror(
            "Error",
            "Subject ID must be an integer"
        )

        return


    subject = int(value)


    try:

        eeg_file = find_latest_easy(
            subject
        )


        theta, beta = estimate_frequencies(
            eeg_file
        )


        files = []

        # sham
        files.append(
            create_protocol(
                subject,
                1,
                0
            )
        )


        # beta
        files.append(
            create_protocol(
                subject,
                2,
                beta
            )
        )


        # theta
        files.append(
            create_protocol(
                subject,
                3,
                theta
            )
        )


        messagebox.showinfo(
            "Complete",
            f"""
EEG:
{eeg_file.name}

Theta:
{theta:.2f} Hz

Beta:
{beta:.2f} Hz


Created:
{files[0].name}
{files[1].name}
{files[2].name}
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
    text="Subject ID"
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