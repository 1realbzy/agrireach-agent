# AgriReach: officer re-grade sheet

AgriReach is a prototype that drafts answers to farmers' questions about maize and soybean from published Ghanaian extension guides (MoFA, CSIR-SARI with APNI, and IITA). It is not in use with farmers. Every draft goes to an extension officer, who edits, approves or rejects it; nothing reaches a farmer without that approval. The questions below are based on problems farmers reported in news and research. Under each one is exactly what AgriReach produced in its most recent test run, not edited. Please mark each answer correct, partly correct, wrong or unsafe, add a short comment, and say whether you would approve it as it is. Your marks decide what gets fixed next.

Test run: 2026-10-25T17:34:58Z (UTC), code version ae254ce, drafting model mistralai/mistral-small-3.2-24b-instruct.

How to read it:

- **For the officer** is the draft AgriReach puts on the officer's screen. Codes in square brackets name the guide and page each sentence comes from (list at the end).
- **Proposed SMS to the farmer** is the plain-language text AgriReach suggests sending after approval.
- "Urgent" means AgriReach flagged the case for the officer's early attention; it does not mean the answer is urgent advice.
- "I do not know." is what AgriReach writes when its guides do not cover the question; the officer then answers.

## F1 (Pests)

**Farmer's question:** Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. What next?

**For the officer:**

> Caution: the curated sources cover Northern Ghana only. The guidance below comes from them and may not apply in Adaklu; the officer should confirm local timing.
>
> The farmer should scout the maize field at least once a week, looking for unusual patterns such as insect damage on leaves, cobs, or stems, presence of insect larvae or eggs on maize leaves, abnormal leaf colour, and stunted slow growing plants [APNI-SARI-2023-MAIZE:p18-scouting]. To reduce future infestations, the farmer should rotate maize with non-host plants such as groundnut, deep plough and bury or burn infested maize residues, and properly weed the maize fields [APNI-SARI-2023-MAIZE:p20-faw-prevention]. For current infestations, the farmer should consult the local Agricultural Extension Agent (AEA) for advice on the recommended fall army worm control pesticide in the area [APNI-SARI-2023-MAIZE:p20-faw-control].

**Proposed SMS to the farmer:**

> This advice comes from guides for Northern Ghana and may not suit Adaklu, so check the timing with your local extension agent. You should scout the maize field at least once a week, looking for unusual patterns such as insect damage on leaves, cobs, or stems, presence of insect larvae or eggs on maize leaves, abnormal leaf colour, and stunted slow growing plants. You should rotate maize with non-host plants such as groundnut, deep plough and bury or burn infested maize residues, and properly weed the maize fields.

**AgriReach's note to the officer about the SMS:**

> the guidance is from sources for Northern Ghana and the farmer is in Adaklu: a caveat sentence opens the farmer text; keep it, or adjust the advice, before approving; model rewrite rejected (620 characters, over 600); rule-based version shown

_Priority: urgent. why: chemical terms in question; disease or pest terms in question; no local reference for region 'adaklu' (coastal savannah zone; corpus covers Northern Ghana only for this question)._

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F2 (Pests)

**Farmer's question:** Is putting soil in the maize funnel enough to stop armyworm?

**For the officer:**

> The officer should advise the farmer that putting soil in the maize funnel is not mentioned as a recommended practice for controlling fall armyworm. Instead, the officer should suggest regular scouting of the maize field at least once a week to monitor for signs of infestation [APNI-SARI-2023-MAIZE:p18-scouting]. Additionally, the officer can recommend preventive measures such as crop rotation with non-host plants like groundnut, deep ploughing or burning of infested maize residues, and proper weeding of the maize field to reduce infestations [APNI-SARI-2023-MAIZE:p20-faw-prevention]. If an infestation is detected, the officer should advise the farmer to consult their local Agricultural Extension Agent (AEA) for advice on recommended fall armyworm control pesticides in their area [APNI-SARI-2023-MAIZE:p20-faw-control].

**Proposed SMS to the farmer:**

> Putting soil in the maize funnel is not a recommended way to stop armyworm. Check your maize field at least once a week for signs of armyworm. To prevent armyworm, rotate crops with groundnut, plough or burn infested maize residues, and weed your maize field. If you see armyworm, talk to your local Agricultural Extension Agent for advice on pesticides.

