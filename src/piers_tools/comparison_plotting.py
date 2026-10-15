"""Daily comparison figure; matplotlib is an optional notebook dependency."""


def plot_day(daily_comparison_df):
    """Return a figure with cumulative rain and minute wind; emphasize pit gauges."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    for column in daily_comparison_df.filter(like="__rain_in"):
        pit = column.endswith(("__Pit_A__rain_in", "__Pit_B__rain_in"))
        axes[0].plot(daily_comparison_df.index, daily_comparison_df[column].cumsum(), linewidth=3.5 if pit else 1,
                     zorder=5 if pit else 2, label=column)
    axes[0].set_ylabel("Observed cumulative rain (inch)")
    axes[0].legend(fontsize=7, ncol=2)
    for column in daily_comparison_df.filter(like="__wind_speed_m_s"):
        axes[1].plot(daily_comparison_df.index, daily_comparison_df[column], label=column)
    axes[1].set_ylabel("Mean wind speed (m/s)")
    axes[1].legend(fontsize=8)
    for column in daily_comparison_df.filter(like="__wind_direction_deg"):
        axes[2].scatter(daily_comparison_df.index, daily_comparison_df[column], s=3, label=column)
    axes[2].set_ylim(0, 360)
    axes[2].set_ylabel("Circular mean direction (degrees)")
    axes[2].legend(fontsize=8)
    fig.suptitle(f"Standalone gauges and PIERS wind · {daily_comparison_df.attrs.get('date', '')}")
    fig.tight_layout()
    return fig
