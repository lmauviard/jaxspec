import os
import numpy as np
import xarray as xr


class Observation(xr.Dataset):
    """
    Class to store the data of an observation
    """

    __slots__ = ("counts", "grouping", "channel", "quality" "exposure")

    _default_attributes = {"description": "X-ray observation dataset"}

    @classmethod
    def from_matrix(
        cls,
        counts,
        grouping,
        channel,
        quality,
        exposure,
        background=None,
        attributes: dict | None = None,
    ):
        if attributes is None:
            attributes = {}
        data_dict = {
            "counts": (["instrument_channel"], np.array(counts, dtype=np.int64), {"description": "Counts", "unit": "photons"}),
            "folded_counts": (
                ["folded_channel"],
                np.array(grouping @ counts, dtype=np.int64),
                {"description": "Folded counts, after grouping", "unit": "photons"},
            ),
            "grouping": (
                ["folded_channel", "instrument_channel"],
                np.array(grouping, dtype=bool),
                {"description": "Grouping matrix."},
            ),
            "quality": (["instrument_channel"], np.array(quality, dtype=np.int64), {"description": "Quality flag."}),
            "exposure": ([], float(exposure), {"description": "Total exposure", "unit": "s"}),
        }

        if background is not None:
            data_dict["background"] = (
                ["instrument_channel"],
                np.array(background, dtype=np.int64),
                {"description": "Background counts", "unit": "photons"},
            )

            data_dict["folded_background"] = (
                ["folded_channel"],
                np.array(grouping @ background, dtype=np.int64),
                {"description": "Background counts", "unit": "photons"},
            )

        return cls(
            data_dict,
            coords={
                "channel": (["instrument_channel"], np.array(channel, dtype=np.int64), {"description": "Channel number"}),
                "grouped_channel": (
                    ["folded_channel"],
                    np.arange(len(grouping @ counts), dtype=np.int64),
                    {"description": "Channel number"},
                ),
            },
            attrs=cls._default_attributes if attributes is None else attributes | cls._default_attributes,
        )

    @classmethod
    def from_pha_file(cls, pha_file: str | os.PathLike, **kwargs):
        from .util import data_loader

        pha, arf, rmf, bkg, metadata = data_loader(pha_file)

        return cls.from_matrix(
            pha.counts,
            pha.grouping,
            pha.channel,
            pha.quality,
            pha.exposure,
            background=bkg.counts if bkg is not None else None,
            attributes=metadata,
        )

    def plot_counts(self, **kwargs):
        """
        Plot the counts

        Parameters:
            **kwargs : `kwargs` passed to https://docs.xarray.dev/en/latest/generated/xarray.DataArray.plot.step.html#xarray.DataArray.plot.line
        """

        return self.counts.plot.step(x="instrument_channel", yscale="log", where="post", **kwargs)

    def plot_grouping(self):
        """
        Plot the grouping matrix and compare the grouped counts to the true counts
        in the original channels.
        """

        import matplotlib.pyplot as plt
        import seaborn as sns

        fig = plt.figure(figsize=(6, 6))
        gs = fig.add_gridspec(
            2, 2, width_ratios=(4, 1), height_ratios=(1, 4), left=0.1, right=0.9, bottom=0.1, top=0.9, wspace=0.05, hspace=0.05
        )
        ax = fig.add_subplot(gs[1, 0])
        ax_histx = fig.add_subplot(gs[0, 0], sharex=ax)
        ax_histy = fig.add_subplot(gs[1, 1], sharey=ax)
        sns.heatmap(self.grouping.T, ax=ax, cbar=False)
        ax_histx.step(np.arange(len(self.folded_counts)), self.folded_counts, where="post")
        ax_histy.step(self.counts, np.arange(len(self.counts)), where="post")

        ax.set_xlabel("Grouped channels")
        ax.set_ylabel("Channels")
        ax_histx.set_ylabel("Grouped counts")
        ax_histy.set_xlabel("Counts")

        ax_histx.semilogy()
        ax_histy.semilogx()

        _ = [label.set_visible(False) for label in ax_histx.get_xticklabels()]
        _ = [label.set_visible(False) for label in ax_histy.get_yticklabels()]
