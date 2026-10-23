#!/usr/bin/env python3
"""Plot independently checked carrier/contrast counterexamples at native 500 Hz."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal

from diagnose_data_vs_method import ROOT, probe_epochs
from rhythm_validation_core import spectra

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
if args.out.exists():
    raise FileExistsError(args.out)
cfg=json.loads((ROOT/'code/rhythm_validation_config.json').read_text())
fig,axes=plt.subplots(2,2,figsize=(12,7.4),layout='constrained')
for row,(key,frequency,label) in enumerate([('response_beta_erd',21,'Beta suppression'),('feedback_theta_enhancement',6,'Theta enhancement')]):
    spec=cfg['estimands'][key];fs=500
    times=np.arange(round(np.diff(spec['epoch_sec'])[0]*fs))/fs+spec['epoch_sec'][0]
    probe=probe_epochs(times,100,3,spec,frequency,10,555)
    epochs=probe+np.random.default_rng(556).normal(0,1,probe.shape)
    f,trials,base,active,_,_=spectra(epochs,times,fs,spec)
    band=(f>=spec['band_hz'][0])&(f<=spec['band_hz'][1])
    contrast=trials.mean(0);candidate=f[band][np.argmax(spec['direction']*contrast[band])]
    fft_f,psd=signal.periodogram(epochs,fs=fs,axis=-1);b=(fft_f>=spec['band_hz'][0])&(fft_f<=spec['band_hz'][1])
    fft_peak=fft_f[b][np.argmax(psd.mean((0,1))[b])]
    left,right=axes[row]
    left.plot(f,10*np.log10(base.mean(0)),label='Baseline',color='#245fa5')
    left.plot(f,10*np.log10(active.mean(0)),label='Response',color='#c47822')
    left.axvline(frequency,color='#16835e',ls='--',label=f'Known carrier: {frequency} Hz')
    left.set(xlim=spec['band_hz'],ylabel='Morlet log power (dB)',title=f'{label}: an oscillatory peak is present')
    left.legend(fontsize=9)
    right.plot(f,contrast,color='#303b49',lw=2)
    right.axvline(frequency,color='#16835e',ls='--',label=f'Known carrier: {frequency} Hz')
    right.axvline(candidate,color='#bc3838',ls=':',lw=2,label=f'Contrast extremum: {candidate:g} Hz')
    right.set(xlim=spec['band_hz'],ylabel='Mean-log-ratio change (dB)',title=f'Current frequency choice differs; Fourier peak = {fft_peak:.2f} Hz')
    right.legend(fontsize=9)
    for ax in (left,right):
        ax.set_xlabel('Frequency (Hz)');ax.grid(alpha=.18);ax.spines[['top','right']].set_visible(False)
fig.suptitle('A failed frequency estimate can be an analysis problem—even with a known, clean signal',fontsize=14)
args.out.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(args.out,dpi=170)
