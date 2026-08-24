import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import shutil
import re


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
#
# IMPORTANT:
# This table is INTERNAL ONLY.
#
# A-F represent the six possible permutations of:
# theta, beta, sham
#
# The GUI NEVER displays this information.
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
# FIND THE DATA FILE FOR THIS SUBJECT + VISIT
# ============================================================

def find_latest_csv(subject_id, visit_number):
    """
    Find the most recently modified CSV for the specified
    subject and visit.

    Example:

        subject_id = 2002
        visit_number = 2

    Searches for files containing:

        2002-2

    """

    search_string = f"{subject_id}-{visit_number}"

    matches = []

    for file in DATA_FOLDER.glob("*.csv"):

        if search_string in file.name:
            matches.append(file)


    if not matches:

        raise FileNotFoundError(
            f"No CSV found for subject {subject_id}, "
            f"visit {visit_number}.\n\n"
            f"Expected the filename to contain:\n"
            f"{search_string}"
        )


    # If multiple files match, use the newest one
    newest = max(
        matches,
        key=lambda x: x.stat().st_mtime
    )


    return newest


# ============================================================
# FREQUENCY EXTRACTION
#
# TEMPORARY VERSION
#
# Later this function will:
#   1. Read the CSV
#   2. Locate the associated .easy EEG file
#   3. Calculate theta from outcome phase
#   4. Calculate beta from decision phase
#
# For now, the frequencies are hardcoded.
# ============================================================

def extract_frequency_values(subject_id, visit_number):

    csv_file = find_latest_csv(
        subject_id,
        visit_number
    )


    # ========================================================
    # TEMPORARY VALUES
    #
    # Replace these later with the EEG analysis.
    # ========================================================

    theta_peak = 6.25
    beta_peak = 18.50


    return (
        csv_file,
        theta_peak,
        beta_peak
    )


# ============================================================
# REPLACE <ftacsValue>
# ============================================================

def replace_frequency(file_path, frequency):

    text = file_path.read_text(
        encoding="utf-8"
    )


    replacement = (
        f"<ftacsValue>{frequency:.2f}</ftacsValue>"
    )


    text, number_replaced = re.subn(
        r"<ftacsValue>.*?</ftacsValue>",
        replacement,
        text,
        flags=re.DOTALL
    )


    if number_replaced == 0:

        raise ValueError(
            "Could not find <ftacsValue></ftacsValue> "
            "in the protocol template."
        )


    file_path.write_text(
        text,
        encoding="utf-8"
    )


# ============================================================
# CREATE ONE PROTOCOL FOR ONE VISIT
# ============================================================

def create_protocol(
    subject_id,
    visit_number,
    counterbalance
):

    # --------------------------------------------------------
    # Get the behavioral/EEG data associated with this visit
    # --------------------------------------------------------

    csv_file, theta, beta = extract_frequency_values(
        subject_id,
        visit_number
    )


    # --------------------------------------------------------
    # Determine the hidden condition
    #
    # THIS IS NEVER RETURNED TO THE GUI.
    # --------------------------------------------------------

    visit_conditions = COUNTERBALANCE[counterbalance]

    hidden_condition = visit_conditions[
        visit_number - 1
    ]


    # --------------------------------------------------------
    # Assign the appropriate frequency
    # --------------------------------------------------------

    frequencies = {

        "theta": theta,
        "beta": beta,
        "sham": 0.0

    }


    frequency = frequencies[
        hidden_condition
    ]


    # --------------------------------------------------------
    # Make output directory
    # --------------------------------------------------------

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )


    # --------------------------------------------------------
    # Output filenames
    #
    # All five files use the frequency assigned to this visit.
    # --------------------------------------------------------

    output_files = [

        OUTPUT_FOLDER / (
            f"{subject_id}_visit{visit_number}_bandit_run1.neprot"
        ),

        OUTPUT_FOLDER / (
            f"{subject_id}_visit{visit_number}_bandit_run2.neprot"
        ),

        OUTPUT_FOLDER / (
            f"{subject_id}_visit{visit_number}_SST_run1.neprot"
        ),

        OUTPUT_FOLDER / (
            f"{subject_id}_visit{visit_number}_SST_run2.neprot"
        )

    ]


    # --------------------------------------------------------
    # Copy template and insert frequency into each file
    # --------------------------------------------------------

    for output_file in output_files:

        shutil.copy(
            TEMPLATE,
            output_file
        )

        replace_frequency(
            output_file,
            frequency
        )


    # The first file is still the visit-specific protocol.
    # Keep this as the primary output reported by the GUI.
    output_file = output_files[0]


    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Return the frequency, but NOT the condition.
    #
    # This means the researcher can see the frequency that
    # was used, but cannot see whether it was theta, beta,
    # or sham.
    # --------------------------------------------------------

    return {
        "csv": csv_file,
        "theta": theta,
        "beta": beta,
        "frequency": frequency,
        "output": output_file
    }


