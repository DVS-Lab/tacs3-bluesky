import os
from psychopy import visual, core, event, gui
import random
import csv
import numpy as np  # Needed for exponential and rescaling

# Screen parameters
useFullScreen = True
useDualScreen = 1
DEBUG = False

#  SETUP
info = {'Subject Number': ''}
dlg = gui.DlgFromDict(info, title="Stop Signal Task with Gambling")
if not dlg.OK:
    core.quit()

sub_number = info['Subject Number']
script_dir = os.path.dirname(os.path.realpath(__file__))

#  WINDOW AND STIMULI
win = visual.Window(size=(1200, 900), color='grey', fullscr=True,
                    units='pix', screen=useDualScreen, allowGUI=False)

# Preload ImageStim objects AFTER window creation
image_stimuli = {
    'left': visual.ImageStim(win, image=os.path.join(script_dir, 'images', 'left_arrow.png'), size=(518, 300)),
    'right': visual.ImageStim(win, image=os.path.join(script_dir, 'images', 'right_arrow.png'), size=(518, 300)),
    'left_red': visual.ImageStim(win, image=os.path.join(script_dir, 'images', 'left_red_arrow.png'), size=(518, 300)),
    'right_red': visual.ImageStim(win, image=os.path.join(script_dir, 'images', 'right_red_arrow.png'), size=(518, 300))
}

fixation = visual.TextStim(win, text='+', height=40)

total_bonus = 0

# Output directory
log_dir = os.path.join(script_dir, 'logs', f'sub-{sub_number}')
os.makedirs(log_dir, exist_ok=True)

#  EXPONENTIAL SAMPLES WITH FIXED TOTAL
def sample_scaled_exp_durations(n, total_duration, low, high, scale):
    while True:
        samples = np.random.exponential(scale=scale, size=n * 10)
        clipped = samples[(samples >= low) & (samples <= high)]
        if len(clipped) >= n:
            clipped = clipped[:n]
            clipped = np.array(clipped)
            scaled = clipped / clipped.sum() * total_duration
            if np.all((scaled >= low) & (scaled <= high)):
                return list(scaled)

