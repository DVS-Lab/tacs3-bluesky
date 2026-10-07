import pandas as pd
import os
import glob
import re
import csv
import random
from typing import Dict, Tuple, Optional, Any

def save_results_to_csv(participant_id: str, task_name: str, run_results: Dict, total_bonus: float, base_path: Optional[str] = None) -> str:
    """
    Save participant results to CSV file in /stimuli/bonuses/.
    """
    print(f"Starting CSV save for participant {participant_id} - {task_name} task")

    if base_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = script_dir

    bonuses_dir = os.path.join(base_path, "stimuli", "bonuses", f"{participant_id}")
    os.makedirs(bonuses_dir, exist_ok=True)

    csv_filename = os.path.join(bonuses_dir, f"sub-{participant_id}_{task_name}.csv")
    print(f"CSV filename will be: {csv_filename}")

    csv_data = []

    if task_name == 'SST':
        csv_data.append([
            'participant_id',
            'run',
            'bet_amount',
            'amount_kept',
            'avg_rt',
            'go_accuracy',
            'stop_accuracy',
            'meets_rt_criteria',
            'meets_go_accuracy_criteria',
            'meets_stop_accuracy_criteria',
            'wins_bet',
            'bet_winnings',
            'run_bonus',
            'error'
        ])

        for run_num in sorted(run_results.keys()):
            run_data = run_results[run_num]
            csv_data.append([
                participant_id,
                run_num,
                run_data['bet_amount'],
                round(run_data.get('amount_kept', 0), 2),
                round(run_data['avg_rt'], 3) if run_data.get('avg_rt') is not None else '',
                round(run_data['go_accuracy'], 1) if run_data.get('go_accuracy') is not None else '',
                round(run_data['stop_accuracy'], 1) if run_data.get('stop_accuracy') is not None else '',
                run_data['meets_rt_criteria'],
                run_data.get('meets_go_accuracy_criteria', False),
                run_data.get('meets_stop_accuracy_criteria', False),
                run_data['wins_bet'],
                round(run_data.get('bet_winnings', 0), 2),
                round(run_data['final_bonus'], 2),
                run_data['error'] if run_data.get('error') else ''
            ])

    elif task_name == 'Bandit':
        csv_data.append([
            'participant_id',
            'compensation',
            'error'
        ])
        csv_data.append([
            participant_id,
            round(total_bonus, 2),
            ''
        ])

    csv_data.append([
        participant_id,
        'TOTAL',
        *([''] * max(0, len(csv_data[0]) - 3)),
        round(total_bonus, 2),
        ''
    ])

    with open(csv_filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerows(csv_data)

    print(f"Results saved to: {csv_filename}")
    print(f"Full path: {os.path.abspath(csv_filename)}")
    return csv_filename


def calculate_sst_run_bonus(df: pd.DataFrame, bet_amount: float) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Calculate bonus for one SST run.

    Criteria are unchanged from the current script:
    - Go trial accuracy > 90%
    - Stop trial accuracy >= 50%
    - Average RT <= 500ms (0.5 seconds)

    Updated compensation:
    - Each run has a $10 endowment.
    - The participant keeps the $10 they did not bet.
    - If all three criteria are met, the bet is doubled.
      Therefore:
          $0 bet -> $10
          $5 bet -> $15
          $10 bet -> $20
    """
    initial_endowment = 10.0

    if bet_amount not in (0.0, 5.0, 10.0):
        return None, "Invalid bet amount; expected $0, $5, or $10"

    # Check average RT - only for trials where participants responded.
    rt_data = df['rt'].dropna()
    if rt_data.empty:
        return None, "Missing or invalid RT data"
    avg_rt = rt_data.mean()

    # Check for required columns.
    if 'stop' not in df.columns:
        return None, "Missing 'stop' column to identify trial types"
    if 'go_correct' not in df.columns or 'stop_success' not in df.columns:
        return None, "Missing required columns (need go_correct and stop_success)"

    # Calculate go trial accuracy.
    go_trials = df[df['stop'] == 0]
    if len(go_trials) == 0:
        return None, "No go trials found"

    correct_go_trials = go_trials['go_correct'].sum()
    total_go_trials = len(go_trials)
    go_accuracy = (correct_go_trials / total_go_trials) * 100

    # Calculate stop trial accuracy.
    stop_trials = df[df['stop'] == 1]
    if len(stop_trials) == 0:
        return None, "No stop trials found"

    successful_stops = stop_trials['stop_success'].sum()
    total_stop_trials = len(stop_trials)
    stop_accuracy = (successful_stops / total_stop_trials) * 100

    print(f"  Go trials: {int(correct_go_trials)}/{total_go_trials} = {go_accuracy:.1f}%")
    print(f"  Stop trials: {int(successful_stops)}/{total_stop_trials} = {stop_accuracy:.1f}%")

    # Same three criteria as the current script.
    meets_rt = avg_rt <= 0.5
    meets_go_acc = go_accuracy > 90.0
    meets_stop_acc = stop_accuracy >= 50.0
    wins_bet = meets_rt and meets_go_acc and meets_stop_acc

    print(f"  Average RT: {avg_rt:.3f}s (meets <=0.5s: {meets_rt})")
    print(f"  Go accuracy: {go_accuracy:.1f}% (meets >90%: {meets_go_acc})")
    print(f"  Stop accuracy: {stop_accuracy:.1f}% (meets >=50%: {meets_stop_acc})")

    # Participant keeps whatever was not bet.
    amount_kept = initial_endowment - bet_amount

    # If all criteria are met, the bet is doubled.
    bet_winnings = bet_amount * 2 if wins_bet else 0.0
    final_bonus = amount_kept + bet_winnings

    if wins_bet:
        print(
            f"  Result: WON BET "
            f"(kept ${amount_kept:.2f} + doubled bet ${bet_winnings:.2f} "
            f"= ${final_bonus:.2f})"
        )
    else:
        print(
            f"  Result: LOST/NO WIN "
            f"(kept unbet amount ${amount_kept:.2f} = ${final_bonus:.2f})"
        )

    return {
        'bet_amount': bet_amount,
        'avg_rt': avg_rt,
        'go_accuracy': go_accuracy,
        'stop_accuracy': stop_accuracy,
        'meets_rt_criteria': meets_rt,
        'meets_go_accuracy_criteria': meets_go_acc,
        'meets_stop_accuracy_criteria': meets_stop_acc,
        'wins_bet': wins_bet,
        'amount_kept': amount_kept,
        'bet_winnings': bet_winnings,
        'final_bonus': final_bonus,
        'error': None
    }, None


def process_bandit_task(participant_id: str, base_path: Optional[str] = None) -> float:
    """
    Pay $5 for each completed Bandit run, up to 6 runs ($30 maximum).

    Expected location:
        [script folder]/data/sub-[participant_id]/

    Expected filename pattern:
        sub-[participant_id]_ses-1_run-01_task-bandit_DATE
        ...
        sub-[participant_id]_ses-3_run-02_task-bandit_DATE
    """
    max_runs = 6
    bonus_per_run = 5.0

    if base_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.join(script_dir, "data")

    participant_dir = os.path.join(base_path, f"sub-{participant_id}")
    pattern = f"sub-{participant_id}_ses-*task-bandit_*"
    files = glob.glob(os.path.join(participant_dir, pattern))

    filename_re = re.compile(
        rf"^sub-{re.escape(participant_id)}_ses-(\d+)_run-(\d+)_task-bandit_"
    )

    valid_files = {}
    for file in files:
        filename = os.path.basename(file)
        match = filename_re.match(filename)
        if not match:
            continue

        session = int(match.group(1))
        run = int(match.group(2))
        if session not in (1, 2, 3) or run not in (1, 2):
            continue

        key = (session, run)
        if key in valid_files:
            print(f"WARNING: duplicate Bandit file for session {session}, run {run}; using first match.")
            continue
        valid_files[key] = file

    completed_runs = min(len(valid_files), max_runs)
    total_bonus = completed_runs * bonus_per_run

    print(f"Processing Bandit task for participant {participant_id}")
    print(f"Looking in: {participant_dir}")
    print(f"Found {completed_runs} completed Bandit run(s).")
    if completed_runs < max_runs:
        print(f"WARNING: {max_runs - completed_runs} possible Bandit run(s) not found.")

    for session, run in sorted(valid_files):
        print(f"  Session {session}, Run {run}: ${bonus_per_run:.2f}")

    try:
        save_results_to_csv(
            participant_id, "Bandit",
            {"completed_runs": completed_runs, "error": None},
            total_bonus
        )
    except Exception as e:
        print(f"Error saving Bandit task CSV: {e}")

    print(f"BANDIT TASK TOTAL BONUS: ${total_bonus:.2f}")
    return total_bonus


def process_sst_task(participant_id: str, base_path: Optional[str] = None) -> float:
    """
    Process any completed SST runs, up to 6.

    Both filename forms are accepted:
        ses-X-run-Y
        ses-X_run-Y
    """
    max_runs = 6

    if base_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.join(script_dir, "data")

    participant_dir = os.path.join(base_path, f"sub-{participant_id}")
    # Search broadly for this participant's files first, then use a regex
    # to identify SST files. New SST files use "task-SST".
    #
    # Accepted filename formats include:
    #   sub-10166_ses-1_run-1_task-SST_2026-10-01_18-24-36_events.csv
    #   sub-10166_ses-1-run-1_task-SST_2026-10-01_18-24-36_events.csv
    #
    # The date/time portion and file extension may vary.
    pattern = f"sub-{participant_id}_*"
    files = glob.glob(os.path.join(participant_dir, pattern))

    filename_re = re.compile(
        rf"^sub-{re.escape(participant_id)}_ses-(\d+)(?:-|_)run-(\d+)_task-SST(?:_|-)"
    )

    valid_files = {}
    for file in files:
        filename = os.path.basename(file)
        match = filename_re.match(filename)
        if not match:
            continue

        session = int(match.group(1))
        run = int(match.group(2))
        if session not in (1, 2, 3) or run not in (1, 2):
            continue

        key = (session, run)
        if key in valid_files:
            print(f"WARNING: duplicate SST file for session {session}, run {run}; using first match.")
            continue
        valid_files[key] = file

    if not valid_files:
        print(f"No SST task files found for participant {participant_id} in {participant_dir}")
        return 0.0

    if len(valid_files) < max_runs:
        print(f"WARNING: {max_runs - len(valid_files)} possible SST run(s) not found; calculating completed runs only.")

    total_bonus = 0.0
    run_results = {}

    for (session, run), file in sorted(valid_files.items()):
        filename = os.path.basename(file)
        print(f"\nSESSION {session}, RUN {run}: {filename}")

        try:
            df = pd.read_csv(file)

            if 'bet' in df.columns:
                bet_data = df['bet'].dropna()
                bet_amount = float(bet_data.iloc[0]) if not bet_data.empty else 0.0
            else:
                bet_amount = 0.0

            if bet_amount not in (0.0, 5.0, 10.0):
                raise ValueError(f"Invalid bet amount ${bet_amount}; expected $0, $5, or $10")

            result, error = calculate_sst_run_bonus(df, bet_amount)

            if error:
                print(f"  ERROR: {error}")
                amount_kept = 10.0 - bet_amount
                result = {
                    'bet_amount': bet_amount,
                    'amount_kept': amount_kept,
                    'avg_rt': None,
                    'go_accuracy': None,
                    'stop_accuracy': None,
                    'meets_rt_criteria': False,
                    'meets_go_accuracy_criteria': False,
                    'meets_stop_accuracy_criteria': False,
                    'wins_bet': False,
                    'bet_winnings': 0.0,
                    'final_bonus': amount_kept,
                    'error': error
                }

            result['session'] = session
            result['run'] = run
            run_results[(session, run)] = result
            total_bonus += result['final_bonus']
            print(f"  Run bonus: ${result['final_bonus']:.2f}")

        except Exception as e:
            print(f"  ERROR processing {filename}: {e}")
            run_results[(session, run)] = {
                'session': session,
                'run': run,
                'bet_amount': 0.0,
                'amount_kept': 10.0,
                'avg_rt': None,
                'go_accuracy': None,
                'stop_accuracy': None,
                'meets_rt_criteria': False,
                'meets_go_accuracy_criteria': False,
                'meets_stop_accuracy_criteria': False,
                'wins_bet': False,
                'bet_winnings': 0.0,
                'final_bonus': 10.0,
                'error': str(e)
            }
            total_bonus += 10.0

    print(f"\nSST RUNS PROCESSED: {len(run_results)} of {max_runs}")
    print(f"SST TASK TOTAL BONUS: ${total_bonus:.2f}")

    try:
        save_results_to_csv(participant_id, 'SST', run_results, total_bonus, None)
    except Exception as e:
        print(f"Error saving SST task CSV: {e}")

    return total_bonus


def process_participant_all_tasks(
    participant_id: str,
    base_path: Optional[str] = None,
    seed: Optional[int] = None,
    tasks: Optional[list] = None
) -> Dict[str, float]:
    """
    Process the two-armed Bandit and SST tasks for a participant.
    """
    if tasks is None:
        tasks = ['Bandit', 'SST']

    results = {}
    total_all_tasks = 0.0

    print(f"\nProcessing ALL TASKS for participant {participant_id}")
    print("=" * 80)

    if 'Bandit' in tasks:
        bandit_bonus = process_bandit_task(participant_id, base_path)
        results['Bandit'] = bandit_bonus
        total_all_tasks += bandit_bonus
        print()

    if 'SST' in tasks:
        sst_bonus = process_sst_task(participant_id, base_path)
        results['SST'] = sst_bonus
        total_all_tasks += sst_bonus

    results['Total'] = total_all_tasks

    print("\n" + "=" * 80)
    print("FINAL SUMMARY:")
    for task, bonus in results.items():
        if task != 'Total':
            print(f"{task} Task Total: ${bonus:.2f}")
    print(f"GRAND TOTAL ACROSS ALL TASKS: ${total_all_tasks:.2f}")
    print("Maximum possible total if all 6 Bandit and all 6 SST runs are completed: $150.00")
    print("=" * 80)

    return results


if __name__ == "__main__":
    participant_id = "10166"  # change as needed

    # Optional: specify which tasks to process.
    tasks_to_process = ['Bandit', 'SST']

    results = process_participant_all_tasks(
        participant_id,
        tasks=tasks_to_process
    )

    # You can also process individual tasks:
    # bandit_bonus = process_bandit_task(participant_id)
    # sst_bonus = process_sst_task(participant_id)

