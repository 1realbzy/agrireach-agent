# AgriReach controlled demonstration deployment gate

Status: preparation only. This is **not a production deployment** or approval to
expose the portals publicly.

## Current deployment package

`Dockerfile` installs pinned dependencies and bundles the existing API, Streamlit
portals and curated, read-only agricultural knowledge files.
`compose.demo.yaml` defines three processes and a persistent disposable data
volume. Every published port binds to host loopback only, so none is directly
accessible from the internet. No model credentials or outbound messaging are
enabled in this deployment configuration.

When Docker and Compose are available, perform these tests on a separate demo
machine or isolated VM, never on the historical pilot database:

1. Inspect `docker compose -f compose.demo.yaml config` and verify that the
   service names, volumes, ports and environment are as intended.
2. Run `docker compose -f compose.demo.yaml up --build -d`.
3. Verify `http://127.0.0.1:8000/health`, `http://127.0.0.1:8501/_stcore/health`
   and `http://127.0.0.1:8502/_stcore/health`.
4. Create a disposable officer credential within the API container using
   `docker compose -f compose.demo.yaml exec api python scripts/add_officer.py 'Demo Officer'`.
   Protect the credential; never include it in screenshots or logs.
5. Submit a synthetic soybean harvest case and verify both browser portals,
   refresh recovery, officer approval and farmer retrieval.
6. Verify blocked pesticide mixing, bad farmer codes, invalid officer tokens and
   release without approval remain denied. Reboot the services and confirm the
   case database persists without reusing the real pilot data.
7. Verify test records and credentials are removed from the disposable test
   environment according to its retention plan, after evidence is captured.

## Blocking requirements before public HTTPS exposure

- Select and provision a controlled hosting environment and DNS name(s).
- Set up HTTPS and access controls in front of the officer portal. The current
  officer bearer token is readable by page scripts and is not server-expiring.
  This remains an operational risk and must not be described as production ready.
- Restrict direct access to the internal API and disable public simulator routes.
- Configure database backups and recovery tests, process health monitoring,
  restart policy and log retention without recording private farmer text or keys.
- Verify Streamlit websocket support and reverse-proxy headers for the chosen
  hosting provider. Do not assume static hosting can run these Python services.
- Verify the exact deployed commit, source provenance, branch, costs and fallback.
- Keep all demonstrations synthetic. The current offline stub is not evidence
  of real model execution. Run paid inference separately under an approved cap.
- Enable external source checking only after its results and failures can be
  inspected and its limitations are clearly disclosed.
- Never enable real SMS, WhatsApp or voice delivery without separate review.

## Product gaps not fixed by containerization

Risk-based autonomous advisory release, follow-up management, institution-wide
officer assignments, source-check audit persistence, server-side session expiry,
and production incident management are not implemented by this deployment.
The existing human approval gate remains mandatory.
