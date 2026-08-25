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
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky\stimulation\calculated-theta-beta"
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
# Reads the already-calculated theta and beta peaks from the
# theta/beta analysis report.
#
# Example:
#
#   3003-2_pre-stim_theta-beta.txt
#
# The report contains:
#
#   Theta stimulation frequency: 7.00 Hz
#   Beta stimulation frequency: 22.00 Hz
#
# The protocol generator uses those values directly.
# ============================================================

def extract_frequency_values(subject_id, visit_number):

    # --------------------------------------------------------
    # Find the calculated theta/beta report
    #
    # Example:
    # subject_id = 3003
    # visit_number = 2
    #
    # Looks for:
    # 3003-2_pre-stim_theta-beta.txt
    # --------------------------------------------------------

    txt_file = DATA_FOLDER / (
        f"{subject_id}-{visit_number}_pre-stim_theta-beta.txt"
    )


    if not txt_file.exists():

        raise FileNotFoundError(
            f"Could not find theta/beta report:\n\n"
            f"{txt_file}"
        )


    # --------------------------------------------------------
    # Read report
    # --------------------------------------------------------

    text = txt_file.read_text(
        encoding="utf-8"
    )


    # --------------------------------------------------------
    # Extract theta
    #
    # Looks for:
    #
    # Theta stimulation frequency: 7.00 Hz
    # --------------------------------------------------------

    theta_match = re.search(
        r"Theta stimulation frequency:\s*([0-9]+(?:\.[0-9]+)?)\s*Hz",
        text
    )


    if theta_match is None:

        raise ValueError(
            "Could not find the theta stimulation frequency "
            "in the theta/beta report."
        )


    theta_peak = float(
        theta_match.group(1)
    )


    # --------------------------------------------------------
    # Extract beta
    #
    # Looks for:
    #
    # Beta stimulation frequency: 22.00 Hz
    # --------------------------------------------------------

    beta_match = re.search(
        r"Beta stimulation frequency:\s*([0-9]+(?:\.[0-9]+)?)\s*Hz",
        text
    )


    if beta_match is None:

        raise ValueError(
            "Could not find the beta stimulation frequency "
            "in the theta/beta report."
        )


    beta_peak = float(
        beta_match.group(1)
    )


    return (
        txt_file,
        theta_peak,
        beta_peak
    )


# ============================================================
# REPLACE <ftacsValue>
# ============================================================

def replace_protocol_info(file_path, frequency, template_name):

    text = file_path.read_text(
        encoding="utf-8"
    )


    # --------------------------------------------------------
    # Replace frequency
    # --------------------------------------------------------

    frequency_replacement = (
        f"<ftacsValue>{frequency:.2f}</ftacsValue>"
    )

    text, frequency_replaced = re.subn(
        r"<ftacsValue>.*?</ftacsValue>",
        frequency_replacement,
        text,
        flags=re.DOTALL
    )


    if frequency_replaced == 0:

        raise ValueError(
            "Could not find <ftacsValue></ftacsValue> "
            "in the protocol template."
        )


    # --------------------------------------------------------
    # Replace TemplateName
    # --------------------------------------------------------

    template_replacement = (
        f"<TemplateName>{template_name}</TemplateName>"
    )

    text, template_replaced = re.subn(
        r"<TemplateName>.*?</TemplateName>",
        template_replacement,
        text,
        flags=re.DOTALL
    )


    if template_replaced == 0:

        raise ValueError(
            "Could not find <TemplateName></TemplateName> "
            "in the protocol template."
        )


    # --------------------------------------------------------
    # Save modified protocol
    # --------------------------------------------------------

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


        # --------------------------------------------------------
        # Determine the protocol name from the output filename
        # --------------------------------------------------------

        if "bandit_run1" in output_file.name:
            run_name = "Bandit-Run1"

        elif "bandit_run2" in output_file.name:
            run_name = "Bandit-Run2"

        elif "SST_run1" in output_file.name:
            run_name = "SST-Run1"

        elif "SST_run2" in output_file.name:
            run_name = "SST-Run2"

        else:
            raise ValueError(
                f"Unrecognized protocol filename: {output_file.name}"
            )


        # --------------------------------------------------------
        # Create TemplateName
        #
        # Example:
        # TACS3-3003-Visit2-Bandit-Run1
        # --------------------------------------------------------

        template_name = (
            f"TACS3-{subject_id}-Visit{visit_number}-{run_name}"
        )


        # --------------------------------------------------------
        # Insert frequency and TemplateName
        # --------------------------------------------------------

        replace_protocol_info(
            output_file,
            frequency,
            template_name
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