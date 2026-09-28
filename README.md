# Podshift

Personal bedtime controller. Reads Whoop recovery and shifts saved Eight Sleep Autopilot levels before bed.

This repository is public so Whoop can load [PRIVACY.md](PRIVACY.md). Do not commit secrets.

## Ignored on purpose

`.gitignore` keeps these out of git:

- `.env` (Whoop client id/secret, Eight Sleep email and password)
- token and session files
- the authorize URL and the last-run log

Copy `.env.example` to `.env` and fill it in locally.

The Eight Sleep `CLIENT_ID` and `CLIENT_SECRET` in the scripts are the public mobile-app OAuth client, the same values published by community clients such as eightctl. They are not a personal password.
