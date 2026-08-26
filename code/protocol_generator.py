import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import shutil
import re


# ============================================================
# PATHS
# ============================================================

TEMPLATE = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky"
    r"\stimulation\protocols\PROTOCOL_TEMPLATE.neprot"
)

DATA_FOLDER = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky"
    r"\stimulation\calculated-theta-beta"
)

OUTPUT_FOLDER = Path(
    r"C:\Users\Public\LAB PROJECTS\smith-lab\tacs3-bluesky"
    r"\stimulation\protocols\generated"
)


# ============================================================
# DOUBLE-BLIND COUNTERBALANCE
#
# A-F correspond to the six possible orders of:
# theta, beta, sham
#
# This is intentionally NOT displayed by the GUI.
# ============================================================

COUNTERBALANCE = {
    "A": ["sham", "beta", "theta"],
    "B": ["sham", "theta", "beta"],
    "C": ["beta", "theta", "sham"],
    "D": ["beta", "sham", "theta"],
    "E": ["theta", "sham", "beta"],
    "F": ["theta", "beta", "sham"],
}


# ============================================================
# READ THETA / BETA FREQUENCIES
# ============================================================

def extract_frequency_values(subject_id, visit_number):
    """
    Read the pre-calculated theta and beta frequencies from:

        SUBJECT-VISIT_pre-stim_theta-beta.txt

    Example:

        3003-2_pre-stim_theta-beta.txt

    Expected lines:

        Theta stimulation frequency: 7.00 Hz
        Beta stimulation frequency: 22.00 Hz
    """

    txt_file = DATA_FOLDER / (
        f"{subject_id}-{visit_number}_pre-stim_theta-beta.txt"
    )

    if not txt_file.exists():
        raise FileNotFoundError(
            f"Could not find theta/beta report:\n\n"
            f"{txt_file}"
        )

    text = txt_file.read_text(encoding="utf-8")

    # --------------------------------------------------------
    # Extract theta
    # --------------------------------------------------------

    theta_match = re.search(
        r"Theta stimulation frequency:\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*Hz",
        text,
    )

    if theta_match is None:
        raise ValueError(
            "Could not find the theta stimulation frequency "
            "in the theta/beta report."
        )

    theta = float(theta_match.group(1))

    # --------------------------------------------------------
    # Extract beta
    # --------------------------------------------------------

    beta_match = re.search(
        r"Beta stimulation frequency:\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*Hz",
        text,
    )

    if beta_match is None:
        raise ValueError(
            "Could not find the beta stimulation frequency "
            "in the theta/beta report."
        )

    beta = float(beta_match.group(1))

    return txt_file, theta, beta


# ============================================================
# MODIFY PROTOCOL
# ============================================================

def replace_protocol_info(file_path, frequency, template_name):
    """
    Replace the frequency and TemplateName in a copied
    protocol template.
    """

    text = file_path.read_text(encoding="utf-8")

    # --------------------------------------------------------
    # Replace stimulation frequency
    # --------------------------------------------------------

    text, frequency_replaced = re.subn(
        r"<ftacsValue>.*?</ftacsValue>",
        f"<ftacsValue>{frequency:.2f}</ftacsValue>",
        text,
        flags=re.DOTALL,
    )

    if frequency_replaced == 0:
        raise ValueError(
            "Could not find <ftacsValue></ftacsValue> "
            "in the protocol template."
        )

    # --------------------------------------------------------
    # Replace TemplateName
    # --------------------------------------------------------

    text, template_replaced = re.subn(
        r"<TemplateName>.*?</TemplateName>",
        f"<TemplateName>{template_name}</TemplateName>",
        text,
        flags=re.DOTALL,
    )

    if template_replaced == 0:
        raise ValueError(
            "Could not find <TemplateName></TemplateName> "
            "in the protocol template."
        )

    file_path.write_text(text, encoding="utf-8")


# ============================================================
# CREATE PROTOCOLS
# ============================================================

