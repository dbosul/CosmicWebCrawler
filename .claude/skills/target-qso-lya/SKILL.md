---
name: target-qso-lya
description: Science configuration for UV-luminous QSO targets for Lyman-alpha emission searches with KCWI/PCWI IFU spectroscopy. Use this to understand what makes a valid target, what catalog filters to apply, and what to look for in the literature.
argument-hint: <project>
---

# Target Science: UV-Luminous QSOs for Lyα Emission Search

Use this skill to inform catalog query parameters, quality cuts, and literature focus when
building a sample for IFU Lyα emission follow-up with KCWI or PCWI.

## Catalog query parameters

**SIMBAD object types to include:**
- `QSO` — confirmed quasar
- `AGN` — active galactic nucleus
- `Sy1`, `Sy2`, `SyG` — Seyfert galaxies
- `Bla`, `BLL` — blazars / BL Lac objects

**Redshift constraints:**
- Default range: z = 2.0 – 3.5
- Hard floor at z = 2.0: below this, Lyα (1216 Å) falls below KCWI's atmospheric blue
  cutoff (~3600 Å) and cannot be observed from the ground
- Soft ceiling at z = 3.5: above this, QSO surface density in a typical 1 deg² field
  drops sharply; widen to z = 4.0 only if target count is insufficient

**Photometry priority:**
- SDSS u-band (AB) preferred: bright QSOs (u < 21) are stronger Lyα ionizing sources
- Accept g-band as fallback; flag sources with no optical photometry for human review
- X-ray selection (XMM, Chandra) is valid but UV luminosity must be confirmed separately

## Instrument field-of-view

Per Morrissey et al. (2018, ApJ 864, 93) and the Keck KCWI instrument primer:

| Instrument | Slicer | FoV | FoV search radius |
|---|---|---|---|
| KCWI | Large  | 33.1″ × 20.4″ | 20″ half-diagonal |
| KCWI | Medium | 16.5″ × 20.4″ | 14″ half-diagonal |
| KCWI | Small  |  8.4″ × 20.4″ | 12″ half-diagonal |
| PCWI | —      | 40″  × 60″    | 40″ half-diagonal |

Default for pipeline: KCWI large slicer (maximum spatial coverage for nebula detection).

Bright star limit: V < 12 within the primary FoV. Stars in this range produce PSF wings
and scattered light that degrade continuum subtraction in emission line searches.
V < 9 would only catch stars near saturation; the damaging regime is V = 9–12.

## Literature focus keywords

Pass these to the literature-agent `focus` parameter:

```
extended Lya emission, Lya nebula, Lya halo, Lyman-alpha blob, LAB, LAH,
IFU spectroscopy, integral field, CGM emission, circumgalactic medium,
KCWI, PCWI, MUSE, extended emission line region
```

**Rejection threshold:** extended Lyα confirmed at > 3σ significance in a peer-reviewed
publication → flag `lya_known`, reject.

**Human review threshold:** tentative detection (< 3σ, preprint only, or indirect
association with an overdensity) → flag `lya_possible`, keep as candidate.

## Why these targets?

Extended Lyα emission around luminous QSOs traces circumgalactic gas, cosmic web
filaments, and AGN-driven outflows. IFU surveys have shown that UV-bright QSOs at
z ~ 2–3 frequently host Lyα halos detectable in hours of KCWI integration time.
The science goal is to find QSOs with *no* known Lyα detection — i.e., new discovery
space — not to re-observe known nebulae.

At z = 2–3, KCWI's large slicer (~16″ × 20″) subtends ~130 × 160 kpc (physical),
sufficient to detect halos on scales predicted by hydrodynamic simulations
(R ≲ 100 kpc) and seen in existing surveys.
