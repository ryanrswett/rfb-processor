# RFB File Processor

Web-based tool for processing Regional Food Bank data files. Replaces the LINQPad script (Step 1), and the manual list formatting (Step 2).

## Quick start (local)

```bash
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000.

## What it does

### Step 1: Scanline generation
- Reads house list XLSX or rental list XLSX/CSV
- Auto-detects file type from column headers
- Generates scanlines with Luhn check digits
- Replaces "and" with "&" in PrimaryAddressee for individual records (orgs untouched)
- Runs validation (field lengths, missing data, malformed ZIPs, duplicate IDs)

### Step 2: Portal 1 formatting
- Transforms Step 1 output into the 21-column Final For Entry format
- Splits CityState into separate City and State fields
- Strips ZIP+4 down to 5-digit ZIP
- Organizations: FirstName = "Our Friends at ", LastName = org name
- Individuals: Splits PrimaryAddressee on first space for FirstName/LastName
- Populates Reserve17-20 (KeyCodeListId, sequential row number, ScanLine, Salutation)
- Adds campaign fields (Store, Creative, eventdate) if provided
- Downloads as full list, organizations only, or individuals only

## Deployment with Cloudflare Tunnel

This is the recommended setup. The app runs on a machine on the office network (so it can reach the MailWorks database). Cloudflare Tunnel exposes it to the internet with HTTPS, no firewall changes needed.

### Prerequisites
- A machine on the office network that can reach the MailWorks SQL Server
- A Cloudflare account (free tier works)
- A domain managed by Cloudflare (or use a .cfargotunnel.com subdomain)

### Step 1: Install the app

```bash
# On the office network machine
git clone <repo-url> rfb-processor
cd rfb-processor
pip install -r requirements.txt

# Set the database connection string (for rental list support)
# Windows PowerShell:
$env:MAILWORKS_CONN_STRING = "Server=SERVERNAME;Database=MailWorksInventory;Trusted_Connection=True;"
# Linux/Mac:
export MAILWORKS_CONN_STRING="Server=SERVERNAME;Database=MailWorksInventory;Trusted_Connection=True;"

# Test it works locally
python -m uvicorn main:app --host 0.0.0.0 --port 8000
# Visit http://localhost:8000 to verify
```

### Step 2: Install Cloudflare Tunnel

```bash
# Windows (run as administrator)
winget install cloudflare.cloudflared

# Mac
brew install cloudflared

# Linux
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
```

### Step 3: Authenticate and create tunnel

```bash
# Login to Cloudflare (opens browser)
cloudflared tunnel login

# Create a tunnel
cloudflared tunnel create rfb-processor

# Note the tunnel ID that gets printed (e.g., a1b2c3d4-e5f6-7890-abcd-ef1234567890)
```

### Step 4: Configure the tunnel

Create a config file at `~/.cloudflared/config.yml`:

```yaml
tunnel: <YOUR_TUNNEL_ID>
credentials-file: ~/.cloudflared/<YOUR_TUNNEL_ID>.json

ingress:
  - hostname: rfb.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

### Step 5: Create DNS record

```bash
cloudflared tunnel route dns rfb-processor rfb.yourdomain.com
```

### Step 6: Start everything

```bash
# Terminal 1: Start the app
cd rfb-processor
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2: Start the tunnel
cloudflared tunnel run rfb-processor
```

Employees can now access the app at `https://rfb.yourdomain.com` from anywhere.

### Step 7: Run as a service (so it survives reboots)

**Windows:**
```bash
# Install cloudflared as a Windows service
cloudflared service install

# Create a scheduled task for the Python app
# Or use NSSM (Non-Sucking Service Manager):
nssm install rfb-processor "C:\path\to\python.exe" "-m uvicorn main:app --host 0.0.0.0 --port 8000"
nssm set rfb-processor AppDirectory "C:\path\to\rfb-processor"
nssm start rfb-processor
```

**Linux:**
```bash
# Cloudflared service
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

# App service (create /etc/systemd/system/rfb-processor.service)
[Unit]
Description=RFB File Processor
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/rfb-processor
Environment="MAILWORKS_CONN_STRING=Server=SERVERNAME;Database=MailWorksInventory;Trusted_Connection=True;"
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable rfb-processor
sudo systemctl start rfb-processor
```

## Database connection

Required only for rental lists. House lists work without it.

The app reads `MAILWORKS_CONN_STRING` from the environment. When configured, it calls the `GetNextIntelligentBarCode` stored procedure for sequential acquisition IDs. When not configured, the DB badge in the UI shows yellow "DB offline" and rental list uploads return a clear error.

Also install pyodbc: `pip install pyodbc`

## Adobe Fonts (Proxima Nova)

The UI uses Nunito Sans as a stand-in for Proxima Nova. To use the real font:

1. Go to fonts.adobe.com, add Proxima Nova to a web project
2. Get your Typekit project ID
3. In `static/index.html`, replace the Google Fonts link with:
   ```html
   <script src="https://use.typekit.net/YOUR_PROJECT_ID.js"></script>
   <script>try{Typekit.load({async:true});}catch(e){}</script>
   ```
4. Change `--font` in the CSS from `'Nunito Sans'` to `'proxima-nova'`

## File structure

```
rfb-processor/
  main.py                   # FastAPI app (two-step routes + downloads)
  requirements.txt
  api/
    __init__.py
    processor.py             # Step 1: scanline generation + validation
    portal_formatter.py      # Step 2: Portal 1 formatting
    scanline.py              # Luhn check digit + scanline generation
  static/
    index.html               # Frontend UI
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | DB connection status |
| POST | `/api/step1` | Upload file, generate scanlines |
| POST | `/api/step2` | Format for Portal 1 |
| GET | `/api/download/{job_id}?stage=&segment=` | Download CSV |
| GET | `/` | Frontend UI |
