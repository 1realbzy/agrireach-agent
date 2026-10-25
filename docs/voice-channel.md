# Voice-note channel (local only)

Status, 25 Oct 2026: built and tested on this machine only. Nothing is hosted, no phone number is connected, and no
webhook is registered with any outside service.

## What it does

```
farmer phone (simulated)            AgriReach                                   officer
  voice note / text + sender id --> channels.service.handle_inbound
                                      1. de-duplicate by message id; retention purge
                                      2. STOP -> delete number, held messages, voice notes
                                      3. first contact: hold the message, send the consent prompt; YES releases it
                                      4. speech-to-text (faster-whisper, local)   STT warnings -> urgent reasons
                                      5. misheard place? ask "Did you mean Wa (Upper West Region)?" and hold
                                      6. agent.run(question, extra_urgent_reasons)  -> case (pending_review)
                                         + a proposed farmer-facing text
                                      7. store the sender id with the case (channel_contacts)
  <-- acknowledgement, clarifying, consent or location question (never advice)
                                                                                  reviews the cited draft and the
                                                                                  farmer text; approves that exact
                                                                                  farmer text (named officer)
                                    channels.service.deliver  <-------------------
                                      refuses unless status == released, an officer is named, the sender
                                      was not removed, and approved text exists
  <-- the approved farmer text, as approved (+ optional Piper audio of it)
```

The officer-approval gate is unchanged: `deliver` sends nothing for a case that is not `released`, and logs the
blocked attempt.

