# MOC Automation Platform — User Manual

**URL:** https://workspace.moc-pty.com

---

## Getting Started

### Logging In

1. Go to https://workspace.moc-pty.com
2. Enter your username and password
3. You'll land on the **Home** dashboard

| Username | Password         |
|----------|------------------|
| Ethan    | *(existing)*     |
| Anthony  | MOC@Anthony2026  |
| Peter    | MOC@Peter2026    |
| Armand   | MOC@Armand2026   |
| Jane     | MOC@Jane2026     |

To change your password, ask an admin or go to **Users** in the sidebar.

---

## Navigation

The sidebar on the left expands when you hover over it. Here's what each section does:

| Page | What It Does |
|------|-------------|
| **Home** | Dashboard overview — total records, active stations, planner progress, and quick links |
| **Data Analysis** | All 21 data stations with record counts, sync buttons, and last synced times |
| **Sync Monitor** | Live health status of every station — shows green (OK) or red (error) |
| **Users** | Add, edit, or remove user accounts |
| **US-EU List** | Contact list for email touchpoints |
| **Settings** | Toggle dark/light mode (saved per user) |
| **Planner** | Kanban task board for tracking project work |
| **Gantt Chart** | Timeline view of tasks with start and end dates |

---

## Data Analysis

This is the main page for all your financial and operational data.

### What You See

Each **station card** shows:
- The station name (e.g. "ATL Financial Analysis")
- Current record count in the database
- A **Sync** button to manually refresh the data
- A **Last synced** timestamp showing when data was last pulled

Click on any card to open its **detail page**, which shows:
- Full stats (records, branches, periods, budget vs actual)
- Table structure (column names and types)
- Database connection details for Power BI
- SQL query and M Code — ready to copy and paste into Power BI

### Stations

There are 21 stations pulling data from OneDrive:

**Turnover Report** — Revenue by debtor across all branches
- Branches: ATL, DFW, HEC, HNL, HOU, ICS, IMP, JFK, LAX, LCL, ORD, PPG, CON-DOR
- Updates weekly with new debtor period analysis files

**PNL Stations** — Budget vs Actual profit & loss for each branch
- ATL, CCC, CCD, CON, DOR, FAX, HNL, HOU, ICS, IMP, JFK, LAX, LCL, ORD, DFW, PPG
- Each has its own database table (e.g. `atl_pnl`, `dfw_pnl`)

**Condor+DOR PNL** — Combined P&L for departments CON, FEA, TRX, BRK

**Creditor Report** — Creditor payables grouped by creditor group and branch

**Import Operations** — Import operational report data

**WIP & Accrual Report** — Work in progress and accrual figures

---

## How Data Syncing Works

### The Process

```
Excel files land in OneDrive
        ↓
Platform downloads and processes them (every hour)
        ↓
Data is inserted into PostgreSQL database
        ↓
Processed files are deleted from OneDrive
        ↓
Power BI reads from the database
```

You don't need to do anything — syncing happens automatically every hour.

### Manual Sync

Sometimes you may want to sync immediately instead of waiting for the next cycle.

**Sync one station:**
1. Go to **Data Analysis**
2. Click the **Sync** button on the station card
3. Wait for the spinner to finish — the page reloads with updated numbers

**Sync all stations at once:**
1. Go to **Data Analysis**
2. Click **Sync All Stations** (top right)
3. Progress shows how many stations have completed

**Sync from a station detail page:**
1. Click on a station card to open it
2. Click **Sync Now** (top right)
3. A progress message shows the status

### What Happens During a Sync

1. The platform checks the OneDrive folder for new Excel files
2. Each file is downloaded and the data is extracted
3. New data is inserted into the database (duplicates are handled automatically)
4. The processed Excel file is deleted from OneDrive so it's not synced again
5. The "Last synced" timestamp updates

### If a Sync Fails

- Check the **Sync Monitor** page — it shows which stations have errors
- The most common issue is an expired OneDrive token (shows as "Token expired")
- If the token is expired, go to **Settings** or contact Ethan to re-authenticate
- Files with incorrect formats will be skipped — they must be `.XLS` or `.XLSX`

---

## Connecting Power BI

Every station page shows everything you need to connect Power BI.

### Connection Details

