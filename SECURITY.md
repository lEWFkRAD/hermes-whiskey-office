# Security

Use [GitHub private vulnerability reporting](https://github.com/lEWFkRAD/hermes-whiskey-office/security/advisories/new). Do not publish credentials, conversation contents, private host details or exploit payloads in an issue. Maintainers will acknowledge as availability permits; this community project has no guaranteed response SLA.

Only the current `main` branch receives fixes. Experimental releases are not a security certification. Report affected commit/versions, a synthetic reproduction, impact and suggested mitigation if known. Coordinated disclosure should allow a reasonable time to investigate and fix the issue.

The office starts local applications under your user account; those applications and Hermes keep their existing permissions. Window-source commands are trusted operator configuration, never model output. Context and document labels are untrusted data. Do not disable SSH host verification or forward private keys to agents.

Object Studio's inherited local API has no network authentication layer. Its documented launcher binds loopback only; access it from another computer through an authenticated SSH tunnel. Do not expose it directly to the internet. Audio and model credentials stay in the operator's Hermes installation, outside this repository.
