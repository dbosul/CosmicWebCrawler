---
name: target-gp-lyc
description: Science configuration for Green Pea / Lyman Continuum leaker candidates. Targets compact star-forming galaxies at z~0.15-0.4 for HST/COS UV spectroscopy and VLT/MUSE ground characterization.
argument-hint: <project>
---

# Target Science: Green Pea / LyC Leaker Candidates

Use this skill to understand selection criteria, catalog filters, and literature focus when
building a sample for Lyman Continuum escape fraction measurements.

## What is a Green Pea / LyC leaker?

Green Pea galaxies are compact (< 5 kpc), low-metallicity, intensely star-forming galaxies
at z ~ 0.1–0.4 identified by unusually strong [OIII]λ4959,5007 emission in SDSS imaging
(giving them a green colour in gri composites). A subset are confirmed Lyman Continuum
leakers — they emit ionizing photons (λ < 912 Å) that escape into the IGM.

**Why they matter:** LyC leakers at z ~ 0.2–0.4 are observational proxies for the
reionisation-era galaxy population. Measuring their escape fractions (f_esc) directly
constrains models of cosmic reionisation. Direct LyC detection requires space-based UV
spectroscopy; ground-based IFU characterises the emission line diagnostics that predict
f_esc.

## Target selection criteria

A good candidate satisfies most of:
- **Compact morphology**: half-light radius < 3 kpc (unresolved or barely resolved
  in ground-based imaging)
- **Strong [OIII]**: rest-frame EW([OIII]λ5007) > 300 Å is the classical GP threshold
- **High [OIII]/[OII]**: O32 ratio = [OIII]λ5007 / [OII]λ3727 > 5 is the strongest
  observational predictor of LyC leakage (Izotov et al. 2018; Fludra et al. 2024)
- **Low metallicity**: 12 + log(O/H) < 8.2 (sub-solar)
- **High specific SFR**: sSFR > 10 Gyr⁻¹
- **No known LyC detection**: existing HST/COS observations already constrain f_esc

## Redshift range

- z = 0.15–0.40
- Floor at z = 0.15: below this, LyC (912 Å) falls to < 1049 Å — below the HST/COS
  G130M red cutoff and swamped by geocoronal Lyman-alpha
- Ceiling at z = 0.40: LyC at 1276 Å, still within COS G130M; above z ~ 0.5,
  sensitivity drops and targets require prohibitively long COS exposures

## Catalog strategy (southern hemisphere)

SDSS spectroscopic coverage is extremely sparse below Dec ≈ −10°. Prioritise:
1. **SIMBAD**: `GiG` (Green Pea galaxy) otype, or `EmG` (emission-line galaxy) +
   coordinate/redshift filter
2. **NED**: cone search with galaxy type filter + z range
3. **VizieR**: 2dFGRS (J/MNRAS/328/1039), GAMA (if in footprint), DEVILS, or
   the Yang et al. 2017 green pea catalog (J/ApJS/230/1) cross-matched to southern sky
4. **SDSS**: query but expect sparse results; treat as bonus confirmation

## Instrument field-of-view

| Instrument | FoV | FoV search radius | Notes |
|---|---|---|---|
| VLT/MUSE WFM | 60″ × 60″ | 42″ half-diagonal | ~50×50 kpc at z=0.2 |
| VLT/MUSE NFM | 7.5″ × 7.5″ | 5″ half-diagonal | AO-assisted, very compact targets |
| HST/COS | 2.5″ aperture | — | UV spectroscopy only, point-like |

Default: MUSE WFM (wide-field mode). Bright star limit: R < 13 within the 1′ FoV
causes guide star acquisition problems and PSF contamination.

## Literature focus keywords

Pass these to the literature-agent `focus` parameter:

```
Lyman continuum leaker, LyC escape fraction, green pea galaxy, compact star-forming,
[OIII]/[OII] ratio O32, ionizing photon escape, HST COS ultraviolet detection,
f_esc measurement, reionization analogue, Southern sky UV
```

**Rejection threshold:** existing direct LyC detection with measured f_esc → flag
`lyc_observed`. The science goal is candidates where f_esc is *unknown*, not
re-observation of confirmed leakers.

**Human review threshold:** tentative detection or upper limit only → flag
`lyc_candidate_uncertain`, keep for human review.

## Why southern hemisphere?

VLT/MUSE has the sensitivity and spectral resolution to measure [OIII], [OII], Hα, Hβ
and derive O32, dust correction, and SFR simultaneously in a single pointing. Most
published green pea samples are SDSS-selected (northern sky). The southern hemisphere
is therefore an underexplored discovery space for new LyC leaker candidates, making
it less likely that literature searches will return memorised training-data results.
