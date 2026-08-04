import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import shutil
import re
import datetime


# ============================================================
# PATHS
# ============================================================

TEMPLATE = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky\stimulation\protocols\PROTOCOL_TEMPLATE.neprot"
)

DATA_FOLDER = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky\data folder used in protocol_generator.py"
)

OUTPUT_FOLDER = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky\stimulation\protocols\generated"
)


# ============================================================
# DOUBLE-BLIND COUNTERBALANCE
# DO NOT DISPLAY THIS TABLE
# ============================================================

COUNTERBALANCE = {

    "A": ["sham", "beta", "theta"],
    "B": ["sham", "theta", "beta"],
    "C": ["beta", "theta", "sham"],
    "D": ["beta", "sham", "theta"],
    "E": ["theta", "sham", "beta"],
    "F": ["theta", "beta", "sham"]

}


# ============================================================
# EEG DATA SEARCH
# ============================================================

def find_latest_csv(subject_id):

    files = list(
        DATA_FOLDER.glob(f"*{subject_id}*.csv")
    )

    if len(files) == 0:
        raise FileNotFoundError(
            f"No CSV found for subject {subject_id}"
        )

    newest = max(
        files,
        key=lambda x: x.stat().st_mtime
    )

    return newest



# ============================================================
# FREQUENCY EXTRACTION
# Replace this later with EEG processing
# ============================================================

def extract_frequency_values(subject_id):

    csv_file = find_latest_csv(subject_id)


    # ========================================================
    # TEMPORARY VALUES
    #
    # Later:
    #   theta = outcome phase peak
    #   beta  = decision phase peak
    #
    # ========================================================

    theta_peak = 6.25
    beta_peak = 18.50


    return (
        csv_file,
        theta_peak,
        beta_peak
    )



# ============================================================
# NEPROT EDITING
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



# ============================================================
# GENERATE FILES
# ============================================================

def create_protocols(subject_id, counterbalance):


    csv_file, theta, beta = extract_frequency_values(
        subject_id
    )


    frequencies = {

        "theta": theta,
        "beta": beta,
        "sham": 0

    }


    # INTERNAL ONLY
    # NEVER RETURN THIS
    visit_conditions = COUNTERBALANCE[counterbalance]


    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )


    created_files = []


    for visit_number, condition in enumerate(
        visit_conditions,
        start=1
    ):

        output_file = OUTPUT_FOLDER / (
            f"{subject_id}_visit{visit_number}.neprot"
        )


        shutil.copy(
            TEMPLATE,
            output_file
        )


        replace_frequency(
            output_file,
            frequencies[condition]
        )


        created_files.append(
            output_file
        )


    return {

        "csv": csv_file,
        "theta": theta,
        "beta": beta,
        "files": created_files

    }



# ============================================================
# GUI FUNCTIONS
# ============================================================

def generate_clicked():

    subject = subject_entry.get().strip()


    if not subject.isdigit():

        messagebox.showerror(
            "Invalid Subject ID",
            "Subject ID must contain only integers."
        )

        return



    counterbalance = counter_var.get()


    if counterbalance == "":

        messagebox.showerror(
            "Missing Counterbalance",
            "Select counterbalance A-F."
        )

        return



    try:

        result = create_protocols(
            int(subject),
            counterbalance
        )


        output_text.delete(
            "1.0",
            tk.END
        )


        output_text.insert(
            tk.END,
            f"Subject ID: {subject}\n\n"
        )


        output_text.insert(
            tk.END,
            f"EEG data used:\n"
            f"{result['csv']}\n\n"
        )


        output_text.insert(
            tk.END,
            f"Extracted frequencies:\n"
            f"Theta: {result['theta']:.2f} Hz\n"
            f"Beta:  {result['beta']:.2f} Hz\n\n"
        )


        output_text.insert(
            tk.END,
            "Generated files:\n"
        )


        for f in result["files"]:

            output_text.insert(
                tk.END,
                f"{f}\n"
            )


        output_text.insert(
            tk.END,
            "\nProtocol generation complete."
        )


    except Exception as e:

        messagebox.showerror(
            "Error",
            str(e)
        )



# ============================================================
# GUI
# ============================================================

root = tk.Tk()

root.title(
    "tACS Protocol Generator"
)

root.geometry(
    "650x500"
)



# Subject ID

tk.Label(
    root,
    text="Subject ID:"
).pack(
    pady=5
)


subject_entry = tk.Entry(
    root
)

subject_entry.pack()



# Counterbalance

tk.Label(
    root,
    text="Counterbalance Group:"
).pack(
    pady=5
)


counter_var = tk.StringVar()


counter_dropdown = ttk.Combobox(
    root,
    textvariable=counter_var,
    values=[
        "A",
        "B",
        "C",
        "D",
        "E",
        "F"
    ],
    state="readonly"
)


counter_dropdown.pack()



# Generate button

tk.Button(
    root,
    text="Generate Protocols",
    command=generate_clicked
).pack(
    pady=15
)



# Output display

output_text = tk.Text(
    root,
    height=18,
    width=80
)

output_text.pack(
    padx=10,
    pady=10
)



root.mainloop()