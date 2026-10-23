#!/usr/bin/env python3
"""Recreate the carrier-recovery figure from checked-in result artifacts."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]

def main():
    folder=ROOT/'validation/carrier_validation_v1_2'
    rr=json.loads((folder/'probes.json').read_text())['summary']
    old=[r['previous_recovered'] for r in rr];new=[r['recovered'] for r in rr]
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained');x=np.arange(2)
    axes[0].bar(x-.18,old,width=.35,label='Previous selector',color='#9b9b9b')
    axes[0].bar(x+.18,new,width=.35,label='Carrier-first selector',color='#247f73')
    axes[0].set(xticks=x,xticklabels=['Clean signals','Added to real EEG'],ylim=(0,74),ylabel='Correct frequency + direction (out of 66)',title='Same known-signal probes, repaired estimator')
    axes[0].legend(loc='lower right',fontsize=8)
    for positions,values in [(x-.18,old),(x+.18,new)]:
        for xx,y in zip(positions,values):axes[0].text(xx,y+1,str(y),ha='center')
    p=ROOT/'validation/pilot_results_carrier_v1_2/10034_ses-1_bandit_pre_20260918104411/response_beta_erd'
    d=pd.read_csv(p/'carrier_spectrum.csv');r=json.loads((p/'result.json').read_text())
    axes[1].plot(d.frequency_hz,10*np.log10(d.power_uv2_per_hz),color='#245b80')
    axes[1].axvspan(13,30,alpha=.12,color='#247f73')
    axes[1].set(xlabel='Frequency (Hz)',ylabel='PSD (dB re 1 µV²/Hz)',title='10034 pre: no resolved beta carrier')
    assert r['candidate_hz'] is None and not r['reliable']
    axes[1].text(.97,.92,f"{r['n_retained']} retained trials\nNo individualized frequency",transform=axes[1].transAxes,ha='right',va='top',fontsize=9)
    fig.savefig(folder/'recovery_and_native_spectrum.png',dpi=160);plt.close(fig)

if __name__=='__main__':main()
