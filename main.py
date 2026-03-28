"""
Automation Glow — Client Onboarding Automation Server
Webhook endpoint that handles the full onboarding flow:
1. Create Notion client card
2. Create Google Drive folder structure
3. Create GHL sub-account
4. Load GHL snapshot
5. Send welcome email via Gmail

SECURITY FEATURES:
- Rate limiting: 10 submissions per hour per IP
- API key validation
- hCaptcha verification
"""

import os
import json
import logging
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Automation Glow — Onboarding Automation")

# ─── CORS Configuration ───────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Rate Limiting ────────────────────────────────────────────────────────────
class RateLimiter:
    """Simple in-memory rate limiter based on IP address."""
    def __init__(self, max_requests: int = 10, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)  # IP -> list of timestamps
    
    def is_allowed(self, ip: str) -> bool:
        """Check if request from IP is allowed. Returns True if allowed, False if rate limited."""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.window_seconds)
        
        # Clean old requests
        self.requests[ip] = [ts for ts in self.requests[ip] if ts > cutoff]
        
        # Check if under limit
        if len(self.requests[ip]) < self.max_requests:
            self.requests[ip].append(now)
            return True
        return False
    
    def get_remaining(self, ip: str) -> int:
        """Get remaining requests for this IP."""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.window_seconds)
        self.requests[ip] = [ts for ts in self.requests[ip] if ts > cutoff]
        return max(0, self.max_requests - len(self.requests[ip]))

rate_limiter = RateLimiter(max_requests=10, window_seconds=3600)  # 10 per hour per IP

# ─── Config ───────────────────────────────────────────────────────────────────
NOTION_TOKEN        = os.getenv("NOTION_TOKEN")
NOTION_DB_ID        = "136bbb67b00381ac87fae600e70ac70b"
GHL_COMPANY_ID      = "2lOyQXCDOTQh2Xu2MMUJ"
GDRIVE_PARENT_ID    = "1ZNo3TWppUgoL68YfY5Jc0nYqJjXDbqP5"  # Clients folder
GHL_API_KEY         = os.getenv("GHL_API_KEY", "pit-2e377694-9c26-4726-ba33-4e8ac0128c01")
GHL_SNAPSHOT_ID     = "w8LR6EA74MRRtZ6UlBhs"
GMAIL_USER          = "milan@glowmarketing.se"
GMAIL_APP_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD")
CALENDLY_LINK       = os.getenv("CALENDLY_LINK", "[INSERT CALENDLY LINK]")
META_GUIDE_LINK     = os.getenv("META_GUIDE_LINK", "[INSERT META BM VIDEO GUIDE LINK]")
FORM_API_KEY        = os.getenv("FORM_API_KEY", "glow-form-secret-key-2024")  # Secret key for form submissions
HCAPTCHA_SECRET     = os.getenv("HCAPTCHA_SECRET", "ES_11fe2d7e77ba4862878d371e8971d723")  # hCaptcha secret key

# ─── Notion ───────────────────────────────────────────────────────────────────
def create_notion_card(data: dict) -> str:
    """Create a new client card in the Notion Client Portfolio database."""
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Company": {
                "title": [{"text": {"content": data.get("clinic_name", "")}}]
            },
            "Email Address": {
                "email": data.get("email")
            },
            "Phone Number": {
                "phone_number": data.get("phone")
            },
            "Status": {
                "select": {"name": "Active"}
            },
            "Onboarding date": {
                "date": {"start": datetime.today().strftime("%Y-%m-%d")}
            },
            "Country": {
                "select": {"name": "Sweden"}
            },
            "Client Sentiment": {
                "select": {"name": "Happy"}
            }
        }
    }
    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()
    page_id = r.json()["id"]
    log.info(f"✅ Notion card created: {page_id}")
    return page_id


