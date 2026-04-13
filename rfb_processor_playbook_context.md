# RFB File Processor -- Context for AI Playbook Documentation

## What was built

A web app ("RFB File Processor") that automates the processing of Regional Food Bank mailing lists. It replaces a two-person, ~30 minute manual workflow with a browser-based tool that runs in seconds.

GitHub repo: [INSERT REPO URL]

## The original manual process

### Stage 1: Scanline Generation (Scott, ~5 min)
- Receives an Asana task with an attached XLSX file from the Regional Food Bank
- Opens LINQPad on his machine
- Runs a C# script (`RegionalFoodBankProcessor.linq`) that:
  - Reads the XLSX (14 columns, ~13K rows for house lists)
  - Generates a 26-character scanline barcode for each record using Luhn check digits
  - Calls a SQL Server stored procedure (`GetNextIntelligentBarCode`) for sequential IDs (rental lists only)
  - Outputs a 17-column "Provided Back" CSV
- Hands the CSV to Stacy

### Stage 2: Manual Excel Formatting for Portal 1 (Stacy, ~25 min)
- Opens the 17-column CSV in Excel
- Drops unused columns (ConstituentId, OrganizationName, PrimaryAddressee, PrimarySalutation, AddressLine2, County, LastGiftDate)
- Splits CityState into separate City and State columns
- Strips ZIP+4 down to 5-digit ZIP
- Transforms organization names: FirstName = "Our Friends at ", LastName = org name
- Transforms individual names: splits PrimaryAddressee on first space
- Replaces " and " with " & " in addressee fields
- Adds Reserve fields (Reserve17 = KeyCodeListId, Reserve18 = sequential row number, Reserve19 = ScanLine, Reserve20 = PrimarySalutation)
- Adds campaign fields (Store, Creative, eventdate) from the job ticket
- Adds empty placeholder columns (zip4, Phone, ihd)
- Splits file into org and individual segments for Order Importer proofing
- Saves as "Final For Entry" CSV and uploads to Portal 1

## What the app does

### Step 1 (automatic on file upload)
- Reads house list XLSX or rental list XLSX/CSV
- Auto-detects file type from column headers
- Generates scanlines with Luhn check digits (verified byte-for-byte against C# output)
- Replaces " and " with " & " in PrimaryAddressee for individual records only (615 corrections in sample data). Organization names are left untouched to preserve legal/brand names.
- Runs validation: field length checks (50 char limit), missing addresses, malformed ZIPs, duplicate Constituent IDs
- Outputs the 17-column intermediate format

### Step 2 (one click)
- Transforms the Step 1 output into the 21-column Portal 1 format
- All the column restructuring, name transformation, reserve field population
- Campaign fields (Store, Creative, eventdate) are optional, entered via a collapsible section
- Downloads available as: full list, organizations only, or individuals only

### Other features
- DB status indicator (turquoise = connected, yellow = offline)
- Recent files panel with stage indicators (Scanline vs Portal) so previous downloads are always accessible
- Validation runs silently -- employee sees "Ready to download" or "Problem found"

## Tech stack

- **Backend**: Python, FastAPI, pandas, openpyxl
- **Frontend**: Vanilla HTML/CSS/JS (no framework), Nunito Sans font (stand-in for Proxima Nova via Adobe Fonts)
- **Branding**: Mailworks dark navy (#071E30) base, indicia pink (#E81F76) accents, turquoise (#44BDA9) for success states, yellow (#F5C542) for warnings
- **Deployment plan**: Cloudflare Tunnel on an office network machine, giving employees a public HTTPS URL while keeping the app connected to the MailWorks SQL Server

## Database dependency

- The MailWorks SQL Server database is on the local office network
- It has one stored procedure (`MailWorksInventory.dbo.GetNextIntelligentBarCode`) that hands out sequential numbers
- The C# script reads the connection string from a Windows registry key: `HKEY_LOCAL_MACHINE\System\MailWorks\BMConnString`
- House lists do NOT need the database (acquisition ID is all zeros, donor ID comes from Constituent ID in the file)
- Rental lists DO need the database for unique acquisition IDs
- The app needs the connection string set as an environment variable (`MAILWORKS_CONN_STRING`) and must be hosted on a machine that can reach the SQL Server

## What's not done yet

1. **Database connection for rental lists** -- need the connection string from Scott, and the app must run on the office network
2. **Asana integration** -- Store, Creative, and eventdate currently entered manually. These values come from the Asana task. If they're added as custom fields on the task, the app can auto-pull them. Need to confirm with account management.
3. **Adobe Fonts** -- UI uses Nunito Sans as a stand-in. Need the Typekit project ID to swap in Proxima Nova.
4. **Confirmation on Portal 1 upload format** -- Do files go in as orgs and individuals separately? The SOP says to split for proofing but flags this as needing confirmation.
5. **Confirmation on campaign fields** -- Are Store, Creative, and eventdate always required? Are they always the same format? Can they be defaulted?

## Files in the project

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app with two-step API routes and download endpoints |
| `api/processor.py` | Step 1: scanline generation, validation, "and" replacement |
| `api/portal_formatter.py` | Step 2: Portal 1 formatting (column restructuring, name transforms, reserve fields) |
| `api/scanline.py` | Luhn check digit calculation and scanline assembly |
| `static/index.html` | Frontend UI |
| `requirements.txt` | Python dependencies |
| `README.md` | Setup, deployment (including Cloudflare Tunnel), and API docs |

## Sample data used for development and verification

- `RFBB_As_Submitted_for_Dev_Script.xlsx` -- Input house list (13,044 rows, 14 columns)
- `RFBB_Provided_Back.csv` -- Output of the C# LINQ script (17 columns). Used to verify Python scanline output matches byte-for-byte.
- `RFBB_Final_For_Entry.csv` -- Final formatted output (21 columns). Used to reverse-engineer Stacy's manual transformation logic. File metadata was available but file was not on disk in this session.
- `RFBB_LIST_PREP_SOP.md` -- The manual SOP document with process steps and open questions
- `RegionalFoodBankProcessor.linq` -- The C# LINQ script that was reverse-engineered into Python
- `MyExtensions.linq` -- Shared C# utility library (DBHelper class) used by the LINQ script

## Key decisions made

1. **" and " to " & " replacement**: Only applied to individual PrimaryAddressee records. Organization names are left untouched (14 orgs have "and" in their names like "Peace, Love and Cupcakes").
2. **No manual sequence number input**: House lists don't need it. Rental lists pull from the database automatically. The employee never sees or enters a sequence number.
3. **Campaign fields are optional and collapsed**: Store, Creative, eventdate may or may not be required by Portal 1. They're available but don't block processing.
4. **Validation is invisible to the employee**: They see green (ready) or red (problem, contact manager). Detailed validation info is for the account manager/developer to investigate.
5. **Cloudflare Tunnel for deployment**: App stays on the office network (database access), employees get a public HTTPS URL. No firewall changes, no VPN.
6. **Kept the SOP open questions visible**: The SOP flags 9 areas needing clarification. We built around the ones we could verify from data and flagged the rest as "needs confirmation."

## Origin

This was built across two Claude chat sessions in the same project. The first chat reverse-engineered the LINQ script and Stacy's manual process by watching screen recordings and comparing input/output files row by row. The second chat (this one) built the Python backend, designed the UI iteratively with the user, and packaged it for deployment.
