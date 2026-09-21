# MOC Automation Platform

Internal automation and reporting platform for MOC.

## Server

**URL:** https://workspace.moc-pty.com

Service: `gunicorn-automation`

Restart after changes:
```bash
sudo systemctl restart gunicorn-automation
```

---

## User Accounts

| Username | Password         | Notes        |
|----------|------------------|--------------|
| Ethan    | *(existing)*     | Admin        |
| Anthony  | MOC@Anthony2026  | Created Mar 2026 |
| Peter    | MOC@Peter2026    | Created Mar 2026 |
| Armand   | MOC@Armand2026   | Created Mar 2026 |

Manage users at: https://workspace.moc-pty.com/users/

---

## Features

- **Dashboard** — home page with sync status overview
- **Reports** — Turnover, Connections, and other data reports
- **Sync Monitor** — tracks OneDrive sync health per branch
- **Power BI** — embeddable Power BI report sections on each page
- **User Management** (`/users/`) — add, edit passwords, delete accounts
- **Settings** (`/settings/`) — light/dark mode toggle (saved per user)

---

## Development

### Requirements
- Python 3.x
- Django
- gunicorn

### Run locally
```bash
cd automations
python manage.py runserver
```

### Apply migrations
```bash
python manage.py migrate
```
