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
- Default range: z = 2.043 – 3.5  (Lyα at 3700–5456 Å, within KCWI BL bandpass)
- Hard floor at z = 2.043: below this, Lyα (1216 Å) falls below the KCWI BL throughput
  floor (~3700 Å; Morrissey et al. 2018, ApJ 864, 93, Fig. 8). Sources at z=2.0–2.043
  have Lyα at 3648–3700 Å and will be rejected by the quality check.
- Science floor at z ≈ 2.56 (Lyα ≈ 3900 Å): below this, BL throughput is 5–30% of peak.
  Sources in z=2.043–2.56 can be targeted but require longer integrations; prefer z > 2.56
  for low-surface-brightness nebula science. These are flagged `lya_blue_edge_science`.
- Soft ceiling at z = 3.5: above this, QSO surface density drops sharply; widen to z = 3.6
  only if target count is insufficient. **Do not widen above z = 3.6 for KCWI BL** — at
  z=3.6, Lyα = 5594 Å near the BL red limit. At z=4.0, Lyα = 6080 Å (requires BM/BH3).

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
