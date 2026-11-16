# UX audit — farmer and officer portals

Baseline: `53cf0f6632b87d9df73af889069f64a7c334528e` (tree `667cdccaccb526bf135fdede23517be2a58ef99e`).

Observed on a disposable offline demonstration of commit `53cf0f6`, started on `http://127.0.0.1:18501` (farmer) and `http://127.0.0.1:18502` (officer) so the processes already listening on 8501 and 8502 were left alone.

Screenshots of the baseline, before the copy changes:

- `docs/ux/audit/farmer-first-view.png` — first screen, question form, no statement that a phone number is not a sign-in.
- `docs/ux/audit/farmer-case-lookup.png` — question number and private access code presented before a question has been asked. The Streamlit "Rerun / Always rerun" controls appeared after a file-watch notice; they are not part of the farmer task.
- `docs/ux/audit/officer-signin-token.png` — officer entry is a pasted access token, with Bearer-prefix instructions.

## Severity

### High — functionality and trust

1. **Farmers are shown a question number and a private access code before they have asked anything.** On first load, "Check a different question" is expanded. It asks for a question number (default 1) and a private access code, and says both are required to see an answer. That is a developer recovery control presented as the main path.
2. **A successful question tells the farmer to keep the question number and private code.** The success text includes the case id. The requirements say farmers must not memorize case reference numbers, and the page must not expose access tokens.
3. **Officers sign in by pasting a token.** The label is "Officer sign in token", with instructions about a Bearer prefix. There is no email and password sign-in. The verified API only accepts `Authorization: Bearer <token>` from `scripts/add_officer.py`.
4. **A phone number is not a sign-in, but the page does not say that.** The number is optional and is sent only when the SMS checkbox is checked. Nothing in the first screen says that typing a number does not identify the farmer.

### Medium — clarity

5. **The first screen does not say what AgriReach is for.** The title "Advice for your next step" does not mention crops, Ghana, or that an officer checks the answer.
6. **Empty submit and invalid-phone warnings sit between two large cards**, so the warning is easy to miss under the lookup form.
7. **Officer safety findings are present but easy to skim past.** Holds render as captions and a warning inside a long case expander, after delivery and acknowledgement details.
8. **Source passages are behind "Read source evidence".** Source titles are a caption. The passage text is collapsed.
9. **The tool record is not shown.** `GET /officer/cases/{id}` returns `log`, and the queue payload does not. The screen never requests or displays it, so a judge cannot see which agricultural tools ran.
10. **Farmer failures reuse officer wording.** A connection error uses the officer message about assessment, approval, and a case number.
11. **Released and approved are distinguished in code** (`STATES` says release is still pending when status is `approved`). The success path still leads with the case id, which competes with that distinction.

### Low — cosmetic and accessibility

12. **The SMS checkbox is exposed to assistive technology as readonly** even though a pointer can change it. That comes from Streamlit's checkbox markup. The visual control does start unchecked.
13. **The officer dashboard is a wide two-column layout.** On a narrow screen the queue and the review sit in one tall scroll. Buttons are already 48px tall.
14. **Captions are grey-green on the page background.** Contrast was already raised in CSS; it is readable but secondary text still carries important instructions.

## What already works

- Farmer question submission posts `{question}` and adds `phone` and `sms_consent` only when the box is checked.
- An invalid Ghana number is rejected locally and the typed number is not repeated.
- A blank question is rejected before any request.
- The farmer sees a pending state ("Advice is not available yet") and sees answer text only when the API returns `answer`.
- Officer approval still requires the source-check confirmation. Reject and request-info require a note and a second confirmation.
- Sign-out clears the officer credential and leaves the farmer tab credential alone.
- Refresh restores a tab credential only after the API accepts it. Storage is `sessionStorage`, not `localStorage`, and it expires after at most 8 hours.
- English only. No language switch, translation, or speech control is offered on these portals.

## Security notes (not fixed in the interface alone)

- The officer bearer token and the farmer case token are kept in tab `sessionStorage` so a refresh can restore them. That is not permanent storage, and another script on the same origin can read it. The replacement is an HttpOnly session from the authentication API. This branch does not remove the working refresh path, and it does not put the new password into storage.
- There is no server logout. Sign-out only forgets the token in the browser. The token remains valid until it is replaced.

## Corrections made on `work/cursor-ux-farmer-officer`

- Farmer page leads with the crop question. Phone is labeled as an optional text update. The lookup form is collapsed.
- The farmer success and status views no longer show the question number. The tab still holds the credential for refresh and "Check for updates".
- Farmer send and detail failures use plain sentences and do not claim anything was saved or approved.
- Officer page shows an email and password form that does not call the API and does not keep the password, with the working access-code sign-in under "Current access code".

## Browser check on the disposable demo

- Farmer: empty question shows "Enter a question before sending." An invalid number with the text-update box checked shows the Ghana number instruction and does not repeat the typed digits. The closed-tab lookup stays collapsed.
- A real question, "When should I plant maize in Tamale?", was saved as waiting for review. A Streamlit reload during that long request cleared the browser session before the success card could be captured.
- Officer: the email and password form is on the page and says it is not connected. `docs/ux/audit/officer-signin-pending.png`.
- The signed-in queue, source passages, safety findings, and approve or reject were not clicked in the browser. The access code is still the only working sign-in, and pasting it into the browser was not completed. Automated tests cover token sign-in, an empty queue, sign-out, and the safety-finding text.
- A phone-width capture was not confirmed. The page CSS stacks the officer columns below 800px. The screenshot that was taken stayed wide.
- The review queue is labeled with the question. Opening a question loads the tool record, shows source names and passages, and puts safety findings in their own step.
- Approval, rejection, request-info, delivery recovery, and sign-out behave as before.

## Still blocked on the backend

- Email and password cannot sign an officer in.
- A farmer who closes the tab cannot return by phone number. The collapsed lookup remains because it is the only supported recovery.
- Session expiry for email sign-in cannot be demonstrated.
- Logout cannot revoke a server session.
