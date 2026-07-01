"""
ICBC appointment slot checker.

Logs into My ICBC, opens the reschedule flow, and checks two locations
for any open slot before a cutoff date. Emails you if one is found.

IMPORTANT: You will very likely need to tweak the selectors marked
with "ADJUST ME" below after a first test run, since the exact page
structure can only be confirmed by actually running this against the
live, logged-in site. See README.md for how to do that in 10 minutes
using `playwright codegen`.
"""

import os
import re
import sys
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Config (all pulled from environment variables / GitHub Secrets, never
# hardcoded, so this file is safe to commit even to a public repo)
# ---------------------------------------------------------------------------

LAST_NAME = os.environ["ICBC_LASTNAME"]
LICENSE_NUMBER = os.environ["ICBC_LICENSE"]
KEYWORD = os.environ["ICBC_KEYWORD"]

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL = os.environ.get("TO_EMAIL", "sahmednabipour@gmail.com")

CUTOFF_DATE = datetime(2026, 7, 28)

LOCATIONS = [
    "Burnaby Claim Centre - Wayburne Drive",
    "Burnaby Driver Licensing",
]

# ADJUST ME: confirm this is the right starting URL for your login
# (likely https://www.icbc.com or https://my.icbc.com, check what
# you land on when you sign in manually).
LOGIN_URL = "https://www.icbc.com/sign-in"


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(subject: str, body: str) -> None:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = TO_EMAIL
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_slots() -> list[str]:
    found = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(LOGIN_URL, wait_until="networkidle")

        # --- LOGIN -----------------------------------------------------
        # ADJUST ME: these field labels must match what's actually on
        # the sign-in form. Use get_by_label where possible, it's the
        # most resilient option (survives CSS/ID changes).
        page.get_by_label(re.compile("last name", re.I)).fill(LAST_NAME)
        page.get_by_label(re.compile("licence number|license number", re.I)).fill(LICENSE_NUMBER)
        page.get_by_label(re.compile("keyword", re.I)).fill(KEYWORD)
        page.get_by_role("button", name=re.compile("sign in|log in", re.I)).click()
        page.wait_for_load_state("networkidle")

        # --- RESCHEDULE --------------------------------------------------
        page.get_by_role("button", name=re.compile("reschedule", re.I)).click()
        page.wait_for_timeout(1000)

        # --- "Are you sure?" confirmation --------------------------------
        try:
            page.get_by_role("button", name=re.compile(r"^yes$", re.I)).click(timeout=5000)
        except PWTimeout:
            pass  # no confirmation dialog appeared, fine
        page.wait_for_load_state("networkidle")

        # --- Check each location ------------------------------------------
        for location in LOCATIONS:
            try:
                page.get_by_text(location, exact=False).first.click()
                page.wait_for_timeout(2000)

                # ADJUST ME: this selector needs to match whatever element
                # wraps each bookable date/time on the calendar/list view.
                # Open dev tools on the real page, right-click an available
                # slot, "Inspect", and copy a stable selector here.
                slot_elements = page.locator("[data-testid='available-date'], .available-slot, .available-date")
                count = slot_elements.count()

                for i in range(count):
                    text = slot_elements.nth(i).inner_text().strip()
                    appt_date = parse_date(text)
                    if appt_date and appt_date <= CUTOFF_DATE:
                        found.append(f"{location}: {text}")

                page.go_back()
                page.wait_for_load_state("networkidle")
            except PWTimeout:
                print(f"Could not load/check location: {location}")
                continue

        browser.close()

    return found


def parse_date(text: str):
    """Try a few common date formats since we don't know the exact one yet."""
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    try:
        slots = check_slots()
    except Exception as e:
        print(f"Error during check: {e}")
        # Don't email on every transient error, just log it so the
        # GitHub Actions run shows failure. Uncomment below if you'd
        # rather be emailed on errors too.
        # send_email("ICBC checker error", str(e))
        sys.exit(1)

    if slots:
        body = "Open ICBC appointment slot(s) found before July 28, 2026:\n\n" + "\n".join(slots)
        send_email("ICBC appointment slot available", body)
        print("Found slot(s), email sent:")
        print("\n".join(slots))
    else:
        print(f"No slots before {CUTOFF_DATE.date()} as of {datetime.now()}.")


if __name__ == "__main__":
    main()
