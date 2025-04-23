from pydantic import BaseModel

class ScrapRequest(BaseModel):
    post_id : str
    sheet_name :str
    workshee_name : str

class ScrapResponse(BaseModel):
    response: str