| Setting | Value |
|---------|-------|
| Host | `workspace.moc-pty.com` |
| Port | `5432` |
| Database | `turnover_data` |
| Username | `powerbi` |
| Password | *(shown on each station page)* |

### Steps

1. Open Power BI Desktop
2. Click **Get Data** → **PostgreSQL database**
3. Enter the host and database from above
4. Paste the **M Code** from the station page into the **Advanced Editor**
5. The data will load with properly named and typed columns

Each station page has a **Copy** button next to the SQL query and M Code so you can paste directly.

---

## Sync Monitor

The Sync Monitor page gives you a real-time view of the health of all syncs.

### Status Indicators

| Status | Meaning |
|--------|---------|
| **Green** | Last sync was successful |
| **Red** | Last sync encountered an error |
| **Token: Active** | OneDrive connection is working |
| **Token: Expired** | OneDrive needs to be re-authenticated |

### What to Check

- **All green** — everything is working normally
- **One station red** — that station's OneDrive folder may have a corrupt file or no files
- **Multiple stations red** — likely a token issue — check the token status
- **Token expired** — contact Ethan to re-authenticate OneDrive

---

## Planner

The Planner is a Kanban board for tracking tasks across projects.

### Columns

| Column | Meaning |
|--------|---------|
| **Backlog** | Ideas and future work |
| **To Do** | Approved and ready to start |
| **In Progress** | Currently being worked on |
| **Review** | Done but needs review |
| **Done** | Complete |

### How to Use

- Click **+ New Task** to create a task
- Click any task card to edit it (change title, description, status, priority, dates)
- Set a **Project** name to group related tasks
- Set **Start Date** and **End Date** if you want the task to appear on the Gantt Chart
- Click **Delete** in the edit modal to remove a task

### Priority Levels

| Priority | Color |
|----------|-------|
| Critical | Red |
| High | Yellow |
| Medium | Blue |
| Low | Green |

---

## Gantt Chart

The Gantt Chart shows all tasks that have start and end dates on a timeline.

### Features

- **Project groups** — tasks are grouped by project with a summary bar
- **Color coding** — bars are colored by status (green = done, blue = in progress, etc.)
- **Today line** — a red vertical line marks today's date
- **Zoom** — switch between Week and Day view
- **Filter** — filter by project using the dropdown

### Tips

- Tasks only appear here if they have both a start date and end date set in the Planner
- Click **Planner** link in the top right to go back to the board view
- Use Week view for a high-level overview, Day view for detail

---

## US-EU Contact List

Manage the contact list used for email touchpoints.

- **Add contacts** — click Add to create a new contact
- **Edit inline** — click any cell in the table to edit directly
- **Send touchpoints** — use the email templates section to send bulk emails
- **Status** — contacts can be Active, Undeliverable, Lost, or Move to HubSpot

---

## Settings

### Dark Mode

1. Go to **Settings** in the sidebar
2. Toggle **Dark Mode** on or off
3. Your preference is saved and applies every time you log in

---

## Frequently Asked Questions

**Q: How often does data sync?**
Every hour, automatically. You can also sync manually at any time.

**Q: Why does a station show 0 records?**
The database table exists but no data has been synced yet. Check OneDrive to make sure files are being delivered to the correct folder.

**Q: Why is a sync failing?**
Check the Sync Monitor page. Common causes:
- OneDrive token expired (needs re-authentication)
- File format is wrong (must be .XLS or .XLSX)
- OneDrive folder path changed

**Q: Can I add a new station/branch?**
Yes — contact Ethan. A new OneDrive folder, database table, and sync function need to be set up.

**Q: How do I get the Power BI connection string?**
Click on any station card from the Data Analysis page. The connection details, SQL query, and M Code are all displayed with copy buttons.

**Q: The page is stuck loading — what do I do?**
Try refreshing the browser. If it persists, the server may need a restart — contact Ethan.

---

## Server Administration

*For admins only.*

### Restart the service
```bash
sudo systemctl restart gunicorn-automation
```

### Check logs
```bash
sudo journalctl -u gunicorn-automation --no-pager -n 50
```

### Deploy updates
```bash
cd /var/www/Automation-Platform
git stash
git pull origin master
sudo systemctl restart gunicorn-automation
```

### Run locally
```bash
cd automations
python manage.py runserver
```