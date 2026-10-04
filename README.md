# Telegram Report Workflow Bot — Render Deployment

This project is a Telegram report-intake/workflow bot. It records user-submitted reports and lets authorized admins review, approve, or reject them. It does **not** automate abuse reports against Telegram or third-party services.

## Render setup

1. Create a new **Web Service** from this repository.
2. Runtime: Python.
3. Render will use `render.yaml` if Blueprint deployment is enabled. Otherwise use:
   - Build: `pip install -r requirements.txt`
   - Start: `python bot.py`
4. Add these environment variables in Render:
   - `BOT_TOKEN` = token from BotFather
   - `ADMIN_IDS` = comma-separated Telegram numeric user IDs, e.g. `123456789,987654321`
   - `SUPER_ADMIN` = one Telegram numeric user ID (optional)
5. Deploy and check `https://<your-service>.onrender.com/health` — it should return a healthy JSON response.

## Important Render/free-plan note

SQLite is local to the service filesystem. On Render free infrastructure, local data should be treated as **non-persistent** across rebuilds/redeploys/restarts. For production data durability, replace SQLite with a managed PostgreSQL database and set the connection string through an environment variable.

The service also uses Telegram polling plus a lightweight HTTP health server so it satisfies Render Web Service port requirements.

## Local run

```bash
pip install -r requirements.txt
export BOT_TOKEN='...'
export ADMIN_IDS='123456789'
python bot.py
```
