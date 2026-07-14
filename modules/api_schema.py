from pydantic import BaseModel


class AnalyzePathRequest(BaseModel):
    file_path: str
