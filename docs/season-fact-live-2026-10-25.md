# Season fact and top-dressing rainfall: live check (25 Oct 2026)

Real model (mistralai/mistral-small-3.2-24b-instruct), live Open-Meteo, judge off, source-page check off. Output below is unedited.

- Ejura planting: the model draft passed the checks on its second attempt and cited the rainfall record. Both officer-only lines were appended. The SMS has neither line and ends with the 'officer will confirm' sentence.
- Tamale top dressing: both model drafts failed the citation check, so the verbatim fallback was shown. The record appears twice, once as a quoted passage and once as the officer-only line. The SMS quotes the dry-soil passage and has no rainfall claim.

```
Q: When should I plant maize in Ejura? | llm:mistralai/mistral-small-3.2-24b-instruct | check ok True | tries 2
To determine the planting time for maize in Ejura, consider the following:

- Plant after three good rains within the planting window to ensure enough soil moisture to support germination and early growth [IITA-MAIZE-2025:p15-three-good-rains].
- The major season transition period is either from mid-March to end of April [MOFA-MAIZE:p11-transition-major] or from end of March to end of April [IITA-MAIZE-2025:p16-transition-major]. The officer should choose.
- The minor season transition period is either from mid-July through August to early September [MOFA-MAIZE:p12-transition-minor] or from mid-July to early September [IITA-MAIZE-2025:p16-transition-minor]. The officer should choose.
- Planting time should be informed by local weather information, sowing after the rains have stabilized to avoid wilting [MOFA-MAIZE:p10-when-to-plant].

The officer should also consider the rainfall record provided for Ejura, but note that the guides do not specify a rainfall amount that marks onset, so the officer must decide if the condition is met [RAINFALL-OPEN-METEO:ejura:2026-10-25].

Note: (officer only) Question received 25 Oct 2026. Windows cited: MoFA major season, transition: Mid-March-end of April; IITA major season, transition: End of March - End of April; MoFA minor season, transition: Mid July through August-early Sept.; IITA minor season, transition: Mid of July - Early September. The date is outside the cited windows.
Note: (officer only) Rainfall record [RAINFALL-OPEN-METEO:ejura:2026-10-25] for Ejura/Sekyedumase, 2026-09-25 to 2026-10-24: 24 rain days (at least 1 mm), 185.5 mm in total, 0 days missing (Open-Meteo (model-based estimate, forecast API past days)). This is a model estimate for one point in the district, not a rain gauge reading; estimates can differ a lot from a local gauge and from other providers. The guides give no rainfall amount that marks onset; AgriReach does not say whether onset has been reached. The officer decides.
SMS: Plant maize after three good rains within the planting window. For the major season, plant from mid-March to end of April or from end of March to end of April. For the minor season, plant from mid-July through August to early September or from mid-July to early September. Plant after the rains have stabilized to avoid wilting. Your extension officer will confirm which to follow.
SMS notes: ['sources differ: edit to keep only the option you choose']
=====
Q: When should I top dress my maize in Tamale? | stub(citation-check-fallback after llm:mistralai/mistral-small-3.2-24b-instruct) | check ok False | tries 2
[OFFLINE STUB DRAFT - no language model was used; text is assembled from retrieved passages]
What the curated sources say:
- "Top dressing should be done when the soil is moist, to enhance the dissolving of applied nutrients in the soil as this allows for faster uptake of nutrients. If at 6 weeks after planting maize the soil is very dry, delay the topdress fertilizer application until some rains are received." [APNI-SARI-2023-MAIZE:p13-topdress-moisture]
- "The Right time for application of top-dressing fertilizer is at 6 weeks after planting." [APNI-SARI-2023-MAIZE:p13-topdress-timing]
- "The first fertilizer application (basal application) should be applied shortly after germination at about two weeks after planting." [APNI-SARI-2023-MAIZE:p13-basal-timing]
- "Rainfall record (Open-Meteo (model-based estimate, forecast API past days); CC BY 4.0) for Tamale district (point: Tamale (district capital), 9.4008, -0.8393), 2026-09-25 to 2026-10-24: 15 of 30 days with at least 1 mm; total 137.2 mm. Retrieved 2026-10-25T17:47:55+00:00. This is a model estimate for one point in the district, not a rain gauge reading; estimates can differ a lot from a local gauge and from other providers. The guides give no rainfall amount that marks onset; AgriReach does not say whether onset has been reached. The officer decides." [RAINFALL-OPEN-METEO:tamale:2026-10-25]
Note: A rainfall record is attached for the officer. The guides give no rainfall amount that marks onset, so AgriReach does not say whether the guides' condition is met; the officer decides.
Note: The model draft failed the citation check, so the verbatim passages are shown instead.

Note: (officer only) Rainfall record [RAINFALL-OPEN-METEO:tamale:2026-10-25] for Tamale, 2026-09-25 to 2026-10-24: 15 rain days (at least 1 mm), 137.2 mm in total, 0 days missing (Open-Meteo (model-based estimate, forecast API past days)). This is a model estimate for one point in the district, not a rain gauge reading; estimates can differ a lot from a local gauge and from other providers. The guides give no rainfall amount that marks onset; AgriReach does not say whether onset has been reached. The officer decides.
SMS: Top dressing should be done when the soil is moist, to enhance the dissolving of applied nutrients in the soil as this allows for faster uptake of nutrients. If at 6 weeks after planting maize the soil is very dry, delay the topdress fertilizer application until some rains are received. The Right time for application of top-dressing fertilizer is at 6 weeks after planting. The first fertilizer application (basal application) should be applied shortly after germination at about two weeks after planting.
SMS notes: []
=====
```
