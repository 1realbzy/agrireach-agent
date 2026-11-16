# Separate local demonstration portals

Farmer: http://127.0.0.1:8501/
Extension officer: http://127.0.0.1:8502/
Shared API: http://127.0.0.1:8000/

Run `src/agrireach/farmer_ui.py` and `src/agrireach/officer_ui.py` as independent
Streamlit processes. Both use `AGRIREACH_API`; only the API owns case persistence.
There is no role navigation between portals. `ui.py` retains common rendering
helpers and defaults to the farmer portal for compatibility.

With the existing API running, launch each portal in its own terminal:

```powershell
./scripts/start_pilot_ui.ps1 -PilotRoot C:/Users/1realbzy/agrireach-agent -Portal farmer
./scripts/start_pilot_ui.ps1 -PilotRoot C:/Users/1realbzy/agrireach-agent -Portal officer
```

The launcher loads the existing pilot environment and preserves absolute database,
media and outbox locations. It selects port 8501 or 8502 by role. Authentication
continues to use operator-issued officer tokens. Farmer private codes only permit
access to one case. Refreshing the officer app may require sign-in again.

The farmer sees question submission, confirmation, status and approved answers.
Officers retain sources, safety holds, revisions, approval, rejection, sign-out,
and delivery recovery. No API contracts, authorization, approval ledger or safety
rules have changed. Original pilot cases must not be used as verification fixtures.

## Demonstration limits and future capabilities

The current offline configuration assembles draft text from saved source passages;
it does not perform live AI inference. Officer review and approval remain real.
The corpus covers Ghanaian material and is not validated Kenyan farming guidance.

Voice support, local-language support, SMS and WhatsApp are future demonstration
capabilities. Existing backend integrations and tests are retained, but these
features are not offered in either portal or represented as verified services.

## Browser verification

Install developer-only Playwright and Google Chrome. Stop both pilot UIs before:

```powershell
$env:PYTHONPATH = 'src'
python scripts/verify_separate_portals.py
```

This runs both UIs on 8501/8502 with a temporary API on 18000 and its own database,
credential and synthetic case. The API on 8000 and pilot records are not used.
It checks role separation, refresh, invalid credentials, native clipboard sign-in,
queue discovery, source review, pending secrecy, approval, private answer retrieval,
unauthorized access, sign-out and mobile layout. It stops its test services on exit.
Restart both pilot portals afterward. Screenshots mask private access-code fields.

This document supersedes the multipage/voice UI instructions in the earlier
`nairobi-pilot-demo.md`; that document remains historical evidence.
