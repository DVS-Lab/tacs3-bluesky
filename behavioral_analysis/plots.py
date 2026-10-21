"""Headless descriptive figures; participant weighting for group curves."""
import os

os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def make_plots(runs, sessions, bandit_trials, sst_trials, reversals, pairs, out):
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.dpi": 140, "savefig.facecolor": "white"})
    folder = out / "plots"
    folder.mkdir(exist_ok=True)
    paths = []

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(folder / name, bbox_inches="tight")
        plt.close(fig)
        paths.append("plots/" + name)

    active = runs[(runs.cohort == "experimental_candidate") & (runs.phase == "active")]
    b = active[active.task.eq("bandit") & active.behavior_valid.eq(True)].sort_values(["participant", "session", "run"])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, outcome, label in zip(axes, ["p_stay_win", "p_shift_loss"], ["P(stay | win)", "P(shift | loss)"]):
        for p, group in b.groupby("participant"):
            ax.plot(np.arange(len(group)), group[outcome], "o-", label=p)
        if len(b):
            ax.axhline(b.groupby("participant")[outcome].mean().mean(), color="black", ls="--", label="participant-weighted mean")
        ax.set(ylim=(0, 1), ylabel=label, xlabel="Successive available runs within participant")
        if len(b):
            ax.legend(fontsize=8)
    fig.suptitle("Experimental candidates: WSLS (descriptive)")
    save(fig, "bandit_wsls.png")
    fig, ax = plt.subplots(figsize=(11, 4))
    if len(b):
        x = np.arange(len(b))
        ax.plot(x, b.choice_accuracy, "o-", label="Choice accuracy")
        ax.plot(x, b.reward_rate, "s-", label="Reward rate")
        ax.set_xticks(x, [f"{r.participant}/v{int(r.session)}/r{int(r.run)}" for _, r in b.iterrows()], rotation=45, ha="right")
        ax.legend()
    ax.set(ylim=(0, 1), ylabel="Proportion", title="Bandit accuracy and reward by run")
    save(fig, "bandit_accuracy_reward.png")
    fig, ax = plt.subplots(figsize=(8, 4))
    rev = reversals[reversals.source_file.isin(b.source_file)] if len(reversals) else reversals
    if len(rev):
        indiv = rev.groupby(["participant", "offset"]).accuracy.mean().reset_index()
        for p, g in indiv.groupby("participant"):
            ax.plot(g.offset, g.accuracy, alpha=.6, label=p)
        group = indiv.groupby("offset").accuracy.mean()
        ax.plot(group.index, group.values, color="black", lw=2.5, label="Participant-weighted mean")
        ax.legend()
    ax.axvline(0, color="gray", ls="--")
    ax.set(ylim=(0, 1), xlabel="Trials from contingency reversal (0 = first new trial)", ylabel="Choice accuracy", title="Reversal adaptation")
    save(fig, "bandit_reversals.png")
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    bt = bandit_trials[(bandit_trials.cohort == "experimental_candidate") & (bandit_trials.phase == "active")] if len(bandit_trials) else bandit_trials
    st = sst_trials[(sst_trials.cohort == "experimental_candidate") & (sst_trials.phase == "active")] if len(sst_trials) else sst_trials
    if len(bt):
        axes[0].hist(bt.rt_ms.dropna(), bins=25, color="#3574a0")
    if len(st):
        axes[1].hist(st.loc[st.is_stop.eq(False), "rt_s"].dropna() * 1000, bins=25, alpha=.6, label="Go")
        axes[1].hist(st.loc[st.is_stop.eq(True) & st.responded.eq(True), "rt_s"].dropna() * 1000, bins=25, alpha=.6, label="Failed stop")
        axes[1].legend()
    if len(active):
        axes[2].scatter(active.loc[active.task.eq("bandit"), "run"], active.loc[active.task.eq("bandit"), "missed_response_rate"], label="Bandit")
        axes[2].scatter(active.loc[active.task.eq("sst"), "run"], active.loc[active.task.eq("sst"), "go_omission_rate"], label="SST go")
        axes[2].legend()
    for ax, title in zip(axes, ["Bandit RT", "SST RT", "Missing responses"]):
        ax.set(title=title, xlabel="RT (ms)" if ax != axes[2] else "Run", ylabel="Trials" if ax != axes[2] else "Proportion")
    save(fig, "rt_and_omissions.png")
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for cohort, color in [("experimental_candidate", "#3574a0"), ("pilot", "#c98035")]:
        s = runs[runs.task.eq("sst") & runs.cohort.eq(cohort)]
        axes[0].scatter(s.go_accuracy, s.p_respond_stop, alpha=.65, label=cohort)
        axes[1].scatter(s.go_rt_mean_ms, s.failed_stop_rt_mean_ms, alpha=.65)
        axes[2].hist(s.loc[s.ssrt_valid.eq(True), "ssrt_ms"].dropna(), bins=10, alpha=.6, label=cohort)
    fig.suptitle("SST QC: selected active, pre/post and pilot recordings")
    axes[0].axhspan(.25, .75, color="green", alpha=.08)
    axes[0].set(xlabel="Go accuracy", ylabel="P(respond | stop)", title="SST tracking and accuracy", xlim=(0, 1.02), ylim=(0, 1.02))
    axes[0].legend(fontsize=7)
    axes[1].plot([0, 1500], [0, 1500], "--", color="gray")
    axes[1].set(xlabel="Mean go RT (ms)", ylabel="Mean failed-stop RT (ms)", title="Race-model diagnostic")
    axes[2].set(xlabel="Provisional eligible run SSRT (ms)", ylabel="Runs", title="Only estimates passing all gates")
    save(fig, "sst_qc.png")
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for ax, task, measure, title in zip(axes.flat, ["bandit", "bandit", "sst", "sst"],
                                      ["p_stay_win", "p_shift_loss", "ssrt_ms", "go_rt_mean_ms"],
                                      ["Win-stay", "Lose-shift", "Eligible pooled SSRT (ms)", "Go RT (ms)"]):
        d = sessions[(sessions.task == task) & (sessions.cohort == "experimental_candidate") & (sessions.phase == "active")]
        if task == "bandit":
            d = d[d.behavior_valid.eq(True)]
        for p, g in d.groupby("participant"):
            g = g.sort_values("session")
            ax.plot(g.session, g[measure], "o-", label=p)
        ax.set(title=title, xlabel="Visit")
        ax.set_xticks([1, 2, 3])
        if measure.startswith("p_"):
            ax.set_ylim(0, 1)
        if len(d):
            ax.legend(fontsize=8)
    save(fig, "session_trajectories.png")
    if len(pairs):
        outcomes = list(pairs.outcome.unique())
        fig, axes = plt.subplots(1, len(outcomes), figsize=(max(6, 3 * len(outcomes)), 4), squeeze=False)
        for ax, outcome in zip(axes.flat, outcomes):
            d = pairs[pairs.outcome == outcome]
            for contrast, g in d.groupby("contrast"):
                ax.scatter([contrast] * len(g), g.difference, label=contrast)
            ax.axhline(0, color="gray", ls="--")
            ax.set(title=outcome, ylabel="Within-participant difference")
            ax.tick_params(axis="x", rotation=45)
        save(fig, "paired_differences.png")
    return paths