# ============================================================
# GUI
# ============================================================

def generate_clicked():

    # --------------------------------------------------------
    # Subject ID
    # --------------------------------------------------------

    subject_text = subject_entry.get().strip()


    if not subject_text.isdigit():

        messagebox.showerror(
            "Invalid Subject ID",
            "Subject ID must contain only integers."
        )

        return


    subject_id = int(subject_text)


    # --------------------------------------------------------
    # Visit number
    # --------------------------------------------------------

    visit_text = visit_var.get()


    if visit_text not in ["1", "2", "3"]:

        messagebox.showerror(
            "Invalid Visit",
            "Select visit 1, 2, or 3."
        )

        return


    visit_number = int(
        visit_text
    )


    # --------------------------------------------------------
    # Counterbalance
    # --------------------------------------------------------

    counterbalance = counter_var.get()


    if counterbalance not in COUNTERBALANCE:

        messagebox.showerror(
            "Missing Counterbalance",
            "Select counterbalance A-F."
        )

        return


    # --------------------------------------------------------
    # Generate
    # --------------------------------------------------------

    try:

        result = create_protocol(
            subject_id,
            visit_number,
            counterbalance
        )


        # ----------------------------------------------------
        # Clear output area
        # ----------------------------------------------------

        output_text.delete(
            "1.0",
            tk.END
        )


        # ----------------------------------------------------
        # Display researcher-visible information
        #
        # DO NOT DISPLAY hidden_condition.
        # ----------------------------------------------------

        output_text.insert(
            tk.END,
            f"Subject ID: {subject_id}\n"
        )


        output_text.insert(
            tk.END,
            f"Visit: {visit_number}\n\n"
        )


        output_text.insert(
            tk.END,
            "Data file used:\n"
        )


        output_text.insert(
            tk.END,
            f"{result['csv']}\n\n"
        )


        output_text.insert(
            tk.END,
            "Extracted frequency estimates:\n"
        )


        output_text.insert(
            tk.END,
            f"Theta peak: {result['theta']:.2f} Hz\n"
        )


        output_text.insert(
            tk.END,
            f"Beta peak:  {result['beta']:.2f} Hz\n\n"
        )


        output_text.insert(
            tk.END,
            "Frequency used for this visit:\n"
        )


        output_text.insert(
            tk.END,
            f"{result['frequency']:.2f} Hz\n\n"
        )


        output_text.insert(
            tk.END,
            "Generated protocol:\n"
        )


        output_text.insert(
            tk.END,
            f"{result['output']}\n\n"
        )


        output_text.insert(
            tk.END,
            "Protocol generation complete."
        )


        messagebox.showinfo(
            "Complete",
            "Protocol generated successfully."
        )


    except Exception as e:

        messagebox.showerror(
            "Error",
            str(e)
        )


# ============================================================
# BUILD GUI
# ============================================================

root = tk.Tk()

root.title(
    "tACS Protocol Generator"
)

root.geometry(
    "700x550"
)


# ============================================================
# SUBJECT ID
# ============================================================

tk.Label(
    root,
    text="Subject ID:",
    font=("Arial", 11)
).pack(
    pady=(15, 5)
)


subject_entry = tk.Entry(
    root,
    width=20,
    font=("Arial", 11)
)

subject_entry.pack()


# ============================================================
# VISIT
# ============================================================

tk.Label(
    root,
    text="Visit:",
    font=("Arial", 11)
).pack(
    pady=(15, 5)
)


visit_var = tk.StringVar()


visit_dropdown = ttk.Combobox(
    root,
    textvariable=visit_var,
    values=[
        "1",
        "2",
        "3"
    ],
    state="readonly",
    width=17
)

visit_dropdown.pack()


# ============================================================
# COUNTERBALANCE
# ============================================================

tk.Label(
    root,
    text="Counterbalance Group:",
    font=("Arial", 11)
).pack(
    pady=(15, 5)
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
    state="readonly",
    width=17
)

counter_dropdown.pack()


# ============================================================
# GENERATE BUTTON
# ============================================================

tk.Button(
    root,
    text="Generate Protocol",
    command=generate_clicked,
    width=25,
    height=2
).pack(
    pady=20
)


# ============================================================
# OUTPUT WINDOW
# ============================================================

output_text = tk.Text(
    root,
    height=18,
    width=85,
    font=("Consolas", 10)
)

output_text.pack(
    padx=15,
    pady=10
)


# ============================================================
# START GUI
# ============================================================

root.mainloop()