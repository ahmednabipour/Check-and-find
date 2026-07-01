# ICBC appointment slot checker

Checks two ICBC locations for an open reschedule slot before July 28, 2026,
and emails you at sahmednabipour@gmail.com if one shows up. Runs for free
on GitHub Actions, no server required.

## Why you'll need to do a bit of setup yourself

I can't log into your ICBC account from here, so I can't confirm the exact
field names and button text on the live site. The script (`icbc_checker.py`)
is written to be as resilient as possible (it matches buttons/fields by
their visible label or text, not by fragile internal IDs), but there are
three spots marked `ADJUST ME` that you should double check once, the
first time you run it. This takes about 10 minutes. Steps below.

## 1. Create the GitHub repo (free)

1. Go to github.com, sign up if you don't have an account (free).
2. Create a new repository. Make it **private** (Settings, your data
   stays out of public view either way since credentials are never in
   the code, but private is the safer default).
3. Upload these files, keeping the folder structure:
   - `icbc_checker.py`
   - `requirements.txt`
   - `.github/workflows/check-icbc.yml`

## 2. Add your credentials as GitHub Secrets

Go to your repo, Settings, Secrets and variables, Actions, "New repository
secret". Add each of these:

| Secret name | Value |
|---|---|
| `ICBC_LASTNAME` | Nabipour |
| `ICBC_LICENSE` | 30784802 |
| `ICBC_KEYWORD` | ghofrani |
| `GMAIL_USER` | your gmail address (the one sending the alert) |
| `GMAIL_APP_PASSWORD` | see step 3 below |

Secrets are encrypted and never shown in logs, this is the standard
free, secure way to handle credentials for a script like this.

## 3. Get a Gmail App Password (free, takes 2 minutes)

You can't use your normal Gmail password for this, Google requires an
"app password" for scripts:

1. Turn on 2-Step Verification on your Google account if not already on:
   myaccount.google.com/security
2. Go to myaccount.google.com/apppasswords
3. Create a new app password (name it "ICBC checker"), copy the 16-character
   code it gives you.
4. Use that code as the `GMAIL_APP_PASSWORD` secret, not your real password.

## 4. Confirm the three `ADJUST ME` spots in icbc_checker.py

The fastest way to get the exact selectors right:

1. Install Playwright locally (one time): `pip install playwright && playwright install chromium`
2. Run: `playwright codegen https://www.icbc.com` (or whatever URL you land
   on when you sign in manually)
3. A browser window opens with a recorder. Manually click through: sign in,
   click Reschedule, click Yes on the confirmation, click into one of the
   two locations. The codegen window shows you the real selectors for each
   step as you click.
4. Copy those real selectors into `icbc_checker.py` in place of the
   `ADJUST ME` sections, particularly:
   - The `LOGIN_URL` at the top
   - The field labels in the login section
   - The selector for "available date" elements in the calendar/list view

## 5. Test it manually before trusting the schedule

In your repo, go to the "Actions" tab, select "Check ICBC appointment slots",
click "Run workflow" to trigger it manually. Check the run logs to confirm
it logs in and reaches the calendar correctly. If something fails, the logs
will tell you which step.

## 6. Let it run

Once it's working, it'll run automatically every hour (set in the workflow
file, change the `cron` line if you want a different frequency) and will
email you the moment a slot shows up at either location before July 28.

## A couple of things worth knowing

- ICBC's terms of use generally expect bookings to go through their own
  interface rather than third-party automation, and some sites explicitly
  warn against third-party booking tools. This script only checks your own
  account for openings and emails you, it doesn't book anything automatically
  or act on anyone else's behalf, but it's worth being aware of in case ICBC's
  terms matter to you. I'm not a lawyer, so if you want certainty here it's
  worth a quick read of ICBC's terms and conditions yourself.
- Keep the check interval reasonable (hourly is plenty). Hammering the site
  every minute is more likely to get flagged or rate-limited, and won't
  meaningfully improve your odds of catching a same-day cancellation.
- If GitHub Actions ever stops working for you or you outgrow the free tier,
  the same script runs fine on a free Render.com or PythonAnywhere cron job,
  the only thing that changes is where the schedule lives.
