# Voice-note channel (local only)

Status, 25 Oct 2026: built and tested on this machine only. Nothing is hosted, no phone number is connected, and no
webhook is registered with any outside service.

## What it does

```
farmer phone (simulated)            AgriReach                                   officer
  voice note / text + sender id --> channels.service.handle_inbound
                                      1. de-duplicate by message id
                                      2. speech-to-text (faster-whisper, local)   STT warnings -> urgent reasons
                                      3. agent.run(question, extra_urgent_reasons)  -> case (pending_review)
                                      4. store the sender id with the case (channel_contacts)
  <-- acknowledgement or clarifying question (never advice)
                                                                                  reviews, approves (named officer)
                                                                                  releases
                                    channels.service.deliver  <-------------------
                                      refuses unless status == released, an officer is named and final_text exists
  <-- approved text (+ optional Piper audio)
```

The officer-approval gate is unchanged: `deliver` sends nothing for a case that is not `released`, and logs the
blocked attempt. Before approval the only automatic messages are a fixed acknowledgement ("waiting for an extension
officer") or the existing clarifying question. When an STT warning is raised (no speech, not English, low language
confidence, STT off or failed), no automatic clarifying question is sent either: the case goes to the officer as
urgent, with the suggested question in the urgent reasons.

## Pieces

| File | What |
|---|---|
| `src/agrireach/channels/base.py` | `InboundMessage`, `OutboundMessage`, `Channel` protocol, `mask_sender` (logs keep only the last 2 characters) |
| `src/agrireach/channels/service.py` | `handle_inbound`, `deliver`, `configured_channels` |
| `src/agrireach/channels/stt.py` | faster-whisper wrapper and the warning rules |
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
PYTHONPATH=src python -m agrireach.channels.simulator officer-approve --case <id> --officer "Officer name"
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
  this so the docs get updated if it changes. Checked through the simulator: the transcript was "When should I plant
  soybean at war?", so the region was missed and the farmer got the automatic "Which district or region is your
  farm in?" question. Safe, but annoying for a farmer who already said it.
- Simulator end to end with real STT: voice note -> case pending review -> only the acknowledgement in the outbox ->
  officer approves and releases -> the approved text is delivered.
- Piper speaks an approved answer and Whisper transcribes it back (a sanity check, not a quality measure).

Not tested:

- **Ghanaian-accented English.** No real farmer recordings were used. Accuracy on real voice notes (accent, phone
  microphones, wind and background noise) is unknown and may be much worse.
- **Twi, Dagbani, Wali or any Ghanaian language.** Whisper does not support them. Such notes should be detected as
  another language and flagged for the officer to listen to, but this was checked only with a mocked transcriber,
  not with real Twi audio.
- Ghanaian-English or Twi TTS voices: the Piper voice is US English.
- Load, concurrency, long notes, or a real WhatsApp number.

## Personal data

- The simulator only accepts `sim:` ids.
- A real channel (WhatsApp) has to store the sender's phone number with the case (`channel_contacts.sender_id`) to
  reply. That is personal data: it stays in the local SQLite file, is never logged unmasked, and is shown masked in
  the officer API. A retention and deletion policy, and farmer consent wording, are still needed before real use.
- Voice notes are saved under `data/media/` (git-ignored) with random file names.
