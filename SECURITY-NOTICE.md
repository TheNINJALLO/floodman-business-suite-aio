# Security notice

This source archive is intentionally sanitized, but it should still be stored in a private repository. Run `python scripts/verify_repo.py` and an independent secret scanner before pushing.

The project handles customer data, payment workflows, signed documents, field photos, staff schedules, and device sessions. Treat all production configuration and runtime data as sensitive.

Never copy live Pterodactyl `data`, `config`, PostgreSQL, signing, Tailscale, or payment directories into this repository.