A failed send after release moves the case to `not_delivered`, back into the officer queue. A farmer who sent STOP,
or whose number was removed by the retention purge, makes it `undeliverable`. So for a channel case, `released`
always means the channel accepted the message. The full status table is in [sms-setup.md](sms-setup.md#case-statuses-all-channels). Before approval the only automatic messages are fixed system texts: the acknowledgement, the
existing clarifying question, the consent prompt, the location question and the STOP confirmation. When an STT
warning is raised (no speech, not English, low language confidence, a transcript that repeats itself, STT off or
failed), no automatic clarifying question is sent: the case goes to the officer as urgent.

## Farmer-facing reply

The officer's draft keeps its citations and notes. For each case AgriReach also proposes a short farmer version
(`src/agrireach/farmer_reply.py`): plain language, no citation brackets, no "the officer should advise" wording, at
most 600 characters, and no figure that isn't in the officer text. The model writes it; `check()` rejects a rewrite
that breaks any of those rules and a rule-based rewrite is shown instead. The officer sees the proposal (and why it
needs attention: sources differ, Northern Ghana caution left out, rewrite rejected) in an editable box, can
re-propose it from an edited officer draft (`POST /officer/cases/{id}/farmer-draft`), and approves that exact text:
`farmer_text` is required to approve, and it is what is sent and spoken. Questions in Twi get no proposal; the
officer writes the farmer text (AgriReach can't write Twi).

## Place names after speech-to-text

`src/agrireach/channels/location.py` looks for a word in a location slot ("near X", "in X", "X district") that isn't
one of Ghana's 16 regions, 261 districts or their capitals (`data/gazetteer.json`) but sounds like one: a small table
of confusions (war -> Wa, tamali -> Tamale, ...) or a close spelling (difflib >= 0.8, words of 5+ letters). It never
corrects silently. The message is held and the farmer is asked "I heard "war". Did you mean Wa (Upper West Region)?
Reply YES, or tell me your district or town." YES, or a reply naming a place, updates the question (the machine
transcript is kept for the officer); anything else files the original with the urgent reason "location
unconfirmed". Only voice transcripts are checked, not typed text.

## Consent, STOP and retention

- First contact from a sender: the message is held and the farmer gets "AgriReach: an agricultural extension
  officer will answer your farming question here. To reply, we keep your number and any voice note for up to 90
  days. Reply YES to continue. Reply STOP at any time and we delete them." YES releases the held message.
- STOP (or "gyae", or NO to the prompt) at any time: held messages, voice notes and the consent record are deleted
  and the stored number is replaced with `[removed]`, so nothing more can be delivered. Case text and the officer's
  decision stay, anonymised.
- Retention: `AGRIREACH_RETENTION_DAYS` (default 90). The purge runs on every inbound message and from
  `python -m agrireach.channels.retention [--days N]` (e.g. a daily cron job).
- `AGRIREACH_CONSENT=0` turns the prompt off (used by the older tests only).
- The wording has not been reviewed by a lawyer or tested with farmers, and Ghana's Data Protection Act 2012
  (Act 843) obligations (e.g. registration with the Data Protection Commission) were not assessed.

## Pieces

| File | What |
|---|---|
| `src/agrireach/channels/base.py` | `InboundMessage`, `OutboundMessage`, `Channel` protocol, `mask_sender` (logs keep only the last 2 characters) |
| `src/agrireach/channels/service.py` | `handle_inbound`, `deliver`, `configured_channels` |
| `src/agrireach/channels/stt.py` | faster-whisper wrapper and the warning rules |
| `src/agrireach/channels/location.py` | misheard place-name suggestions and reply parsing |
| `src/agrireach/channels/retention.py` | retention purge CLI |
| `src/agrireach/farmer_reply.py` | farmer-facing text proposal and its checks |
| `src/agrireach/channels/tts.py` | optional Piper TTS (`AGRIREACH_TTS=piper`) |
| `src/agrireach/voice_script.py` | approved text -> voice script: names AgriReach and the officer first, strips citations, keeps every sentence and figure, flags (never cuts) scripts over 150 s at 130 wpm |
| `src/agrireach/channels/simulator.py` | simulated phone: CLI, outbox file; sender ids must match `sim:<name>` so a real number can't be typed in |
| `src/agrireach/channels/whatsapp.py` | WhatsApp Cloud API adapter, code only, off by default ([setup](whatsapp-setup.md)) |
| API | `POST /channels/simulator/inbound`, `GET /channels/simulator/outbox`, `GET /officer/cases/{id}/voice`, `GET /officer/cases/{id}/audio` |
| UI | Streamlit tab "Voice note (simulator)"; the officer tab shows the masked sender, the audio and the machine transcript; STT warnings appear in the urgent reasons |

## Running it locally

```bash
pip install -r requirements-voice.txt          # faster-whisper 1.2.1, av 15.1.0 (av 19 broke faster-whisper here), piper-tts 1.8.0
# optional voice for spoken answers
python -m piper.download_voices en_US-lessac-medium --data-dir ~/.cache/agrireach/piper

PYTHONPATH=src python -m agrireach.channels.simulator ask --sender sim:farmer-1 \
    --audio tests/fixtures/audio/en_harvest_tamale_piper.wav
PYTHONPATH=src python -m agrireach.channels.simulator ask --sender sim:farmer-1 --text yes   # consent
PYTHONPATH=src python -m agrireach.channels.simulator officer-approve --case <id> --officer "Officer name" \
    --accept-proposed      # or --farmer-text "..." ; prints the text being approved
PYTHONPATH=src python -m agrireach.channels.simulator outbox --sender sim:farmer-1
```

The Whisper "base" model (~145 MB) is downloaded from Hugging Face into `~/.cache/agrireach/whisper` on first use.
Audio never leaves the machine.

## What was tested, and what was not

Tested (see `tests/test_stt_real.py`, which runs only when the model is cached):

- Real faster-whisper "base" (CPU, int8) on two synthetic English clips made with Piper (US voice
  en_US-lessac-medium) and on one of them re-encoded to OGG/Opus, the format WhatsApp voice notes use.
- "When should I harvest my soybean? I farm near Tamale." is transcribed correctly, with "Tamale" spelt right only
  because of a vocabulary hint (`stt.PROMPT`); without it the model wrote "Tamali".
- Known failure: "When should I plant soybean at Wa?" is heard with "Wa" as "war", even with the hint. A test pins
  this. With the location check, the farmer is now asked "Did you mean Wa (Upper West Region)?" and a YES files
  "When should I plant soybean at Wa?" with region Wa (`test_misheard_wa_is_confirmed_back_not_guessed`, real STT).
- Simulator end to end with real STT: voice note -> case pending review -> only the acknowledgement in the outbox ->
  officer approves and releases -> the approved text is delivered.
- Piper speaks an approved answer and Whisper transcribes it back (a sanity check, not a quality measure).

Not tested:

- **Ghanaian-accented English, partly.** Run S1 (`scripts/stt_ghana_check.py`, results in
  [eval-run-2026-10-25-stt-ghana.txt](eval-run-2026-10-25-stt-ghana.txt)): 10 clips of Ghanaian broadcast English
  from the Ghana English ASR Dataset (CC BY-NC 4.0, not committed). Whisper "base" word error rate 52.5% (106/202
  words) against the dataset's own transcripts, which also contain errors. Language was detected as something other
  than English (Yoruba, Swahili, Spanish, French) in 7 of 10 clips, and English confidence was below 0.6 in the other
  3, so all 10 would go to the officer as urgent with "listen to the audio"; two were nonsense (Spanish/French text).
  Of 5 Ghana place mentions, 2 were transcribed right (Kumasi, Upper East); Koforidua became "akotea", Ashanti "their
  Shanti", Upper East "Papa is". No location question was raised (none of these were in a location slot). Forcing
  English was tried and made it worse: on two clips Whisper repeated the vocabulary hint ("The land of Wa,
  Bolgatanga, Wa, Bolgatanga..."), inventing place names; that is why language stays auto-detected and a transcript
  that repeats itself is now flagged. These are news readers on studio microphones, not farmers on phones;
  real voice notes are still untested and likely worse. A larger Whisper model or an accent-tuned one was not tried.
- **Twi, Dagbani, Wali or any Ghanaian language.** Whisper does not support them. Such notes should be detected as
  another language and flagged for the officer to listen to, but this was checked only with a mocked transcriber,
  not with real Twi audio.
- Ghanaian-English or Twi TTS voices: the Piper voice is US English.
- Load, concurrency, long notes, or a real WhatsApp number.

## Personal data

- The simulator only accepts `sim:` ids.
- A real channel (WhatsApp) has to store the sender's phone number with the case (`channel_contacts.sender_id`) to
  reply. That is personal data: it stays in the local SQLite file, is never logged unmasked, is shown masked in the
  officer API, and is removed on STOP or after the retention period (above).
- Voice notes are saved under `data/media/` (git-ignored) with random file names, and deleted with the number.
