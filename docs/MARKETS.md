# Market deep dive, 2026-09-17

What a solo modeller with public data can and cannot beat on Kalshi. Numbers
are as of this date; the reasoning is what to keep.

## Tier 1: modelable now, code exists or is small

| market | edge source | status |
|---|---|---|
| Daily rain, 22 cities (KXRAIN) | six calibrated NWP inputs plus the station gauge; the climate day boundary | live, tracked |
| Daily high temperature, 7 cities (KXHIGH*) | per-station error distributions, wet-day split | live, Chicago excluded |
| Monthly city rain and snow (KXRAIN*M, *SNOWM) | month-to-date from the CLI report plus 30-year climatology plus the week-ahead models | Houston done by hand; generalise |
| GISTEMP monthly anomaly (KXHMONTHRANGE) | ERA5 daily global mean from Climate Reanalyzer, offset to GISTEMP (13-month offset 0.63 C, sd 0.07). A nowcast exists three weeks before NASA publishes | Sep 2026 nowcast 1.47 vs 1.30 threshold |
| Fed ladder consistency (KXEFFR vs KXFEDDECISION) | the EFFR rungs are arithmetic on the FOMC outcome and the books are thin; twice priced 15 to 40 cents off | scanner to write |
| Hurricane counts and dates (KXHURCTOT*, KXNEXTHURDATE) | HURDAT2 climatology conditioned on ENSO and date, NHC outlooks | code exists |
| Launch counts (KXLAUNCHES, KXSPACEXCOUNT) | Launch Library 2 schedule plus a Poisson on the remaining days | small |
| Payrolls and CPI buckets | claims, ADP, Cleveland Fed nowcast | brief milestone 5 |

## Tier 2: long-dated base-rate sells (rules read, physics checked)

| market | price | estimate | note |
|---|---:|---|---|
| Quantum computer cracks RSA-2048 or simulates FeMoco/P450 before 2030 (KXQUANTUM-30) | YES 33 to 36 | under 5%. Best 2025 estimates need about a million physical qubits for RSA-2048; largest machines are in the low thousands. FeMoco at chemical accuracy needs fault tolerance nobody has. | NO at 64 to 67, about 50% to Jan 2030, plus interest |
| Same before 2035 (KXQUANTUM-35) | YES 50 | 20 to 30% | NO at 50 is fair to slightly good; longer horizon |
| CO2 at least 445 ppm before 2030 (KXCO2LEVEL-30-445) | YES 25 to 33 | under 5%. Mauna Loa deseasonalised 429.5 in Aug 2026, trend 2.5 ppm/yr, May 2029 monthly peak projects 439 plus or minus 1.5; daily peaks add 2 | NO at 67 to 75. Risk is the undefined measure in the rule; 450 NO at 77 to 85 is the safer rung |
| CO2 at least 440 (KXCO2LEVEL-30-440) | YES 85 to 88 | 60 to 75% on monthly means, higher on daily | no edge |
| Japan M8.0 before 2030 (KXEARTHQUAKEJAPAN-30) | YES 37 to 38 | 25% Poisson from 11 events since 1900 (rate 0.087/yr, 3.3 yr window); Nankai Trough hazard pushes it to about 30% | NO at 62, thin edge, hold only if bored |
| Meissner effect at 240 K ambient pressure in a Q1 journal before 2027 (KXMEISSNER) | YES 2 to 5 | under 1%; LK-99 style claims do not pass Q1 review in three months | NO at 95 to 98, not worth the capital |
| Riemann prize before 2028 | YES 2 to 6 | 0 | done |
| New reactor combined licence in 2026 (KXREACTOR) | YES 5 to 8 | 0; Fermi's application completes Dec 31 at the earliest | NO at 92 to 95, tie-up to Jan |

## Tier 3: structural overpricing

- **Nobel Physics 2026 (KXNOBELPHYSICS)**, announced Oct 6. 24 names, bids
  sum to 1.86 and mids to 2.78. At most three people win and most years the
  winners are on nobody's list, so the true sum is nearer 0.7 to 1.0. Every
  name is overpriced; the top ones (Kitaev 21 to 28, Preskill 19 to 25, Kane
  17 to 25) most of all. Buy NO on the top five at 72 to 80 and expect to lose
  one of them at worst. Clarivate's 2026 physics picks (Adachi, Forrest,
  Thompson on OLEDs; Spaldin on multiferroics; Xue on the quantum anomalous
  Hall effect) are not listed, which says the listed set is the crowd's guess,
  not the field's.
- **Nobel Economics** bids sum to 0.71 for 9 names: fairly priced, skip.

## Where Duncan's own knowledge applies

- **Thin films, OLEDs, multiferroics**: the Nobel list above. Judgement on
  whether a materials prize is due this year is worth more than base rates.
- **Superconductivity claims**: the Meissner market and anything like it.
- **Semiconductor capacity and China EUV** (KXCHINAEUV at 68 to 75 for a
  functional EUV tool): the market is pricing a functional domestic EUV
  scanner, a claim that needs a light source, optics and a resist stack that
  no public evidence supports on this timeline. This is where process
  knowledge matters, but check the rule's definition of "functional" before
  anything else. Employer overlap: reason only from public reporting.
- **Battery and grid storage** (thesis): no open markets today; watch for
  EV share, Tesla energy GWh (KXTESLAENERGYBY) which is company-filing
  arithmetic.
- **Radiation transport**: no markets.

## Avoid

Sports, politics, elections, crypto, the WTI, Brent, gold and silver ladders
(all priced off CME options), and AI model-release dates (news speed). Weekly
OpenRouter market-share and token markets are data-driven and public, so they
are a maybe, but the crowd there already watches the same page.