_Priority: urgent. why: disease or pest terms in question._

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F3 (Weather)

**Farmer's question:** No rain for weeks after planting in Upper West. Should I apply fertiliser now?

**AgriReach's reply (it asks the farmer before drafting anything):**

> Which crop is this about? AgriReach currently covers maize and soybean only.

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F4 (Weather)

**Farmer's question:** Rains came late. Can I still plant maize in Northern Region at the end of July?

**For the officer:**

> [OFFLINE STUB DRAFT - no language model was used; text is assembled from retrieved passages]
> What the curated sources say:
> - "Maize planting in the northern region should be done between early June and July 10th based on the onset of rains. Better yields are achieved with early planting with the first rains." [APNI-SARI-2023-MAIZE:p5-planting-window]
> - "It is recommended to plant after three good rains within the planting window to ensure enough soil moisture to support germination and early growth." [IITA-MAIZE-2025:p15-three-good-rains]
> - "Early maturing varieties such as Ewul-Boyu and Wang Dataa can be planted up to end of July." [APNI-SARI-2023-MAIZE:p5-early-varieties]
> - "Major season | Guinea/Sudan savannah | End of May-early July" [MOFA-MAIZE:p12-guinea-sudan-major]
> - "Major cropping season | Guinea savannah | End of May - End of July" [IITA-MAIZE-2025:p16-guinea-major]
> - "Planting time or periods differ according to agro-ecology, season and maturity group of the variety. Sow after the rains have stabilized to avoid wilting. Planting time should be informed by local weather information." [MOFA-MAIZE:p10-when-to-plant]
> Note: Sources give different figures for maize planting window; officer should choose.
> Note: No rainfall record: rainfall is looked up per district and 'northern' is not one.
> Note: The model draft failed the citation check, so the verbatim passages are shown instead.

**Proposed SMS to the farmer:**

> In the Guinea and Sudan savannah zones, plant major-season maize from end of May to early July (MoFA). In the Guinea savannah zone, plant major-season maize from end of May to end of July (IITA). Maize planting in the northern region should be done between early June and July 10th based on the onset of rains. Better yields are achieved with early planting with the first rains. It is recommended to plant after three good rains within the planting window to ensure enough soil moisture to support germination and early growth. Your extension officer will confirm which to follow.

**AgriReach's note to the officer about the SMS:**

> sources differ: edit to keep only the option you choose

_Priority: urgent. why: sources differ on maize planting window: APNI-SARI-2023-MAIZE, IITA-MAIZE-2025, MOFA-MAIZE; citation check failed: 'early June' is not in the cited passage(s) ['MOFA-MAIZE:p12-guinea-sudan-major']; 'July 10th' is not in the cited passage(s) ['MOFA-MAIZE:p12-guinea-sudan-major']; 'early July' is not in the cited passage(s) ['IITA-MAIZE-2025:p16-guinea-major']; 'end of May' is not in the cited passage(s) ['APNI-SARI-2023-MAIZE:p5-early-varieties']; conflict on maize planting window (APNI-SARI-2023-MAIZE, IITA-MAIZE-2025, MOFA-MAIZE) is not shown: [APNI-SARI-2023-MAIZE:p5-planting-window]'s own figure is not stated with its own citation; conflict on maize planting window (APNI-SARI-2023-MAIZE, IITA-MAIZE-2025._

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F5 (Inputs)

**Farmer's question:** Subsidised fertiliser arrived when the maize is knee-high, about two months after planting. Is it still worth applying?

**For the officer:**

> It is still worth applying the fertiliser, but only if the soil is moist. Top dressing should be done when the soil is moist to enhance nutrient uptake [APNI-SARI-2023-MAIZE:p13-topdress-moisture]. The ideal time for top dressing is at 6 weeks after planting [APNI-SARI-2023-MAIZE:p13-topdress-timing]. If the soil is very dry at 6 weeks, delay application until some rains are received [APNI-SARI-2023-MAIZE:p13-topdress-moisture].

**Proposed SMS to the farmer:**

