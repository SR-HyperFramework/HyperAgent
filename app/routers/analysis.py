from fastapi import APIRouter, UploadFile, File, HTTPException
from app.models import AnalysisResponse, DIEResult
from app.services.die_service import run_die
import shutil
import os
import tempfile

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.post("/scan", response_model=AnalysisResponse)
async def scan_file(file: UploadFile = File(...)):
    # Save uploaded file to a temporary file
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")

    try:
        # Run DIE analysis
        die_output = run_die(tmp_path)
        
        return AnalysisResponse(
            filename=file.filename,
            die_result=DIEResult(
                raw_output=die_output.get("raw", ""),
                parsed_output=die_output.get("parsed", {}),
                error=die_output.get("error")
            )
        )
    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
