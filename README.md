# TLI Driver Time Record — Deployment Guide

## Overview
Mobile-friendly timecard app for TLI dump truck drivers.
- Driver selects truck + date → Geotab auto-fills start/end time, miles, driving hours
- Driver confirms, adds job site, completes pre-trip checklist, submits
- Records stored permanently in Supabase (PostgreSQL)

---

## One-Time Infrastructure Setup

### Step 1 — GitHub (10 min)
1. Go to github.com and create a free account
2. Click **New repository** → name it `tli-apps` → Create
3. You don't need to know Git — Render can deploy from a zip upload instead

### Step 2 — Supabase (10 min)
1. Go to supabase.com → Sign up → **New Project**
2. Settings:
   - Organization: `Takehara Landscape`
   - Project name: `tli`
   - Database password: generate strong one, save it
   - Region: `West US (North California)`
3. Wait ~2 min for provisioning
4. Go to **Settings → API** and copy:
   - **Project URL** → looks like `https://abcdefgh.supabase.co`
   - **service_role** key (the long one — NOT the anon key)
5. Create the database table:
   - Go to **SQL Editor** in the left sidebar
   - Paste and run this SQL:

```sql
create table time_records (
  id              bigserial primary key,
  driver_name     text not null,
  truck_id        text not null,
  truck_name      text not null,
  work_date       date not null,
  job_site        text not null,
  start_time      text not null,
  end_time        text not null,
  total_hours     numeric not null,
  driving_hours   numeric not null,
  miles           numeric,
  within_radius   boolean default true,
  checklist_pct   integer default 0,
  remarks         text,
  geotab_prefill  boolean default false,
  submitted_at    timestamptz default now()
);
```

### Step 3 — Geotab Service Account (5 min)
1. Log in to MyGeotab
2. Go to **Administration → Users → Add**
3. Create: `timecard-service@takehara.com` (or similar)
4. Security Clearance: **View Only**
5. Note: server (from your browser URL), database name, username, password

### Step 4 — Deploy Backend to Render (15 min)
1. Go to render.com → Sign up with GitHub
2. Click **New → Web Service**
3. Choose **Upload files** and upload the `backend/` folder, OR connect GitHub repo
4. Settings:
   - Name: `tli-timecard-api`
   - Runtime: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Plan: **Starter ($7/mo)** — avoids cold start delays on a daily-use app
5. Under **Environment Variables**, add all 6:
   ```
   GEOTAB_SERVER    = my.geotab.com
   GEOTAB_DATABASE  = your_db_name
   GEOTAB_USERNAME  = timecard-service@yourdomain.com
   GEOTAB_PASSWORD  = your_password
   SUPABASE_URL     = https://xxxx.supabase.co
   SUPABASE_KEY     = your_service_role_key
   ```
6. Click **Create Web Service** — deploys in ~3 min
7. Copy your Render URL: `https://tli-timecard-api.onrender.com`

### Step 5 — Update Frontend (2 min)
Open `frontend/index.html`, find line ~8:
```javascript
const API_BASE = "https://tli-timecard-api.onrender.com";
```
Replace with your actual Render URL.

### Step 6 — Deploy Frontend
Simplest: **Render Static Site**
1. Render → **New → Static Site**
2. Upload `frontend/` folder
3. No build command needed
4. Free tier is fine for a static HTML file

### Step 7 — Share with Drivers
1. Send drivers the frontend URL
2. **iPhone**: Safari → Share → Add to Home Screen
3. **Android**: Chrome → Menu → Add to Home Screen
4. Print a QR code (qr.io) and stick it in each truck cab

---

## Customizing Driver Names
In `frontend/index.html`, find the driver dropdown and update:
```html
<option>Carlos Mendoza</option>
<option>Jose Rivera</option>
```
Truck list populates automatically from Geotab.

---

## Viewing Submitted Records
Hit your backend URL:
```
/records                                    — all records
/records?start_date=2025-03-01              — filter by start date
/records?start_date=2025-03-01&end_date=2025-03-31  — date range
/records?truck_name=T-101                   — by truck
```
Or view directly in Supabase: **Table Editor → time_records**

---

## Future Apps
This same Supabase project and Render account will host your other TLI apps:
- `tli-estimating-api` → estimates table
- `tli-field-reports-api` → field_reports table
- `tli-payroll-api` → payroll_exports table

One infrastructure setup, all apps share it.

---

## Files
```
tli-timecard/
├── backend/
│   ├── main.py            ← FastAPI app (Geotab + Supabase)
│   ├── requirements.txt   ← Python dependencies
│   ├── render.yaml        ← Render config
│   └── .env.example       ← Env variable template
└── frontend/
    └── index.html         ← Driver-facing mobile web app
```