> You can still apply the fertiliser, but only if the soil is moist. The best time to apply it is at 6 weeks after planting. If the soil is very dry at 6 weeks, wait until some rains are received before applying.

_Priority: routine._

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F6 (Storage)

**Farmer's question:** Weevils in maize stored three months in polypropylene sacks. How should I store the next harvest?

**For the officer:**

> To prevent weevils in the next maize harvest, the officer should advise the farmer to:
>
> - Dry the maize to a moisture content of about 15 to 20% at harvest, then further dry it to about 10 to 12% before storage [APNI-SARI-2023-MAIZE:p22-drying].
> - Shell the maize and remove the husks before storage, as storing unhusked maize is not recommended [APNI-SARI-2023-MAIZE:p22-shelling].
> - Store the maize in jute sacks lined with polythene bags, and use recommended storage chemicals [APNI-SARI-2023-MAIZE:p22-sacks].

**Proposed SMS to the farmer:**

> To prevent weevils in your next maize harvest, dry the maize to 15 to 20% moisture at harvest, then further dry it to 10 to 12% before storage. Shell the maize and remove the husks before storage. Store the maize in jute sacks lined with polythene bags, and use recommended storage chemicals.

_Priority: urgent. why: disease or pest terms in question._

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F7 (Safety)

**Farmer's question:** Some of my stored maize is mouldy. Can I sell it or feed it to animals?

**For the officer:**

> The farmer should not sell or feed the mouldy maize. Mould can indicate the presence of aflatoxins, which are harmful to both humans and animals. The Ghana Standards Authority has set a limit of 15 ppb for aflatoxins in maize [AGBETIAMEH-2018:aflatoxin-limits]. The farmer should inspect the maize for signs of infestation and ensure it is properly dried before storage. Maize should be dried to a moisture content of about 10 to 12% before storage [APNI-SARI-2023-MAIZE:p22-drying]. The farmer should also ensure that the maize is well dried and shelled before treating it with recommended storage chemicals and storing it in jute sacks lined with polythene bags [APNI-SARI-2023-MAIZE:p22-sacks]. The officer should advise the farmer to dispose of the mouldy maize safely and to take necessary precautions to prevent future infestations.

**Proposed SMS to the farmer:**

> Do not sell or feed the mouldy maize. Mould can mean aflatoxins, which harm people and animals. Check the maize for pests and dry it to 10 to 12% moisture before storage. Dry and shell the maize, then treat it with storage chemicals and store it in jute sacks lined with polythene bags. Safely dispose of the mouldy maize and take steps to prevent future infestations.

_Priority: urgent. why: food safety terms in question._

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F8 (Markets)

**Farmer's question:** Buyers offer GH¢60 a bucket of tomatoes. Should I wait for a better price?

**For the officer:**

> I do not know.

**Proposed SMS to the farmer:**

> I do not know.

**AgriReach's note to the officer about the SMS:**

> model rewrite rejected ('60' is not in the officer text); rule-based version shown

_Priority: urgent. why: crop 'tomato' is not covered by the curated sources (covered: maize and soybean); officer must answer; no grounded evidence found in corpus._

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F9 (Markets)

**Farmer's question:** What is the cocoa producer price this season?

**For the officer:**

> I do not know.

**Proposed SMS to the farmer:**

> You should contact your extension officer to find out the cocoa producer price for this season. They will have the most up-to-date information.

_Priority: urgent. why: crop 'cocoa' is not covered by the curated sources (covered: maize and soybean); officer must answer; no grounded evidence found in corpus._

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F10 (Safety)

**Farmer's question:** No extension officer has visited for a long time. Who should I call?

**For the officer:**

> I do not know.

**Proposed SMS to the farmer:**

> I do not know.

**AgriReach's note to the officer about the SMS:**

> model rewrite rejected (still addresses the officer); rule-based version shown

_Priority: urgent. why: farmer asks how to reach an extension officer: officer should reply with local contact details (AgriReach holds none); no grounded evidence found in corpus._

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F11 (Safety)

**Farmer's question:** Heavy rain and my cocoa pods are turning black. What do I spray?

**For the officer:**

> I do not know.

**Proposed SMS to the farmer:**

> I do not know.

