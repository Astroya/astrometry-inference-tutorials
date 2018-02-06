"""
PyStan version of the luminosity calibration (inference) example discussed in the chapter by Brown in the
book 'Astrometry for Astrophysics', 2013, edited by W.F. van Altena (Cambridge University Press). Here
distance instead of parallax priors are used.

Anthony Brown Nov 2017 - Dec 2017
"""

import numpy as np
import matplotlib.pyplot as plt
import argparse
from scipy.interpolate import interp1d

import pystan
import corner

from stantools import load_stan_code, stan_cache
from parallaxsurveys import UniformDistributionSingleLuminosityHip as udslH
from parallaxsurveys import UniformDistributionSingleLuminosityTGAS as udslT
from parallaxsurveys import showSurveyStatistics

def naive_lum_estimate(obsplx, errplx, obsmag, errmag):
    """
    Make a naive estimate of the mean absolute magnitude and its standard deviation, include also
    Lutz-Kelker corrections.

    Parameters
    ----------

    obsplx - observed parallaxes
    errplx - errors on the observed parallaxes
    obsmag - observed apparent magnitudes
    errmag - errors on observed apparent magnitudes
    """
    lk_correction = interp1d(np.linspace(0,0.175,8), np.array([0.0, -0.01, -0.02, -0.06, -0.11, -0.18,
        -0.28, -0.43]), kind='quadratic')
    lk_relative_error_limit = 0.175
    goodplx = np.where(obsplx/errplx >= 1/lk_relative_error_limit)

    if goodplx[0].size>=3:
        absMagNaive = obsmag[goodplx] + 5*np.log10(obsplx[goodplx]) - 10.0
        absMagNaiveCorrected = absMagNaive + lk_correction(errplx[goodplx]/obsplx[goodplx])
        print("Number of 'good' parallaxes used {0}/{1}".format(obsplx[goodplx].size, obsplx.size))
        print("### Naive estimate ###")
        print("Mean and sigma: {0:.2f}, {1:.2f}".format(absMagNaive.mean(), absMagNaive.std()))                                                               
        print("### Naive estimate after LK correction ###")
        print("Mean and sigma: {0:.2f}, {1:.2f}".format(absMagNaiveCorrected.mean(), absMagNaiveCorrected.std()))
    else:
        print("Cannot make naive estimate")

def run_luminosity_inference(args):
    """
    Generate the simulated parallax survey and then perform the Bayesian inference to estimate the mean
    absolute magnitude of the stars and the variance thereof. Compare to naive estimates of the mean
    absolute magnitude, including the Lutz-Kelker correction.

    Parameters
    ----------

    args - Command line arguments
    """

    distMin = args['distMin']
    distMax = args['distMax']
    plxMin = 1000.0/distMax
    plxMax = 1000.0/distMin
    nstars = args['nstars']
    absMagTrue = args['muM']
    sigmaAbsMagTrue = args['sigmaM']
    magLimit = args['mlim']

    numChains = 4
    
    print("### Generating parallax survey ... ###")
    if args['cat']=='hip':
        survey = udslH(nstars, distMin, distMax, absMagTrue, sigmaAbsMagTrue, surveyLimit = magLimit)
    else:
        survey = udslT(nstars, distMin, distMax, absMagTrue, sigmaAbsMagTrue, surveyLimit = magLimit)
    survey.setRandomNumberSeed(args['surveyseed'])
    survey.generateObservations()
    print("### ... Done ###")

    if args['surveyplot'] and (not args['noplots']):
        showSurveyStatistics(survey, pdfFile="surveyStats.pdf", usekde=False)

    if args['volumecomplete']:
        stan_data = {'minDist':distMin, 'maxDist':distMax, 'N':survey.numberOfStarsInSurvey,
                'obsPlx':survey.observedParallaxes, 'errObsPlx':survey.parallaxErrors,
                'obsMag':survey.observedMagnitudes, 'errObsMag':survey.magnitudeErrors}
        stanmodel = load_stan_code("luminosity_inference_volume_complete_distance_prior.stan")
        sm = stan_cache(stanmodel, model_name="luminosityInferenceDistPriorVC")
        fit = sm.sampling(data = stan_data, pars=['meanAbsMag', 'sigmaAbsMag'], iter=args['staniter'],
                chains=numChains, thin=args['stanthin'], seed=args['stanseed'])
    else:
        # For the magnitude limited case, explicit initialization of the true absolute magnitudes is
        # needed. See comments in Stan code.
        maxPossibleAbsMag = survey.apparentMagnitudeLimit-5*np.log10(distMax)+5
        initLow = maxPossibleAbsMag - 4
        initialValuesList = []
        for i in range(numChains):
            initialValuesList.append( dict(absMag=np.random.uniform(initLow, maxPossibleAbsMag,
                size=survey.numberOfStarsInSurvey)) )

        stan_data = {'minDist':distMin, 'maxDist':distMax, 'surveyLimit':survey.apparentMagnitudeLimit,
                'N':survey.numberOfStarsInSurvey, 'obsPlx':survey.observedParallaxes,
                'errObsPlx':survey.parallaxErrors, 'obsMag':survey.observedMagnitudes,
                'errObsMag':survey.magnitudeErrors}
        stanmodel = load_stan_code("luminosity_inference_distance_prior.stan")
        sm = stan_cache(stanmodel, model_name="luminosityInferenceDistPrior")
        fit = sm.sampling(data = stan_data, pars=['meanAbsMag', 'sigmaAbsMag'], iter=args['staniter'],
                chains=numChains, thin=args['stanthin'], seed=args['stanseed'], init=initialValuesList)
    
    print()
    print(fit)
    print()
    naive_lum_estimate(survey.observedParallaxes, survey.parallaxErrors,
            survey.observedMagnitudes, survey.magnitudeErrors)

    samples = np.vstack([fit.extract()['meanAbsMag'], fit.extract()['sigmaAbsMag']]).transpose()
    
    if (not args['noplots']):
        fig = plt.figure(figsize=(8,8))
        for i in range(1,5):
            fig.add_subplot(2,2,i)
        corner.corner(samples, labels=[r'$\mu_M$', r'$\sigma_M$'], truths=[absMagTrue, sigmaAbsMagTrue],
                truth_color='r', quantiles=[0.16,0.50,0.84], show_titles=True, fig=fig)
        plt.show()