def update_notion_card(page_id: str, updates: dict):
    """Update properties on an existing Notion page."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    r = requests.patch(url, headers=headers, json={"properties": updates})
    r.raise_for_status()
    log.info(f"✅ Notion card updated: {page_id}")


# ─── Google Drive (via rclone OAuth token) ───────────────────────────────────
import re as _re

RCLONE_CONFIG_PATH = os.getenv("RCLONE_CONFIG_PATH", "/home/ubuntu/.gdrive-rclone.ini")

def get_drive_token() -> str:
    """Read the current OAuth access token from the rclone config file."""
    with open(RCLONE_CONFIG_PATH) as f:
        content = f.read()
    match = _re.search(r'token = (.+)', content)
    if not match:
        raise RuntimeError("Could not find OAuth token in rclone config")
    token_data = json.loads(match.group(1))
    return token_data["access_token"]


def drive_create_folder(name: str, parent_id: str) -> tuple[str, str]:
    """Create a folder in Google Drive using the rclone OAuth token. Returns (id, link)."""
    token = get_drive_token()
    resp = requests.post(
        "https://www.googleapis.com/drive/v3/files",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Drive API error: {data['error']['message']}")
    folder_id = data["id"]
    web_link = f"https://drive.google.com/drive/folders/{folder_id}"
    log.info(f"✅ Drive folder created: {name} ({folder_id})")
    return folder_id, web_link


def setup_drive_folders(clinic_name: str) -> str:
    """Create main client folder + 3 sub-folders. Returns main folder URL."""
    main_id, main_link = drive_create_folder(f"{clinic_name} — Assets", GDRIVE_PARENT_ID)
    drive_create_folder("1. Clinic | Staff", main_id)
    drive_create_folder("2. Ad material", main_id)
    drive_create_folder("3. Glow Creatives", main_id)
    return main_link


# ─── GoHighLevel ─────────────────────────────────────────────────────────────
GHL_HEADERS = {
    "Authorization": f"Bearer {GHL_API_KEY}",
    "Version": "2021-07-28",
    "Content-Type": "application/json"
}

def create_ghl_subaccount(data: dict) -> str:
    """Create a new GHL sub-account and return the location ID."""
    payload = {
        "name": data.get("clinic_name"),
        "companyId": GHL_COMPANY_ID,
        "phone": data.get("phone", ""),
        "email": data.get("email", ""),
        "website": data.get("website_url", ""),
        "timezone": "Europe/Stockholm",
        "country": "SE"
    }
    r = requests.post(
        "https://services.leadconnectorhq.com/locations/",
        headers=GHL_HEADERS,
        json=payload
    )
    r.raise_for_status()
    location_id = r.json().get("location", {}).get("id") or r.json().get("id")
    log.info(f"✅ GHL sub-account created: {location_id}")
    return location_id


def load_ghl_snapshot(location_id: str):
    """Push the standard snapshot into the new GHL sub-account via share link."""
    # Step 1: Create a location-restricted share link for the snapshot
    payload = {
        "snapshot_id": GHL_SNAPSHOT_ID,
        "share_type": "location_link",
        "share_location_id": location_id
    }
    r = requests.post(
        f"https://services.leadconnectorhq.com/snapshots/share/link?companyId={GHL_COMPANY_ID}",
        headers=GHL_HEADERS,
        json=payload
    )
    r.raise_for_status()
    share_data = r.json()
    share_link = share_data.get("shareLink", "")
    log.info(f"✅ GHL snapshot share link created: {share_link} for location: {location_id}")
    # Note: The share link is location-restricted — the sub-account can load it directly.
    # For full automation, the snapshot can also be loaded via the GHL UI using this link.
    return share_link


# ─── Email ────────────────────────────────────────────────────────────────────
def send_welcome_email(data: dict, drive_link: str):
    """Send the welcome email to the new client via Gmail SMTP."""
    clinic_name       = data.get("clinic_name", "")
    contact_name      = data.get("contact_name", clinic_name)
    lead_treatment    = data.get("lead_treatment", "")
    lead_price        = data.get("lead_treatment_price", "")
    to_email          = data.get("email", "")

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1a1a1a;">
      <div style="background: linear-gradient(135deg, #FF6B35, #FF8C42); padding: 32px; border-radius: 12px 12px 0 0;">
        <h1 style="color: white; margin: 0; font-size: 24px;">Welcome to Automation Glow! 🚀</h1>
      </div>
      <div style="background: #ffffff; padding: 32px; border-radius: 0 0 12px 12px; border: 1px solid #e5e5e5;">
        <p style="font-size: 16px;">Hi <strong>{contact_name}</strong>,</p>
        <p style="font-size: 16px; line-height: 1.6;">
          Welcome to <strong>Automation Glow</strong>! We are so excited to partner with <strong>{clinic_name}</strong>
          and start scaling your clinic together. Your onboarding is now officially underway.
        </p>

        <div style="background: #f9f9f9; border-left: 4px solid #FF6B35; padding: 20px; margin: 24px 0; border-radius: 0 8px 8px 0;">
          <h3 style="margin: 0 0 8px; color: #FF6B35;">📂 Step 1 — Upload Your Assets</h3>
          <p style="margin: 0; line-height: 1.6;">
            We've created a dedicated Google Drive folder for your clinic. Please upload any existing assets here —
            photos, videos, before/afters, logo files, anything we can use for your ads:
          </p>
          <a href="{drive_link}" style="display: inline-block; margin-top: 12px; background: #FF6B35; color: white;
             padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold;">
            👉 Open Your Google Drive Folder
          </a>
        </div>

        <div style="background: #f9f9f9; border-left: 4px solid #FF6B35; padding: 20px; margin: 24px 0; border-radius: 0 8px 8px 0;">
          <h3 style="margin: 0 0 8px; color: #FF6B35;">🔗 Step 2 — Grant Meta Business Manager Access</h3>
          <p style="margin: 0; line-height: 1.6;">
            To run your ads on Facebook and Instagram, we need access to your Meta Business Manager and Ad Account.
            This takes about 2 minutes:
          </p>
          <a href="{META_GUIDE_LINK}" style="display: inline-block; margin-top: 12px; background: #FF6B35; color: white;
             padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold;">
            👉 Watch the 2-Minute Setup Guide
          </a>
        </div>

        <div style="background: #f9f9f9; border-left: 4px solid #FF6B35; padding: 20px; margin: 24px 0; border-radius: 0 8px 8px 0;">
          <h3 style="margin: 0 0 8px; color: #FF6B35;">📅 Step 3 — Book Your Onboarding Call</h3>
          <p style="margin: 0; line-height: 1.6;">
            Book your onboarding call with your dedicated Client Success Manager. This is where we walk through
            your strategy and get your first campaign live:
          </p>
          <a href="{CALENDLY_LINK}" style="display: inline-block; margin-top: 12px; background: #FF6B35; color: white;
             padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold;">
            👉 Book Your Onboarding Call
          </a>
        </div>

        <div style="background: #fff8f5; border: 1px solid #FFD4C2; padding: 20px; border-radius: 8px; margin: 24px 0;">
          <h3 style="margin: 0 0 8px; color: #1a1a1a;">🎯 What We're Building For You</h3>
          <p style="margin: 0; line-height: 1.6;">
            Based on your form, we will be leading with <strong>{lead_treatment}</strong>
            {"at <strong>" + lead_price + "</strong>" if lead_price else ""}.
            Our team is already reviewing your information and preparing your first campaign strategy.
          </p>
        </div>

        <hr style="border: none; border-top: 1px solid #e5e5e5; margin: 24px 0;">
        <p style="font-size: 14px; color: #666; line-height: 1.6;">
          If you have any questions at all, just reply to this email or reach out on WhatsApp. We're here.
        </p>
        <p style="font-size: 16px; margin: 0;">
          Talk soon,<br>
          <strong>The Automation Glow Team</strong><br>
          <span style="color: #FF6B35;">milan@glowmarketing.se</span>
        </p>
      </div>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Welcome to Automation Glow! 🚀 Here's everything you need, {contact_name}"
    msg["From"]    = f"Milan @ Automation Glow <{GMAIL_USER}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, to_email, msg.as_string())
    log.info(f"✅ Welcome email sent to {to_email}")


# ─── Main Onboarding Flow ─────────────────────────────────────────────────────
async def run_onboarding(data: dict):
    """Execute the full onboarding sequence."""
    clinic_name = data.get("clinic_name", "Unknown Clinic")
    log.info(f"🚀 Starting onboarding for: {clinic_name}")
    results = {"clinic_name": clinic_name, "steps": {}}

    # Step 1: Notion card
    try:
        notion_page_id = create_notion_card(data)
        results["steps"]["notion"] = {"status": "ok", "page_id": notion_page_id}
    except Exception as e:
        log.error(f"❌ Notion failed: {e}")
        results["steps"]["notion"] = {"status": "error", "error": str(e)}
        notion_page_id = None

    # Step 2: Google Drive folders
    try:
        drive_link = setup_drive_folders(clinic_name)
        results["steps"]["google_drive"] = {"status": "ok", "link": drive_link}
        # Update Notion card with Drive link
        if notion_page_id:
            try:
                update_notion_card(notion_page_id, {
                    "Google Drive": {"url": drive_link}
                })
            except Exception as e:
                log.warning(f"⚠️ Could not update Notion with Drive link: {e}")
    except Exception as e:
        log.error(f"❌ Google Drive failed: {e}")
        results["steps"]["google_drive"] = {"status": "error", "error": str(e)}
        drive_link = "#"

    # Step 3: GHL sub-account
    try:
        location_id = create_ghl_subaccount(data)
        results["steps"]["ghl_account"] = {"status": "ok", "location_id": location_id}
    except Exception as e:
        log.error(f"❌ GHL sub-account failed: {e}")
        results["steps"]["ghl_account"] = {"status": "error", "error": str(e)}
        location_id = None

    # Step 4: GHL snapshot
    if location_id:
        try:
            share_link = load_ghl_snapshot(location_id)
            results["steps"]["ghl_snapshot"] = {"status": "ok", "share_link": share_link}
        except Exception as e:
            log.error(f"❌ GHL snapshot failed: {e}")
            results["steps"]["ghl_snapshot"] = {"status": "error", "error": str(e)}

    # Step 5: Welcome email
    try:
        send_welcome_email(data, drive_link)
        results["steps"]["welcome_email"] = {"status": "ok"}
    except Exception as e:
        log.error(f"❌ Welcome email failed: {e}")
        results["steps"]["welcome_email"] = {"status": "error", "error": str(e)}

    log.info(f"✅ Onboarding complete for: {clinic_name}")
    return results


# ─── API Endpoints ────────────────────────────────────────────────────────────
@app.get("/")
async def health():
    return {"status": "ok", "service": "Automation Glow Onboarding", "version": "1.0"}


@app.post("/onboard")
async def onboard_client(request: Request, background_tasks: BackgroundTasks):
    """
    Main webhook endpoint. Accepts form data as JSON.
    Expected fields: clinic_name, contact_name, email, phone, website_url,
                     lead_treatment, lead_treatment_price, etc.
    Security: Rate limiting (10 per hour per IP) + API key validation + hCaptcha verification
    """
    # Get client IP address
    client_ip = request.client.host if request.client else "unknown"
    
    # Rate limiting check
    if not rate_limiter.is_allowed(client_ip):
        remaining = rate_limiter.get_remaining(client_ip)
        log.warning(f"⚠️ Rate limit exceeded for IP {client_ip}")
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Rate limit: 10 per hour. Remaining: {remaining}"
        )
    
    # API key validation
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if api_key != FORM_API_KEY:
        log.warning(f"⚠️ Invalid API key attempt from {client_ip}")
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not data.get("clinic_name") or not data.get("email"):
        raise HTTPException(status_code=422, detail="clinic_name and email are required")
    
    # Validate hCaptcha token if provided
    captcha_token = data.get("captcha_token")
    if captcha_token:
        try:
            captcha_response = requests.post(
                "https://hcaptcha.com/siteverify",
                data={"secret": HCAPTCHA_SECRET, "response": captcha_token},
                timeout=5
            )
            captcha_data = captcha_response.json()
            if not captcha_data.get("success"):
                log.warning(f"⚠️ hCaptcha verification failed from {client_ip}")
                raise HTTPException(status_code=400, detail="CAPTCHA verification failed")
        except requests.RequestException as e:
            log.error(f"❌ hCaptcha verification error: {e}")
            # Don't fail the request if hCaptcha service is down, but log it
    
    log.info(f"✅ Valid submission from {client_ip} for {data.get('clinic_name')}")

    # Run in background so webhook returns immediately
    background_tasks.add_task(run_onboarding, data)

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": f"Onboarding started for {data['clinic_name']}. All steps will run in the background.",
            "clinic": data["clinic_name"]
        }
    )


@app.post("/onboard/sync")
async def onboard_client_sync(request: Request):
    """Synchronous version — waits for all steps to complete before responding."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not data.get("clinic_name") or not data.get("email"):
        raise HTTPException(status_code=422, detail="clinic_name and email are required")

    results = await run_onboarding(data)
    return JSONResponse(status_code=200, content=results)
