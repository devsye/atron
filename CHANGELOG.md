# Changelog

## v1.1 — report group hub
- New: connect a Telegram forum group; the bot grabs the group ID automatically when you make it admin (or via `/setup`, `/id`, or manual ID).
- Creates 10 topics: overview, charts, backups, users export, top users, panel status, alerts, trash, migration, operations log.
- Works for ALL registered panels (new panels are included automatically).
- Scheduled sending per job (off / 6h / 12h / daily / 3 days / weekly) + "send now" button.
- Alerts are mirrored to the group (optionally muted in private chat).
- Operations (edit / reset / revoke / delete / restore / migrate / add-remove panel) are logged to the group.
- Lightweight: no new dependencies (Termux-friendly); charts fall back to text if matplotlib is missing.
- Fix: user export file names now include the panel host.
- Fix: topic re-check no longer leaves test messages in existing topics.
- Fix: "send now" while the hub is paused now says so instead of reporting success.
- New logo in README.

## v1.0 — first public release
- First open-source release of ATRON (آترون) by SYE.
- Multi-panel management for PasarGuard via Telegram inline buttons.
- Env-based configuration (`.env`), no secrets in the repo.
- Permanent deployment: systemd installer, Docker, Termux (testing).

More updates are on the way.
