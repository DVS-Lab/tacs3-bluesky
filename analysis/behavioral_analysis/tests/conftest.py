import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def config():
    return json.loads(Path(__file__).parents[1].joinpath("config.json").read_text())


def main_sst(n=91, initial=.25):
    state = initial
    rows = []
    nstop = 0
    for i in range(n):
        stop = i % 3 == 0
        response = True
        used = state
        if stop:
            response = nstop % 2 == 1
            nstop += 1
            state = np.clip(state + (-.05 if response else .05), .05, .9)
        stim = 1790000000 + 5 * i
        early = stop and response
        rows.append(dict(trialNumber=i + 1, stop=int(stop), response=response,
                         rt=.2 if early else .6 if response else "", ssd=round(state, 3),
                         stim_onset=stim, stop_onset=stim + used if stop and not early else "",
                         iti_offset=stim + 4, run_start_unix=1790000000,
                         go_correct=int(not stop and response), go_miss=0 if response or stop else 999,
                         stop_success=int(stop and not response), source_file="synthetic"))
    return pd.DataFrame(rows).astype(str)


def bandit_frame(choices=(1, 1, 2, 2, 1), rewards=(True, False, False, True, True)):
    n = len(choices)
    return pd.DataFrame(dict(trial_num=range(1, n + 1), choice=choices, reward=rewards,
                             flower1=[10] * n, flower2=[20] * n, current_good=[10] * n,
                             rt=[500] * n, source_file=["synthetic"] * n))
