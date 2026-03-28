# Automation Glow — Onboarding Service Deployment Guide

## What This Does

A single webhook endpoint (`POST /onboard`) that runs the full onboarding sequence in under 60 seconds:

1. Creates a Notion client card in your Client Portfolio database
2. Creates a Google Drive folder (`[Clinic Name] — Assets`) with 3 sub-folders
3. Updates the Notion card with the Drive folder link
4. Creates a GHL sub-account via API
5. Loads your standard GHL snapshot into the new account
6. Sends a branded welcome email from milan@glowmarketing.se

---

## Step 1 — Get Your Credentials

You need 3 credentials before deploying:

### A. Notion Integration Token
1. Go to https://www.notion.so/my-integrations
2. Click **New integration** → name it "Glow Onboarding" → Submit
3. Copy the **Internal Integration Token** (starts with `secret_`)
4. Go to your Client Portfolio database in Notion → click `...` → **Connections** → add "Glow Onboarding"

### B. Google Service Account (for Drive)
1. Go to https://console.cloud.google.com
2. Create a new project (or use existing)
3. Enable the **Google Drive API**
4. Go to **IAM & Admin → Service Accounts** → Create service account
5. Download the JSON key file
6. Share your Google Drive parent folder (`1M_8q_hJET4o4_jmiOCre3tR0WL6lokmr`) with the service account email (give it Editor access)
7. The entire JSON file content goes into the `GOOGLE_CREDENTIALS_JSON` environment variable (as a single-line string)

### C. Gmail App Password (for sending email)
1. Go to https://myaccount.google.com/apppasswords (must have 2FA enabled)
2. Select app: **Mail** → device: **Other** → name it "Glow Onboarding"
3. Copy the 16-character app password (format: `xxxx xxxx xxxx xxxx`)

---

## Step 2 — Deploy to Railway (Recommended, ~5 minutes)

Railway is the easiest way to host this. It costs ~$5/month.

1. Go to https://railway.app and sign up
2. Click **New Project → Deploy from GitHub repo**
   - OR click **New Project → Deploy from local** and upload the project folder
3. Set the following **Environment Variables** in Railway:

| Variable | Value |
| :--- | :--- |
| `NOTION_TOKEN` | Your Notion integration token (`secret_...`) |
| `GOOGLE_CREDENTIALS_JSON` | The full service account JSON (paste as one line) |
| `GMAIL_APP_PASSWORD` | Your Gmail app password |
| `CALENDLY_LINK` | Your booking calendar URL |
| `META_GUIDE_LINK` | Your Meta BM video guide URL |

4. Railway will give you a public URL like `https://glow-onboarding.up.railway.app`
5. Your webhook endpoint is: `https://glow-onboarding.up.railway.app/onboard`

---

## Step 3 — Connect Your Onboarding Form

Point your form's webhook to: `POST https://your-railway-url.up.railway.app/onboard`

The JSON payload must include these field names:

| Field | Required | Description |
| :--- | :--- | :--- |
| `clinic_name` | ✅ | Clinic / business name |
| `email` | ✅ | Client email address |
| `contact_name` | | Person's name |
| `phone` | | Phone / WhatsApp |
| `website_url` | | Website URL |
| `lead_treatment` | | Lead offer/treatment |
| `lead_treatment_price` | | Price of lead treatment |

---

## Step 4 — Test It

Send a test request:

```bash
curl -X POST https://your-railway-url.up.railway.app/onboard \
  -H "Content-Type: application/json" \
  -d '{
    "clinic_name": "Test Clinic",
    "contact_name": "Test Person",
    "email": "your@email.com",
    "phone": "+46701234567",
    "lead_treatment": "Botox",
    "lead_treatment_price": "2500 SEK"
  }'
```

You should receive `{"status": "accepted"}` immediately, and within 30 seconds:
- A new Notion card appears in your Client Portfolio
- A new Google Drive folder appears in your shared folder
- A new GHL sub-account is created with the snapshot loaded
- A welcome email arrives in the test inbox

---

## Health Check

Visit `https://your-railway-url.up.railway.app/` — should return `{"status": "ok"}`.
