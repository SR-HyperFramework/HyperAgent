from pydantic import BaseModel
from typing import Dict, Any, Optional

class AnalysisRequest(BaseModel):
    # For now, we might not need a body if we just upload a file, 
    # but keeping this for future extensibility (e.g. options)
    pass

class DIEResult(BaseModel):
    parsed: Optional[Dict[str, Any]] = None

# class DIEResult(BaseModel):
#     raw_output: str
#     parsed_output: Optional[Dict[str, Any]] = None
#     file_class: Optional[str] = None
#     packer: Optional[str] = None
#     compiler: Optional[str] = None
#     language: Optional[str] = None
#     error: Optional[str] = None

class AnalysisResponse(BaseModel):
    filename: str
    die_result: DIEResult


