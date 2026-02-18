
from fastapi import APIRouter,HTTPException
import requests
router = APIRouter()
from src.api.google_ai import extraerInfo

from pydantic import BaseModel

class OCRRequest(BaseModel):
    image_url: str

@router.post("/ocr_text")
async def upload_url(data:OCRRequest):
    """
        Llamada al agente de ocr y estructuración mediente una url
    """
    image_url = data.image_url
    if not image_url:
        raise HTTPException(status_code=400, detail="No image_url provided.")    
    response_ticket_url = requests.get(image_url,timeout=20)
    response_ticket_url.raise_for_status()
    image_bytes = response_ticket_url.content     
    try:
        resultado = extraerInfo(image_bytes) 
        return {"structured_text":resultado}
    except Exception as e:
        custom_json = {
            "date": "None",
            "address": "None",
            "station": "None",
            "total": 0,
            "quantity": 0
             }
        print(f"Error in general_schematizer: {str(e)}")
        return{"structured:text":custom_json}
    