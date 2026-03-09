"""
TLI Driver Time Record — Backend API
- Pulls trip data from Geotab MyGeotab API
- Stores submitted time records in Supabase (PostgreSQL)
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import httpx
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

app = FastAPI(title="TLI Timecard API", version="1.0.0")

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to your frontend URL after go-live
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── CONFIG ────────────────────────────────────────────────────────────────────
GEOTAB_SERVER    = os.environ.get("GEOTAB_SERVER",    "my.geotab.com")
GEOTAB_DATABASE  = os.environ.get("GEOTAB_DATABASE",  "")
GEOTAB_USERNAME  = os.environ.get("GEOTAB_USERNAME",  "")
GEOTAB_PASSWORD  = os.environ.get("GEOTAB_PASSWORD",  "")

SUPABASE_URL     = os.environ.get("SUPABASE_URL",     "")   # https://xxxx.supabase.co
SUPABASE_KEY     = os.environ.get("SUPABASE_KEY",     "")   # service_role key

TZ = ZoneInfo("America/Los_Angeles")

# ── SUPABASE HELPERS ──────────────────────────────────────────────────────────

def sb_headers() -> dict:
    return {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=representation",
    }


async def sb_insert(table: str, data: dict) -> dict:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, headers=sb_headers(), json=data)
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=502,
                detail=f"Supabase insert failed: {r.text}")
        rows = r.json()
        return rows[0] if isinstance(rows, list) and rows else data


async def sb_select(table: str) -> list:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {"select": "*", "order": "submitted_at.desc"}
    headers = {**sb_headers(), "Prefer": ""}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=headers, params=params)
        if r.status_code != 200:
            raise HTTPException(status_code=502,
                detail=f"Supabase query failed: {r.text}")
        return r.json()


# ── GEOTAB AUTH ───────────────────────────────────────────────────────────────
_session_cache: dict = {}


async def geotab_authenticate() -> dict:
    global _session_cache
    if _session_cache.get("sessionId"):
        return _session_cache

    payload = {
        "method": "Authenticate",
        "params": {
            "database": GEOTAB_DATABASE,
            "userName": GEOTAB_USERNAME,
            "password": GEOTAB_PASSWORD,
        }
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://{GEOTAB_SERVER}/apiv1", json=payload)
        r.raise_for_status()
        result = r.json().get("result", {})

    creds = result.get("credentials", {})
    path  = result.get("path", GEOTAB_SERVER)
    _session_cache = {
        "sessionId": creds.get("sessionId"),
        "database":  creds.get("database"),
        "userName":  creds.get("userName"),
        "server":    path if path != "ThisServer" else GEOTAB_SERVER,
    }
    return _session_cache


async def geotab_call(method: str, params: dict) -> dict:
    creds = await geotab_authenticate()
    payload = {
        "method": method,
        "params": {
            **params,
            "credentials": {
                "sessionId": creds["sessionId"],
                "database":  creds["database"],
                "userName":  creds["userName"],
            }
        }
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"https://{creds['server']}/apiv1", json=payload)
        r.raise_for_status()
        body = r.json()

    if "error" in body:
        code = body["error"].get("errors", [{}])[0].get("name", "")
        if code == "InvalidUserException":
            _session_cache.clear()
            return await geotab_call(method, params)
        raise HTTPException(status_code=502, detail=body["error"])

    return body.get("result", {})


# ── HELPERS ───────────────────────────────────────────────────────────────────

def to_pacific(dt_str: str) -> datetime:
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    return dt.astimezone(TZ)

def fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")

def km_to_miles(km: float) -> float:
    return round(km * 0.621371, 1)


# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "TLI Timecard API"}


@app.get("/devices")
async def get_devices():
    result = await geotab_call("Get", {
        "typeName": "Device",
        "search": {"activeFrom": "1986-01-01T00:00:00.000Z"},
    })
    devices = [
        {"id": d["id"], "name": d.get("name", "Unknown"),
         "licensePlate": d.get("licensePlate", "")}
        for d in result
        if d.get("name") and not d.get("isArchived", False)
    ]
    devices.sort(key=lambda x: x["name"])
    return {"devices": devices}


@app.get("/trip-data")
async def get_trip_data(
    device_id: str = Query(...),
    trip_date: str = Query(..., description="YYYY-MM-DD"),
):
    local_start = datetime.strptime(trip_date, "%Y-%m-%d").replace(
        hour=0, minute=0, second=0, tzinfo=TZ)
    local_end = local_start + timedelta(days=1)

    result = await geotab_call("Get", {
        "typeName": "Trip",
        "search": {
            "deviceSearch": {"id": device_id},
            "fromDate": local_start.astimezone().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "toDate":   local_end.astimezone().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
    })

    if not result:
        return {"found": False, "message": "No trips found for this truck on this date."}

    starts, stops, total_km, total_secs = [], [], 0.0, 0
    for trip in result:
        if trip.get("start"): starts.append(to_pacific(trip["start"]))
        if trip.get("stop"):  stops.append(to_pacific(trip["stop"]))
        total_km   += trip.get("distance", 0) or 0
        total_secs += trip.get("drivingDuration", 0) or 0

    return {
        "found":         True,
        "first_start":   fmt_time(min(starts)) if starts else None,
        "last_stop":     fmt_time(max(stops))  if stops  else None,
        "total_miles":   km_to_miles(total_km),
        "driving_hours": round(total_secs / 3600, 1),
        "trip_count":    len(result),
        "source":        "geotab",
    }


# ── SUBMIT ────────────────────────────────────────────────────────────────────

class TimeRecord(BaseModel):
    driver_name:    str
    truck_id:       str
    truck_name:     str
    work_date:      str
    job_site:       str
    start_time:     str
    end_time:       str
    total_hours:    float
    driving_hours:  float
    miles:          Optional[float] = None
    within_radius:  bool = True
    checklist_pct:  int  = 0
    remarks:        Optional[str] = None
    geotab_prefill: bool = False


@app.post("/submit")
async def submit_record(record: TimeRecord):
    data = record.dict()
    data["submitted_at"] = datetime.now(TZ).isoformat()
    row = await sb_insert("time_records", data)
    return {"success": True, "id": row.get("id")}


@app.get("/records")
async def get_records(
    start_date: Optional[str] = None,
    end_date:   Optional[str] = None,
    truck_name: Optional[str] = None,
):
    rows = await sb_select("time_records")
    if start_date:
        rows = [r for r in rows if r.get("work_date", "") >= start_date]
    if end_date:
        rows = [r for r in rows if r.get("work_date", "") <= end_date]
    if truck_name:
        rows = [r for r in rows if truck_name.lower() in r.get("truck_name", "").lower()]
    return {"records": rows, "count": len(rows)}
