import haiku as hk
import jax
import jax.numpy as jnp
import jax.scipy as jsp
from .abc import AdditiveComponent, AnalyticalAdditive
from haiku.initializers import Constant as HaikuConstant


class Powerlaw(AdditiveComponent):
    r"""
    A power law model

    .. math::
        \mathcal{M}\left( E \right) = K E^{-\alpha}

    Parameters
    ----------
        * :math:`\alpha` : Photon index of the power law :math:`\left[\text{dimensionless}\right]`
        * :math:`K` : Normalization :math:`\left[\frac{\text{photons}}{\text{cm}^2\text{s}}\right]`
    """

    def __call__(self, energy):

        alpha = hk.get_parameter('alpha', [], init=HaikuConstant(1.3))
        norm = hk.get_parameter('norm', [], init=HaikuConstant(1e-4))

        return norm*energy**(-alpha)


class AdditiveConstant(AnalyticalAdditive):
    r"""
    A constant model

    .. math::
        \mathcal{M}\left( E \right) = K

    Parameters
    ----------
        * :math:`K` : Normalization :math:`\left[\frac{\text{photons}}{\text{cm}^2\text{s}}\right]`
    """

    def __call__(self, energy):

        norm = hk.get_parameter('norm', [], init=HaikuConstant(1))

        return norm*jnp.ones_like(energy)

    def primitive(self, energy):

        norm = hk.get_parameter('norm', [], init=HaikuConstant(1))

        return norm*energy


class Lorentz(AdditiveComponent):
    r"""
    A Lorentzian line profile

    .. math::
        \mathcal{M}\left( E \right) = K\frac{\frac{\sigma}{2\pi}}{(E-E_L)^2 + \left(\frac{\sigma}{2}\right)^2}

    Parameters
    ----------
        * :math:`E_L` : Energy of the line :math:`\left[\text{keV}\right]`
        * :math:`\sigma` : FWHM of the line :math:`\left[\text{keV}\right]`
        * :math:`K` : Normalization :math:`\left[\frac{\text{photons}}{\text{cm}^2\text{s}}\right]`
    """

    has_fine_structure = True

    def fine_structure(self, e_min, e_max) -> (jax.Array, jax.Array):

        #return the primitive of a lorentzian
        line_energy = hk.get_parameter('E_l', [], init=HaikuConstant(1))
        sigma = hk.get_parameter('sigma', [], init=HaikuConstant(1))
        norm = hk.get_parameter('norm', [], init=HaikuConstant(1))

        #This is AI generated for tests I should double check this at some point
        def primitive(energy):
            return norm*(sigma/(2*jnp.pi))*jnp.arctan((energy-line_energy)/(sigma/2))

        return primitive(e_max) - primitive(e_min), (e_min + e_max)/2

    def __call__(self, energy):

        line_energy = hk.get_parameter('E_l', [], init=HaikuConstant(1))
        sigma = hk.get_parameter('sigma', [], init=HaikuConstant(1))
        norm = hk.get_parameter('norm', [], init=HaikuConstant(1))

        return jnp.zeros_like(energy) #norm*(sigma/(2*jnp.pi))/((energy-line_energy)**2 + (sigma/2)**2)


class Logparabola(AdditiveComponent):
    r"""
    A LogParabola model

    .. math::
        \mathcal{M}\left( E \right) = K \left( \frac{E}{E_{\text{Pivot}}} \right)^{-(\alpha + \beta ~ \log (E/E_{\text{Pivot}})) }

    Parameters
    ----------
        * :math:`a` : Slope of the LogParabola at the pivot energy :math:`\left[\text{dimensionless}\right]`
        * :math:`b` : Curve parameter of the LogParabola :math:`\left[\text{dimensionless}\right]`
        * :math:`K` : Normalization at the pivot energy :math:`\left[\frac{\text{photons}}{\text{cm}^2\text{s}}\right]`
        * :math:`E_{\text{Pivot}}` : Pivot energy fixed at 1 keV :math:`\left[ \mathrm{keV}\right]`
    """

    def __call__(self, energy):

        a = hk.get_parameter('a', [], init=HaikuConstant(11 / 3))
        b = hk.get_parameter('b', [], init=HaikuConstant(0.2))
        norm = hk.get_parameter('norm', [], init=HaikuConstant(1))

        return norm*energy**(-(a + b*jnp.log(energy)))


class Blackbody(AdditiveComponent):
    r"""
    A black body model

    .. math::
        \mathcal{M}\left( E \right) = \frac{K \times 8.0525 E^{2}}{(k_B T)^{4}\left(\exp(E/k_BT)-1\right)}

    Parameters
    ----------
        * :math:`k_B T` : Temperature :math:`\left[\text{keV}\right]`
        * :math:`K` : :math:`L_{39}/D_{10}^{2}`, where :math:`L_{39}` is the source luminosity in units of :math:`10^{39}` erg/s and :math:`D_{10}` is the distance to the source in units of 10 kpc
    """

    def __call__(self, energy):

        kT = hk.get_parameter('kT', [], init=HaikuConstant(11 / 3))
        norm = hk.get_parameter('norm', [], init=HaikuConstant(1))

        return norm*8.0525*energy**2/((kT**4)*(jnp.exp(energy/kT)-1))


class Gauss(AnalyticalAdditive):
    r"""
    A Gaussian line profile

    .. math::
        \mathcal{M}\left( E \right) = \frac{K}{\sqrt{2\pi\sigma^2}}\exp\left(\frac{-(E-E_L)^2}{2\sigma^2}\right)

    The primitive is defined as :

    .. math::
        \int \mathcal{M}\left( E \right) \text{d}E = \frac{K}{2}\left( 1+\text{erf} \frac{(E-E_L)}{\sqrt{2}\sigma} \right)

    The primitive is defined as :

    .. math::
        \int \mathcal{M}\left( E \right) \diff E = K\frac{1}{2}\left( 1+\erf frac{(E-E_L)}{\sqrt{2}\sigma} \right)

    Parameters
    ----------
        * :math:`E_L` : Energy of the line :math:`\left[\text{keV}\right]`
        * :math:`\sigma` : Width of the line :math:`\left[\text{keV}\right]`
        * :math:`K` : Normalization :math:`\left[\frac{\text{photons}}{\text{cm}^2\text{s}}\right]`
    """

    has_fine_structure = True

    def fine_structure(self, e_min, e_max) -> (jax.Array, jax.Array):
        line_energy = hk.get_parameter('E_l', [], init=HaikuConstant(1))
        sigma = hk.get_parameter('sigma', [], init=HaikuConstant(1))
        norm = hk.get_parameter('norm', [], init=HaikuConstant(1))

        return norm * (jsp.stats.norm.cdf(e_max, loc=line_energy, scale=sigma) - jsp.stats.norm.cdf(e_min, loc=line_energy, scale=sigma)), (e_min + e_max)/2

    def __call__(self, energy):

        line_energy = hk.get_parameter('E_l', [], init=HaikuConstant(1))
        sigma = hk.get_parameter('sigma', [], init=HaikuConstant(1))
        norm = hk.get_parameter('norm', [], init=HaikuConstant(1))

        return jnp.zeros_like(energy)#norm*jsp.stats.norm.pdf(energy, loc=line_energy, scale=sigma)

    def primitive(self, energy):

        line_energy = hk.get_parameter('E_l', [], init=HaikuConstant(1))
        sigma = hk.get_parameter('sigma', [], init=HaikuConstant(1))
        norm = hk.get_parameter('norm', [], init=HaikuConstant(1))

        return norm*jsp.stats.norm.cdf(energy, loc=line_energy, scale=sigma)
