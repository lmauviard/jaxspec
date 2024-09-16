from jaxspec.fit import NSFitter


def test_convergence(get_individual_mcmc_results, get_joint_mcmc_result):
    for result in get_individual_mcmc_results + get_joint_mcmc_result:
        assert result.converged


def test_ns(obs_model_prior):
    obsconfs, model, prior = obs_model_prior

    obsconf = obsconfs[0]
    fitter = NSFitter(model, prior, obsconf)
    fitter.fit(num_samples=5000, num_live_points=200)
