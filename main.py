"""FastAPI backend for RFB File Processor.

Two-step flow:
  Step 1: Upload file -> scanline generation + validation
  Step 2: Portal 1 formatting with optional campaign fields
"""

import io
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from api.processor import (
    process_file, output_to_csv_bytes, db_available, OUTPUT_COLUMNS,
)
from api.portal_formatter import (
    format_for_portal, portal_to_csv_bytes, PORTAL_COLUMNS,
)

app = FastAPI(title="RFB File Processor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store keyed by job_id so multiple files can coexist
_jobs = {}


@app.get("/api/status")
async def status():
    """Check system status."""
    return {"db_connected": db_available(), "status": "ok"}


@app.post("/api/step1")
async def step1_upload(
    file: UploadFile = File(...),
):
    """Step 1: Upload file, generate scanlines, validate."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    contents = await file.read()

    try:
        result = process_file(
            filename=file.filename,
            file_bytes=contents,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Processing failed: {str(e)}")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "filename": file.filename,
        "step1_df": result["output_df"],
        "step2_df": None,
        "stage": "scanline",
    }

    return {
        "job_id": job_id,
        "file_type": result["file_type"],
        "record_count": result["record_count"],
        "org_count": result["org_count"],
        "individual_count": result["individual_count"],
        "key_code_list_id": result["key_code_list_id"],
        "warnings": result["warnings"],
        "and_replaced_count": result["and_replaced_count"],
        "db_connected": result["db_connected"],
    }


@app.post("/api/step2")
async def step2_format(
    job_id: str = Form(...),
    store: str = Form(""),
    creative: str = Form(""),
    eventdate: str = Form(""),
):
    """Step 2: Format Step 1 output for Portal 1."""
    if job_id not in _jobs:
        raise HTTPException(400, "Job not found. Upload a file first.")

    job = _jobs[job_id]
    step1_df = job["step1_df"]

    try:
        portal_df, stats = format_for_portal(
            step1_df,
            store=store.strip(),
            creative=creative.strip(),
            eventdate=eventdate.strip(),
        )
    except Exception as e:
        raise HTTPException(400, f"Formatting failed: {str(e)}")

    job["step2_df"] = portal_df
    job["stage"] = "portal"

    return {
        "job_id": job_id,
        "record_count": stats["total_count"],
        "org_count": stats["org_count"],
        "individual_count": stats["individual_count"],
    }


@app.get("/api/download/{job_id}")
async def download(job_id: str, stage: str = "latest", segment: str = "all"):
    """Download processed CSV.

    Args:
        job_id: The job identifier from step1/step2
        stage: "scanline" for Step 1 output, "portal" for Step 2, "latest" for most recent
        segment: "all", "organizations", or "individuals"
    """
    if job_id not in _jobs:
        raise HTTPException(400, "Job not found.")

    job = _jobs[job_id]
    orig = job["filename"]

    # Determine which DataFrame to use
    if stage == "latest":
        stage = job["stage"]

    if stage == "portal" and job["step2_df"] is not None:
        df = job["step2_df"]
        csv_bytes_fn = portal_to_csv_bytes
        org_col = "FirstName"
        is_org = lambda row: row.strip() == "Our Friends at"
        suffix = "Portal1"
    else:
        df = job["step1_df"]
        csv_bytes_fn = output_to_csv_bytes
        org_col = "OrganizationName"
        is_org = lambda row: row != ""
        suffix = "Scanline"

    # Filter by segment
    if segment == "organizations":
        df = df[df[org_col].apply(is_org)]
        suffix += "_orgs"
    elif segment == "individuals":
        df = df[~df[org_col].apply(is_org)]
        suffix += "_individuals"

    csv_bytes = csv_bytes_fn(df)
    out_name = f"{orig.rsplit('.', 1)[0]}_{suffix}.csv"

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


@app.get("/")
async def root():
    return FileResponse("static/index.html")