def create_protocol(subject_id, visit_number, counterbalance):
    """
    Generate the four protocol files for the selected
    participant and visit.
    """

    # --------------------------------------------------------
    # Get theta and beta
    # --------------------------------------------------------

    txt_file, theta, beta = extract_frequency_values(
        subject_id,
        visit_number,
    )

    # --------------------------------------------------------
    # Determine hidden condition
    #
    # This is intentionally never returned to the GUI.
    # --------------------------------------------------------

    hidden_condition = COUNTERBALANCE[counterbalance][visit_number - 1]

    # --------------------------------------------------------
    # Determine stimulation frequency
    # --------------------------------------------------------

    frequencies = {
        "theta": theta,
        "beta": beta,
        "sham": 0.0,
    }

    frequency = frequencies[hidden_condition]

    # --------------------------------------------------------
    # Create output directory
    # --------------------------------------------------------

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Output files
    # --------------------------------------------------------

    output_files = [
        (
            OUTPUT_FOLDER
            / f"{subject_id}_visit{visit_number}_bandit_run1.neprot"
        ),
        (
            OUTPUT_FOLDER
            / f"{subject_id}_visit{visit_number}_bandit_run2.neprot"
        ),
        (
            OUTPUT_FOLDER
            / f"{subject_id}_visit{visit_number}_SST_run1.neprot"
        ),
        (
            OUTPUT_FOLDER
            / f"{subject_id}_visit{visit_number}_SST_run2.neprot"
        ),
    ]

    # --------------------------------------------------------
    # Protocol names
    # --------------------------------------------------------

    protocol_names = [
        "Bandit-Run1",
        "Bandit-Run2",
        "SST-Run1",
        "SST-Run2",
    ]

    # --------------------------------------------------------
    # Generate each protocol
    # --------------------------------------------------------

    for output_file, run_name in zip(
        output_files,
        protocol_names,
    ):

        shutil.copy(
            TEMPLATE,
            output_file,
        )

        template_name = (
            f"TACS3-{subject_id}-"
            f"Visit{visit_number}-"
            f"{run_name}"
        )

        replace_protocol_info(
            output_file,
            frequency,
            template_name,
        )

    # --------------------------------------------------------
    # Return information for the GUI
    #
    # hidden_condition is deliberately NOT returned.
    # --------------------------------------------------------

    return {
        "txt": txt_file,
        "theta": theta,
        "beta": beta,
        "frequency": frequency,
        "outputs": output_files,
    }


# ============================================================
# GUI: GENERATE BUTTON
# ============================================================

def generate_clicked():

    # --------------------------------------------------------
    # Subject ID
    # --------------------------------------------------------

    subject_text = subject_entry.get().strip()

    if not subject_text.isdigit():
        messagebox.showerror(
            "Invalid Subject ID",
            "Subject ID must contain only integers.",
        )
        return

    subject_id = int(subject_text)

    # --------------------------------------------------------
    # Visit
    # --------------------------------------------------------

    visit_text = visit_var.get()

    if visit_text not in ["1", "2", "3"]:
        messagebox.showerror(
            "Invalid Visit",
            "Select visit 1, 2, or 3.",
        )
        return

    visit_number = int(visit_text)

    # --------------------------------------------------------
    # Counterbalance
    # --------------------------------------------------------

    counterbalance = counter_var.get()

    if counterbalance not in COUNTERBALANCE:
        messagebox.showerror(
            "Missing Counterbalance",
            "Select counterbalance A-F.",
        )
        return

    # --------------------------------------------------------
    # Generate
    # --------------------------------------------------------

    try:

        result = create_protocol(
            subject_id,
            visit_number,
            counterbalance,
        )

        # ----------------------------------------------------
        # Clear output
        # ----------------------------------------------------

        output_text.delete(
            "1.0",
            tk.END,
        )

        # ----------------------------------------------------
        # Display information
        #
        # IMPORTANT:
        # Do not display hidden_condition.
        # ----------------------------------------------------

        output_text.insert(
            tk.END,
            f"Subject ID: {subject_id}\n"
            f"Visit: {visit_number}\n\n"
        )

        output_text.insert(
            tk.END,
            "Theta/Beta report used:\n"
            f"{result['txt']}\n\n"
        )

        output_text.insert(
            tk.END,
            "Extracted frequency estimates:\n"
            f"Theta peak: {result['theta']:.2f} Hz\n"
            f"Beta peak:  {result['beta']:.2f} Hz\n\n"
        )


        output_text.insert(
            tk.END,
            "Generated protocols:\n"
        )

        for output_file in result["outputs"]:
            output_text.insert(
                tk.END,
                f"{output_file}\n"
            )

        output_text.insert(
            tk.END,
            "\nProtocol generation complete."
        )

        messagebox.showinfo(
            "Complete",
            "Protocols generated successfully.",
        )

    except Exception as e:

        messagebox.showerror(
            "Error",
            str(e),
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
    font=("Arial", 11),
).pack(
    pady=(15, 5)
)

subject_entry = tk.Entry(
    root,
    width=20,
    font=("Arial", 11),
)

subject_entry.pack()


# ============================================================
# VISIT
# ============================================================

tk.Label(
    root,
    text="Visit:",
    font=("Arial", 11),
).pack(
    pady=(15, 5)
)

visit_var = tk.StringVar()

visit_dropdown = ttk.Combobox(
    root,
    textvariable=visit_var,
    values=["1", "2", "3"],
    state="readonly",
    width=17,
)

visit_dropdown.pack()


# ============================================================
# COUNTERBALANCE
# ============================================================

tk.Label(
    root,
    text="Counterbalance Group:",
    font=("Arial", 11),
).pack(
    pady=(15, 5)
)

counter_var = tk.StringVar()

counter_dropdown = ttk.Combobox(
    root,
    textvariable=counter_var,
    values=["A", "B", "C", "D", "E", "F"],
    state="readonly",
    width=17,
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
    height=2,
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
    font=("Consolas", 10),
)

output_text.pack(
    padx=15,
    pady=10
)


# ============================================================
# START GUI
# ============================================================

root.mainloop()