for run_number in range(1, 4):

    # ---------- Per-run setup ----------
    results = []
    fieldnames = [
        'trialNumber', 'bet', 'stim_onset', 'stop_onset',
        'stimulus_offset', 'stop_offset', 'duration',
        'stimulus', 'stop', 'response', 'rt', 'stim_file', 'ssd',
        'fixation_onset', 'fixation_offset',
        'isi_onset', 'isi_offset', 'iti_onset', 'iti_offset',
        'go_correct', 'go_incorrect', 'go_miss', 'stop_success',
        'stop_failure_arrowcorrect'
    ]
    base = os.path.join(log_dir, f"sub-{sub_number}_task-SST_run-{run_number}_events")
    tsv_filename = base + ".tsv"
    csv_filename = base + ".csv"

    def write_events(path, delimiter):
        with open(path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=delimiter)
            writer.writeheader()
            for r in results:
                writer.writerow(r)

    def save_and_quit():
        write_events(tsv_filename, '\t')
        write_events(csv_filename, ',')
        win.close()
        core.quit()

    #  INSTRUCTIONS (run 1 only)
    if run_number == 1:
        instruction_texts = [
            "Welcome to the Stop-Signal Task!\n\nPress the blue button with your index finger to continue.",
            
            "Your task is to respond to the black arrows that appear on the screen.",
            
            "Press the blue button with your index finger when you see a LEFT ARROW.\n\nPress the yellow button with your middle finger when you see a RIGHT ARROW.",
            
            "Respond as QUICKLY and ACCURATELY as possible when you see the black arrow.",
            
            "On about one third of trials, a RED ARROW will appear shortly after the black one.\n\nWhen this happens, try to STOP your response.",
            
            "Sometimes the red arrow will appear quickly, and be easier to stop.\n\nOther times it will appear later and be harder to stop.\n\nThis is normal - just do your best.",
            
            "Do not wait for the red arrow to appear.\n\nAlways respond as quickly as possible to the black arrow.\n\nThe red arrow is unpredictable.",
            
            "At the beginning of each round, you will be given the option to bet a portion of your $20 endowment.",
            
            "To be eligible for the bonus that round, you must:\n\n- Respond correctly on at least 90% of black arrow trials\n\n- Successfully stop on at least 50% of red arrow trials\n\n- Keep your average response time under 500ms on black arrow trials\n\nIf you meet all criteria, your bet will be doubled.",
            
            "If you don't bet your entire $20 endowment, the remaining amount will automatically be added to your bonus payment.",
            
            "On the next screen, you will be asked how much you would like to bet.\n\nDo you have any questions?"
        ]
        for text in instruction_texts:
            instruction = visual.TextStim(win, text=text, color='white', height=36, wrapWidth=700)
            instruction.draw()
            win.flip()
            event.clearEvents()
            while True:
                keys = event.getKeys()
                if '1' in keys:
                    break
                elif 'z' in keys:
                    save_and_quit()

    #  CRITERIA REMINDER (runs 2 and 3)
    if run_number > 1:
        reminder_text = (
            "Reminder: To win your bet, you must meet ALL of the following criteria:\n\n"
            "• Respond correctly on at least 90% of black arrow (go) trials\n\n"
            "• Successfully stop on at least 50% of red arrow (stop) trials\n\n"
            "• Keep your average response time under 500 ms on go trials\n\n"
            "If you meet all criteria, your bet will be doubled.\n\n"
            "Press the blue button to continue."
        )
        reminder = visual.TextStim(win, text=reminder_text, color='white', height=32, wrapWidth=700)
        reminder.draw()
        win.flip()
        event.clearEvents(eventType='keyboard')
        while True:
            keys = event.getKeys()
            if '1' in keys:
                break
            elif 'z' in keys:
                save_and_quit()

    #  GAMBLING CHOICE
    title = visual.TextStim(win, text="How much would you like to bet for this round?",
                            color='white', height=36, pos=(0, 120))
    opt0  = visual.TextStim(win, text="$0",  color='white', height=48, pos=(-220, 40))
    opt10 = visual.TextStim(win, text="$10", color='white', height=48, pos=(0, 40))
    opt20 = visual.TextStim(win, text="$20", color='white', height=48, pos=(220, 40))
    prompt = visual.TextStim(win, text="Press:", color='white', height=28, pos=(0, -40))
    lab_pointer = visual.TextStim(win, text="Pointer (Blue)",  color='blue', height=28, pos=(0, -90))
    lab_middle  = visual.TextStim(win, text="Middle (Yellow)", color='yellow', height=28, pos=(0, -130))
    lab_ring    = visual.TextStim(win, text="Ring (Green)",    color='green', height=28, pos=(0, -170))

    for stim in (title, opt0, opt10, opt20, prompt, lab_pointer, lab_middle, lab_ring):
        stim.draw()
    win.flip()

    gamble_key_map = {'1': 0, '2': 10, '3': 20}
    opt_by_key = {'1': opt0, '2': opt10, '3': opt20}
    event.clearEvents(eventType='keyboard')

    gamble_choice = None
    while gamble_choice not in gamble_key_map:
        keys = event.getKeys(keyList=['1', '2', '3', 'z'])
        if not keys:
            continue
        if 'z' in keys:
            save_and_quit()
        for k in keys:
            if k in gamble_key_map:
                gamble_choice = k
                break

    selected_opt = opt_by_key[gamble_choice]
    prev_color = selected_opt.color
    selected_opt.color = 'orange'
    for stim in (title, opt0, opt10, opt20, prompt, lab_pointer, lab_middle, lab_ring):
        stim.draw()
    win.flip()
    core.wait(0.5)
    selected_opt.color = prev_color
    bet = gamble_key_map[gamble_choice]

    # PARAMETERS
    n_trials = 74
    stop_prob = 0.30
    response_keys = ['1', '2']
    exit_key = 'z'
    ssd = 0.25
    ssd_step = 0.05
    min_ssd = 0.05
    max_ssd = 0.9

    # Sample ISI/ITI durations with fixed totals
    total_isi_time = 126.0
    total_iti_time = 252.0
    isi_values = sample_scaled_exp_durations(n_trials, total_isi_time, 0.8075, 2.4225, scale=0.5)
    iti_values = sample_scaled_exp_durations(n_trials, total_iti_time, 0.8075, 7.2675, scale=1.5)

    # Build trial list
    trials = []
    for _ in range(n_trials):
        direction = random.choice(['left', 'right'])
        is_stop = random.random() < stop_prob
        trials.append({'direction': direction, 'is_stop': is_stop})

    # Precompute trial schedule (anchored)
    trial_schedule = []
    t = 0
    for i in range(n_trials):
        isi_dur = isi_values.pop()
        iti_dur = iti_values.pop()
        t += isi_dur
        trial_schedule.append({
            'onset': t,
            'isi': isi_dur,
            'iti': iti_dur,
            'trial': trials[i]
        })
        t += 1.5
        t += iti_dur
    run_duration = t
    print(f"Run {run_number} scheduled duration: {run_duration:.3f} sec")

    # Tracking
    stop_trials = 0
    successful_stops = 0
    correct_go_trials = 0
    total_go_trials = 0
    rt_list = []
    trial_number = 0

    # WAIT FOR START
    start_msg = visual.TextStim(win,
        text="Please wait for this round of the game to begin.\n\n Remember to keep your head still, and respond as soon as you see the black arrow.\n\nDo not wait for the red arrow to appear.",
        color='white', height=36)
    start_msg.draw()
    win.flip()

    key = event.waitKeys(keyList=('equal', 'z'))[0]
    if key == 'z':
        save_and_quit()

    global_clock = core.Clock()
    fixation.draw()
    win.flip()

    # TRIAL LOOP
    for sched in trial_schedule:
        trial_number += 1
        trial = sched['trial']

        # --- ISI (fixation cross for full isi_dur) ---
        isi_onset = global_clock.getTime()
        fixation_onset = isi_onset
        fixation.draw()
        win.flip()
        while global_clock.getTime() < isi_onset + sched['isi']:
            fixation.draw()
            win.flip()
            if exit_key in event.getKeys():
                save_and_quit()
        isi_offset = global_clock.getTime()
        fixation_offset = isi_offset


        # --- Stimulus ---
        direction = trial['direction']
        is_stop = trial['is_stop']
        go_stim = image_stimuli[direction]
        stop_stim = image_stimuli[f"{direction}_red"]

        go_stim.draw()
        win.flip()
        stim_onset = global_clock.getTime()
        trial_clock = core.Clock()


        responded = False
        response_key = ''
        rt = None
        stop_presented = False
        stop_onset = ''
        response_onset = ''

        while trial_clock.getTime() < 1.5:
            keys = event.getKeys(keyList=response_keys + [exit_key], timeStamped=trial_clock)
            if keys:
                for key, timestamp in keys:
                    if key == exit_key:
                        save_and_quit()
                    else:
                        responded = True
                        response_key = key
                        rt = timestamp
                        response_onset = global_clock.getTime()
                        break
                if responded:
                    break
            if is_stop and not stop_presented and trial_clock.getTime() >= ssd:
                stop_stim.draw()
                win.flip()
                stop_onset = global_clock.getTime()
                stop_presented = True

        # ITI until next onset
        iti_onset = global_clock.getTime()
        stimulus_offset = iti_onset
        stop_offset = iti_onset if stop_presented else ''
        next_onset = None
        idx = trial_number
        if idx < len(trial_schedule):
            next_onset = trial_schedule[idx]['onset']
        else:
            next_onset = run_duration
        while global_clock.getTime() < next_onset:
            fixation.draw()  # Add this line
            win.flip()
            if exit_key in event.getKeys():
                save_and_quit()
        iti_offset = global_clock.getTime()

        # Outcomes
        expected_key = '1' if direction == 'left' else '2'
        go_correct = 0
        go_incorrect = 0
        go_miss = 0
        stop_success = 0
        stop_failure_arrowcorrect = ''
        if is_stop:
            stop_trials += 1
            if not responded:
                successful_stops += 1
                ssd = min(max_ssd, ssd + ssd_step)
                stop_success = 1
            else:
                ssd = max(min_ssd, ssd - ssd_step)
                stop_success = 0
                stop_failure_arrowcorrect = (response_key == expected_key)
        else:
            total_go_trials += 1
            if responded:
                if response_key == expected_key:
                    go_correct = 1
                    correct_go_trials += 1
                    rt_list.append(rt)
                else:
                    go_incorrect = 1
            else:
                go_miss = 999

        duration_val = float(rt) if rt is not None else 1.5
        results.append({
            'trialNumber': trial_number,
            'bet': bet,
            'stim_onset': stim_onset,
            'stop_onset': stop_onset,
            'stimulus_offset': stimulus_offset,
            'stop_offset': stop_offset,
            'duration': round(duration_val, 3),
            'stimulus': direction,
            'stop': int(is_stop),
            'response': responded,
            'rt': rt if rt is not None else '',
            'stim_file': os.path.join(script_dir, 'images', f"{direction}_arrow.png"),
            'ssd': round(ssd, 3),
            'fixation_onset': fixation_onset,
            'fixation_offset': fixation_offset,
            'isi_onset': isi_onset,
            'isi_offset': isi_offset,
            'iti_onset': iti_onset,
            'iti_offset': iti_offset,
            'go_correct': go_correct,
            'go_incorrect': go_incorrect,
            'go_miss': go_miss,
            'stop_success': stop_success,
            'stop_failure_arrowcorrect': stop_failure_arrowcorrect
        })

    # Calculate performance metrics
    mean_rt = (sum(rt_list) / len(rt_list) * 1000) if rt_list else 999
    go_accuracy = (correct_go_trials / total_go_trials) * 100 if total_go_trials > 0 else 0
    stop_accuracy = (successful_stops / stop_trials) * 100 if stop_trials > 0 else 0

    # Check each criterion (matching instructions)
    go_accuracy_met = go_accuracy >= 90
    stop_accuracy_met = stop_accuracy >= 50
    rt_met = mean_rt < 500

    # Determine winnings based on all criteria
    all_criteria_met = go_accuracy_met and stop_accuracy_met and rt_met
    if all_criteria_met and bet > 0:
        winnings = bet * 2
    else:
        winnings = 0
    
    # Add unbet amount to bonus
    unbet_amount = 20 - bet
    total_bonus += winnings + unbet_amount

    # Save events
    write_events(tsv_filename, '\t')
    write_events(csv_filename, ',')

    # Feedback screens
    if run_number < 3:
        hold_text = visual.TextStim(win, text="+",
                                    color='white', height=40)
        hold_text.draw()
        win.flip()
        event.clearEvents(eventType='keyboard')
        keys = event.waitKeys(keyList=['space', 'z'])
        if keys and 'z' in keys:
            save_and_quit()

        # Build feedback message
        summary_text = f"End of Run {run_number}.\n\n"
        summary_text += f"Average response time: {mean_rt:.0f} ms (target: < 500 ms) "
        summary_text += "✓\n" if rt_met else "✗\n"
        summary_text += f"Go Accuracy: {go_accuracy:.1f}% (target: ≥ 90%) "
        summary_text += "✓\n" if go_accuracy_met else "✗\n"
        summary_text += f"Stop Accuracy: {stop_accuracy:.1f}% (target: ≥ 50%) "
        summary_text += "✓\n\n" if stop_accuracy_met else "✗\n\n"

        if bet == 0:
            summary_text += "You did not place a bet this round.\n"
        elif all_criteria_met:
            summary_text += f"Congratulations! You met all criteria.\n"
            summary_text += f"Your ${bet} bet was doubled to ${winnings}!\n"
        else:
            summary_text += f"You did not win your ${bet} bet.\n"
            missed_reasons = []
            if not go_accuracy_met:
                missed_reasons.append(f"Go accuracy was below 90%")
            if not stop_accuracy_met:
                missed_reasons.append(f"Stop accuracy was below 50%")
            if not rt_met:
                missed_reasons.append(f"Average response time was 500 ms or slower")
            summary_text += "Reason(s): " + "; ".join(missed_reasons) + "\n"

        summary = visual.TextStim(win, text=summary_text, color='white', height=32, wrapWidth=800)
        summary.draw()
        win.flip()
        event.clearEvents(eventType='keyboard')
        keys = event.waitKeys(maxWait=20, keyList=['space', 'z'])
        if keys and 'z' in keys:
            save_and_quit()

        inter_text = visual.TextStim(win,
            text="The next round is about to begin. Do you have any questions?",
            color='white', height=36)
        inter_text.draw()
        win.flip()
        event.clearEvents(eventType='keyboard')
        keys = event.waitKeys(maxWait=20, keyList=['space', 'z'])
        if keys and 'z' in keys:
            save_and_quit()
    else:
        # Final run feedback
        summary_text = f"End of Run {run_number}.\n\n"
        summary_text += f"Average response time: {mean_rt:.0f} ms (target: < 500 ms) "
        summary_text += "✓\n" if rt_met else "✗\n"
        summary_text += f"Go Accuracy: {go_accuracy:.1f}% (target: ≥ 90%) "
        summary_text += "✓\n" if go_accuracy_met else "✗\n"
        summary_text += f"Stop Accuracy: {stop_accuracy:.1f}% (target: ≥ 50%) "
        summary_text += "✓\n\n" if stop_accuracy_met else "✗\n\n"

        if bet == 0:
            summary_text += "You did not place a bet this round.\n"
        elif all_criteria_met:
            summary_text += f"Congratulations! You met all criteria.\n"
            summary_text += f"Your ${bet} bet was doubled to ${winnings}!\n"
        else:
            summary_text += f"You did not win your ${bet} bet.\n"
            missed_reasons = []
            if not go_accuracy_met:
                missed_reasons.append(f"Go accuracy was below 90%")
            if not stop_accuracy_met:
                missed_reasons.append(f"Stop accuracy was below 50%")
            if not rt_met:
                missed_reasons.append(f"Average response time was 500 ms or slower")
            summary_text += "Reason(s): " + "; ".join(missed_reasons) + "\n"

        summary = visual.TextStim(win, text=summary_text, color='white', height=32, wrapWidth=800)
        summary.draw()
        win.flip()
        event.clearEvents(eventType='keyboard')
        keys = event.waitKeys(maxWait=20, keyList=['space', 'z'])
        if keys and 'z' in keys:
            save_and_quit()

        final_msg = visual.TextStim(
            win,
            text="You have completed the final run of the Stop-Signal Task.\n\nYour bonuses will be calculated after the visit!",
            color='white', height=36
        )
        final_msg.draw()
        win.flip()
        event.clearEvents(eventType='keyboard')
        keys = event.waitKeys(maxWait=20, keyList=['space', 'z'])
        if keys and 'z' in keys:
            save_and_quit()
        win.close()
        core.quit()