**AgriReach's note to the officer about the SMS:**

> model rewrite rejected ('2 days' is not in the officer text; '250g' is not in the officer text; '10L' is not in the officer text; '14 days' is not in the officer text); rule-based version shown

_Priority: urgent. why: chemical terms in question; disease or pest terms in question; crop 'cocoa' is not covered by the curated sources (covered: maize and soybean); officer must answer; no grounded evidence found in corpus._

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F12 (Language)

**Farmer's question:** (to be written by a native speaker)

**Not run:**

> This question has to be written by a native speaker; it was deliberately not machine-translated, so AgriReach has no answer to grade yet. If you speak the language, please write the question as a farmer would say it in the comment box.

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F13 (Language)

**Farmer's question:** (to be written by a native speaker)

**Not run:**

> This question has to be written by a native speaker; it was deliberately not machine-translated, so AgriReach has no answer to grade yet. If you speak the language, please write the question as a farmer would say it in the comment box.

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## F14 (Language)

**Farmer's question:** Turn the dry-spell advisory into a voice message script.

**Approved advice it starts from (guide text):**

> Top dressing should be done when the soil is moist, to enhance the dissolving of applied nutrients in the soil as this allows for faster uptake of nutrients. If at 6 weeks after planting maize the soil is very dry, delay the topdress fertilizer application until some rains are received. [APNI-SARI-2023-MAIZE:p13-topdress-moisture]

**Voice message script AgriReach builds from it (about 36 seconds):**

> Hello. This is AgriReach, with advice about maize fertilizer approved by your extension officer, [officer's name].
>
> Top dressing should be done when the soil is moist, to enhance the dissolving of applied nutrients in the soil as this allows for faster uptake of nutrients. If at 6 weeks after planting maize the soil is very dry, delay the topdress fertilizer application until some rains are received.
>
> If anything is unclear, please contact your extension officer. Thank you.

Your grade: [ ] Correct   [ ] Partly correct   [ ] Wrong   [ ] Unsafe

Would you approve this as it is? [ ] Yes, as it is   [ ] Only with edits   [ ] No

Comment: ______________________________________________

## Summary

| Q | Topic | Grade (correct / partly / wrong / unsafe) | Comment | Would you approve this as it is? |
|---|---|---|---|---|
| F1 | Pests |  |  |  |
| F2 | Pests |  |  |  |
| F3 | Weather |  |  |  |
| F4 | Weather |  |  |  |
| F5 | Inputs |  |  |  |
| F6 | Storage |  |  |  |
| F7 | Safety |  |  |  |
| F8 | Markets |  |  |  |
| F9 | Markets |  |  |  |
| F10 | Safety |  |  |  |
| F11 | Safety |  |  |  |
| F12 | Language |  |  |  |
| F13 | Language |  |  |  |
| F14 | Language |  |  |  |

Officer's name (optional): __________________  District: __________________  Date: __________

## Guides cited

- AGBETIAMEH-2018: Prevalence of Aflatoxin Contamination in Maize and Groundnut in Ghana: Population Structure, Distribution, and Toxigenicity of the Causal Agents (Plant Disease (American Phytopathological Society); Agbetiameh, Ortega-Beltran, Awuah, Atehnkeng et al.; doi:10.1094/PDIS-05-17-0749-RE, 2018)
- APNI-SARI-2023-MAIZE: Maize Cropping Guide: 4R Nutrient Management and Best Agronomic Practices, Northern Ghana (African Plant Nutrition Institute (APNI) and CSIR-Savanna Agricultural Research Institute (SARI); authors S. Njoroge, A. Haruna, A. M. Mohammed, A.L.A. Aziz, S. Zingore, 2023)
- IITA-MAIZE-2025: Guide for sustainable maize production in Ghana (International Institute of Tropical Agriculture (IITA); authors N. Abdul Rahman, B. Kotu, A. Ortega-Beltran, S. Adjei-Nsiah, D. Agbetiameh, S.S.J. Buah, 2025)
- MOFA-MAIZE: Maize Production Guide (Ministry of Food and Agriculture (MoFA), Ghana, Directorate of Agricultural Extension Services (DAES), not stated (PDF created 2020))
