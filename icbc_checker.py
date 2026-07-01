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

# TEMP TEST VALUE: widened to Dec 8, 2026 to confirm the full pipeline
# (scrape -> parse -> email) actually works, since we know from an earlier
# inspection that a slot exists on that date. Change back to July 28, 2026
# once you've confirmed you got the test email.
CUTOFF_DATE = datetime(2026, 7, 28)

LOCATIONS = [
    "Burnaby claim centre (Wayburne Drive)",
    "Burnaby driver licensing",
]

# This is ICBC's road test / appointment booking system, which is separate
# from the newer "My ICBC" account portal, and is what actually uses
# last name + licence number + keyword to log in.
LOGIN_URL = "https://onlinebusiness.icbc.com/webdeas-ui/login;type=driver"


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
        page.goto(LOGIN_URL, wait_until="load", timeout=60000)

        # --- LOGIN -----------------------------------------------------
        # These selectors target Angular's formcontrolname attribute,
        # which is the most stable way to grab fields in this app since
        # the visible labels aren't wired to real <label> elements.
        page.locator('[formcontrolname="drvrLastName"]').fill(LAST_NAME)
        page.locator('[formcontrolname="licenceNumber"]').fill(LICENSE_NUMBER)
        page.locator('[formcontrolname="keyword"]').fill(KEYWORD)

        # The "I have read and agree" checkbox must be ticked or the
        # Sign in button stays disabled. It's an Angular Material
        # checkbox, click the visible inner container rather than the
        # hidden native input.
        page.locator('.mat-checkbox-inner-container').first.click()
        page.get_by_role("button", name=re.compile("sign in|log in", re.I)).click()
        page.wait_for_load_state("load", timeout=15000)

        # --- RESCHEDULE --------------------------------------------------
        page.get_by_role("button", name=re.compile("reschedule", re.I)).click()
        page.wait_for_timeout(1000)

        # --- "Are you sure?" confirmation --------------------------------
        try:
            page.get_by_role("button", name=re.compile(r"^yes$", re.I)).click(timeout=5000)
        except PWTimeout:
            pass  # no confirmation dialog appeared, fine
        page.wait_for_load_state("load", timeout=15000)

        # --- Check each location ------------------------------------------
        for location in LOCATIONS:
            try:
                found.extend(check_location(page, location))
            except PWTimeout as e:
                print(f"Could not load/check location: {location}")
                print(f"  -> {e}")
                safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", location)
                page.screenshot(path=f"debug_{safe_name}.png", full_page=True)
                continue

        browser.close()

    return found


def check_location(page, location: str) -> list[str]:
    """Search for one location by name and scrape any dates/times shown
    in the "Dates and times" dialog that opens. Every date shown there
    is an open slot, ICBC doesn't show unavailable dates in this view."""

    slots_found = []

    # Switch to the "By office" search tab (harmless if already selected)
    page.get_by_text(re.compile("by office", re.I)).click()
    page.wait_for_timeout(500)

    search_input = page.get_by_placeholder("Start typing...")
    search_input.fill("")
    search_input.fill(location)
    page.wait_for_timeout(1000)

    # An autocomplete suggestion must be clicked, not just typed, or the
    # Search button stays disabled. Target the suggestion text directly.
    page.locator('.mat-option-text', has_text=location).first.click(timeout=8000)

    page.get_by_role("button", name=re.compile(r"^search$", re.I)).click()
    page.wait_for_timeout(1500)

    # Click into the matching result to open the "Dates and times" dialog
    page.get_by_text(location, exact=False).first.click()
    page.wait_for_timeout(1500)

    dialog = page.locator("mat-dialog-container")
    date_titles = dialog.locator(".date-title")
    count = date_titles.count()

    for i in range(count):
        date_text = date_titles.nth(i).inner_text().strip()
        appt_date = parse_date(date_text)
        if appt_date and appt_date <= CUTOFF_DATE:
            slots_found.append(f"{location}: {date_text}")

    # Close the dialog so the next location search starts clean
    try:
        dialog.get_by_text("Cancel", exact=True).click(timeout=3000)
    except PWTimeout:
        pass

    return slots_found


_ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)", re.I)
_WEEKDAY_PREFIX_RE = re.compile(r"^[A-Za-z]+,\s*")


def parse_date(text: str):
    """Parses dates like 'Monday, December 7th, 2026'."""
    text = text.strip()
    text = _WEEKDAY_PREFIX_RE.sub("", text)      # drop "Monday, "
    text = _ORDINAL_RE.sub(r"\1", text)           # "7th" -> "7"
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
