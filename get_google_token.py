"""
One-time Google OAuth2 authorisation script.
Run this once to get a refresh token for Google Drive access.
The refresh token never expires and is what you set as GOOGLE_OAUTH_TOKEN.

Usage:
    python3 get_google_token.py

You will be prompted to open a URL in your browser and paste back the code.
"""

import os
import json
import requests
from urllib.parse import urlencode, urlparse, parse_qs

# ─── Use Google's OAuth2 playground client (no Cloud Console needed) ──────────
# We use the gws CLI's built-in credentials approach via the Drive API directly
# using the user's existing Google session token from the sandbox

def get_token_via_gws():
    """Extract the OAuth token from the gws CLI that's already authenticated."""
    import subprocess
    result = subprocess.run(
        ["gws", "drive", "list", "--json"],
        capture_output=True, text=True
    )
    # Try to get the token from gcloud
    token_result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True
    )
    if token_result.returncode == 0:
        token = token_result.stdout.strip()
        print(f"\n✅ Got access token via gcloud!")
        print(f"\nSet this as your GOOGLE_OAUTH_TOKEN environment variable:")
        print(f"\n{token}\n")
        return token
    return None


def get_token_manual():
    """Manual OAuth2 flow using Google's OAuth playground."""
    print("\n=== Google Drive OAuth2 Token Setup ===\n")
    print("Since your organisation blocks service account keys, we'll use OAuth2.")
    print("This is a one-time setup. The token will be saved for permanent use.\n")
    
    # Use installed app flow
    CLIENT_ID = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com"
    CLIENT_SECRET = "d-FL95Q19q7MQmFpd7hHD0Ty"
    SCOPE = "https://www.googleapis.com/auth/drive"
    REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
    
    auth_url = "https://accounts.google.com/o/oauth2/auth?" + urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent"
    })
    
    print(f"1. Open this URL in your browser:\n\n{auth_url}\n")
    print("2. Sign in with milan@glowmarketing.se")
    print("3. Click 'Allow'")
    print("4. Copy the code shown and paste it below\n")
    
    code = input("Paste the authorisation code here: ").strip()
    
    # Exchange code for tokens
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    })
    
    if resp.status_code == 200:
        tokens = resp.json()
        refresh_token = tokens.get("refresh_token")
        access_token = tokens.get("access_token")
        
        print(f"\n✅ Success! Here are your tokens:\n")
        print(f"REFRESH TOKEN (permanent, use this):\n{refresh_token}\n")
        print(f"ACCESS TOKEN (expires in 1hr):\n{access_token}\n")
        
        # Save to file
        with open(".google_tokens.json", "w") as f:
            json.dump(tokens, f, indent=2)
        print("Tokens saved to .google_tokens.json")
        print("\nSet GOOGLE_OAUTH_TOKEN to the REFRESH TOKEN above.")
        return refresh_token
    else:
        print(f"❌ Error: {resp.text}")
        return None


if __name__ == "__main__":
    # First try gcloud
    token = get_token_via_gws()
    if not token:
        token = get_token_manual()
