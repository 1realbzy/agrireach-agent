"""Farmer channels: how a question arrives (text or voice note) and how an officer-approved answer goes back.

base.py       Channel interface, message types, sender-id masking
stt.py        speech-to-text (local faster-whisper)
tts.py        optional text-to-speech for the approved answer (local Piper)
service.py    inbound -> case in the existing agent pipeline; approved + released case -> channel
simulator.py  local channel for demos and tests (files on disk, no outside service)
whatsapp.py   WhatsApp Cloud API adapter: code and docs only, off unless configured (docs/whatsapp-setup.md)
sms.py        Africa's Talking SMS adapter: code and docs only, no account, off unless configured (docs/sms-setup.md)
"""
