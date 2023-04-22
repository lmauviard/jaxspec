import haiku as hk
import jax.numpy as jnp
import arviz as az
import numpyro
import jax
import numpyro.distributions as dist
from abc import ABC, abstractmethod
from jax import random
from jax.flatten_util import ravel_pytree
from jax.tree_util import tree_map
from .model.abc import SpectralModel
from .data.observation import Observation
from numpyro.infer import MCMC, NUTS
from numpyro.infer.mcmc import MCMCKernel
from numpyro.distributions import Distribution, Poisson
from typing import Union


def build_prior(prior):
    """
    Build the prior distribution for the model parameters.
    """

    parameters = hk.data_structures.to_haiku_dict(prior)

    for i, (m, n, to_set) in enumerate(hk.data_structures.traverse(prior)):

        if isinstance(to_set, Distribution):
            parameters[m][n] = numpyro.sample(f'{m}_{n}', to_set)

    return parameters


class ForwardModel(hk.Module):

    def __init__(self, model: SpectralModel, observation: Observation):
        super().__init__()
        self.model = model
        self.observation = observation

    def __call__(self, parameters):
        """
        Compute the count functions for a given observation.
        """

        energies = jnp.asarray(self.observation.energies, dtype=jnp.float64)
        transfer_matrix = jnp.asarray(self.observation.transfer_matrix, dtype=jnp.float64)

        return jnp.clip(transfer_matrix @ jnp.trapz(self.model(parameters, energies), x=energies, axis=0), a_min=1e-6)

class ForwardModelFit(ABC):
    """
    Abstract class to fit a model to a given set of observation.
    """

    model: SpectralModel
    observation: Union[Observation, list[Observation]]
    count_function: hk.Transformed
    pars: dict

    def __init__(self, model: SpectralModel, observation: Union[Observation, list[Observation]]):

        self.model = model
        self.observation = [observation] if isinstance(observation, Observation) else observation
        self.pars = tree_map(lambda x: jnp.float64(x), self.model.params)

    @abstractmethod
    def fit(self, *args, **kwargs):
        """
        Abstract method to fit the model to the data.
        """
        pass


class FrequentistModel(ForwardModelFit):
    """
    Class to fit a model to a given set of observation using a frequentist approach.
    """

    def __init__(self, model, observation):
        super().__init__(model, observation)

    def fit(self):
        pass


class BayesianModel(ForwardModelFit):
    """
    Class to fit a model to a given set of observation using a Bayesian approach.
    """

    def __init__(self, model, observation):
        super().__init__(model, observation)

    def fit(self,
            prior_params,
            rng_key: int = 0,
            num_chains: int = 4,
            num_warmup: int = 1000,
            num_samples: int = 1000,
            likelihood: Distribution = Poisson,
            kernel: MCMCKernel = NUTS,
            jit_model: bool = False,
            kernel_kwargs: dict = {},
            mcmc_kwargs: dict = {},
            return_inference_data: bool = True):

        def bayesian_model():

            pars = build_prior(prior_params)

            for i, obs in enumerate(self.observation):

                transformed_model = hk.without_apply_rng(hk.transform(lambda pars: ForwardModel(self.model, obs)(pars)))

                if jit_model:
                    obs_model = jax.jit(lambda p: transformed_model.apply(None, p))

                else:
                    def obs_model(p): transformed_model.apply(None, p)

                numpyro.sample(f'likelihood_obs_{i}',
                               likelihood(obs_model(pars)),
                               obs=obs.observed_counts)

        chain_kwargs = {
            'num_warmup': num_warmup,
            'num_samples': num_samples,
            'num_chains': num_chains
        }

        kernel = kernel(bayesian_model, **kernel_kwargs)
        mcmc = MCMC(kernel, **(chain_kwargs | mcmc_kwargs))

        mcmc.run(random.PRNGKey(rng_key))

        if return_inference_data:

            return az.from_numpyro(posterior=mcmc)

        else:

            return mcmc.get_samples()
