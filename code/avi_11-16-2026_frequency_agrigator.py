
import re
import pandas as pd
from pathlib import Path

# Folder containing the theta-beta text files
FOLDER = Path(
    "/Users/avidachs/Documents/GitHub/tacs3-bluesky/"
    "stimulation/calculated-theta-beta"
)

results = []

def extract_frequency(pattern, text):
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


# Process every text file
for file_path in FOLDER.glob("*.txt"):

    text = file_path.read_text(encoding="utf-8")

    # Extract subject ID and session from filename
    subject_match = re.match(r"^(G?\d+)-(\d+)", file_path.name)

    if not subject_match:
        print(f"Skipping unrecognized filename: {file_path.name}")
        continue

    subject_id = subject_match.group(1)
    session = int(subject_match.group(2))

    # Extract frequencies
    specparam_theta = extract_frequency(
        r"Specparam theta:\s*([0-9.]+)\s*Hz",
        text
    )

    tfr_theta = extract_frequency(
        r"TFR theta:\s*([0-9.]+)\s*Hz",
        text
    )

    iaf5_theta = extract_frequency(
        r"IAF-5 theta:\s*([0-9.]+)\s*Hz",
        text
    )

    tfr_beta = extract_frequency(
        r"TFR beta ERD:\s*([0-9.]+)\s*Hz",
        text
    )

    results.append({
        "Subject ID": subject_id,
        "Session": session,
        "Specparam Theta": specparam_theta,
        "TFR Theta": tfr_theta,
        "IAF-5 Theta": iaf5_theta,
        "TFR Beta": tfr_beta
    })


# Create DataFrame
df = pd.DataFrame(results)

# Sort by subject ID and session
df["_sort"] = df["Subject ID"].str.replace(
    "G", "", regex=False
).astype(int)

df = (
    df.sort_values(["_sort", "Session"])
      .drop(columns="_sort")
      .reset_index(drop=True)
)

# Save CSV
output_file = FOLDER / "combined_theta_beta_frequencies.csv"
df.to_csv(output_file, index=False)

# Display results
print(df.to_string(index=False))

print(f"\nSaved to: {output_file}")
print(f"Total rows: {len(df)}")
print(f"Unique subjects: {df['Subject ID'].nunique()}")
