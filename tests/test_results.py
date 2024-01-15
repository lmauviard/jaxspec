import matplotlib.pyplot as plt
import numpyro
import numpyro.distributions as dist
from jax.config import config
from unittest import TestCase
from jaxspec.model.additive import Powerlaw
from jaxspec.model.multiplicative import Tbabs
from jaxspec.data import FoldingModel
from jaxspec.data.util import load_example_observations, load_example_instruments
from jaxspec.fit import BayesianModel


# chex.set_n_cpu_devices(n=4)

config.update("jax_enable_x64", True)
numpyro.set_platform("cpu")
numpyro.set_host_device_count(4)


observations = load_example_observations()
instruments = load_example_instruments()


class TestResults(TestCase):
    model = Tbabs() * Powerlaw()
    foldings = [FoldingModel.from_instrument(instruments[key], observations[key]) for key in instruments.keys()]
    forward = BayesianModel(model, foldings)

    prior = {"powerlaw_1": {"alpha": dist.Uniform(0, 10), "norm": dist.Exponential(1e4)}, "tbabs_1": {"N_H": dist.Uniform(0, 1)}}

    result = forward.fit(prior, num_samples=1000)

    def test_plot_ppc(self):
        self.result[0].plot_ppc(percentile=(5, 95))
        plt.show()

    def test_plot_corner(self):
        self.result[0].plot_corner()
        plt.show()

    def test_table(self):
        print(self.result[0].table())