def parseCommandLineArguments():
    """
    Set up command line parsing.
    """
    defaultDistMin = 1.0
    defaultDistMax = 100.0
    defaultNstars = 50
    defaultMeanAbsMag = 9.0
    defaultSigmaAbsMag = 0.7
    defaultMagLim = np.inf
    defaultCatalogue = 'hip'
    defaultStanIter = 10000
    defaultStanThin = 5
    parser = argparse.ArgumentParser(description="""Run luminosity inference tutorial for distance priors""")
    parser.add_argument("--distMin", help="""Minimum value of distance distribution (default
            {0} pc)""".format(defaultDistMin), default=defaultDistMin, type=float)
    parser.add_argument("--distMax", help="""Maximum value of distance distribution (default
            {0} pc)""".format(defaultDistMax), default=defaultDistMax, type=float)
    parser.add_argument("--nstars", help="""Number of stars in simulated survey (default
            {0})""".format(defaultNstars), default=defaultNstars, type=int)
    parser.add_argument("--muM", help="""Mean true absolute magnitude (default
            {0})""".format(defaultMeanAbsMag), default=defaultMeanAbsMag, type=float)
    parser.add_argument("--sigmaM", help="""Standard deviation true absolute magnitude distribution
            (default {0})""".format(defaultSigmaAbsMag), default=defaultSigmaAbsMag, type=float)
    parser.add_argument("--mlim", help="""Survey limiting magnitude (default
            {0})""".format(defaultMagLim), default=defaultMagLim, type=float)
    parser.add_argument("--cat", help="""Simulated astrometric catalogue (default {0})""".format(defaultCatalogue),
            choices=['hip','tgas'], default=defaultCatalogue, type=str)
    parser.add_argument("--surveyplot", action="store_true", help="""Make plot of survey statistics""")
    parser.add_argument("--noplots", action="store_true", help="""Do not produce any plots (overrides --surveyplot switch)""")
    parser.add_argument("--volumecomplete", action="store_true", help="""Use model for volume complete survey""")
    parser.add_argument("--surveyseed", help="""Random number seed for survey simulation (default None)""", type=int, default=None)
    parser.add_argument("--stanseed", help="""Random number seed for Stan MCMC sampler (default None)""", type=int, default=None)
    parser.add_argument("--staniter", help="""Number of iterations per chain for Stan MCMC sampler
            (default {0})""".format(defaultStanIter), type=int, default=defaultStanIter)
    parser.add_argument("--stanthin", help="""Thinning parameter for Stan MCMC sampler (default {0})"""
            .format(defaultStanThin), type=int, default=defaultStanThin)
    args=vars(parser.parse_args())
    return args

if __name__ in ('__main__'):
    args=parseCommandLineArguments()
    run_luminosity_inference(args)
