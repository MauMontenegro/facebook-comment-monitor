from fastapi import APIRouter
from src.schemas.request_schemas import ScrapResponse,ScrapRequest
from src.init import main as initialize

router = APIRouter()

@router.post("/postid",response_model=ScrapResponse)
async def get_post(scrap_request:ScrapRequest)->ScrapResponse:
    """Scrap a facebook post and send it to G-Sheets"""

    # Get variables
    post_id = scrap_request.post_id
    sheet_name = scrap_request.sheet_name
    worksheet_name = scrap_request.worksheet_name

    type = 'one-click'
    response = initialize(post_id,sheet_name,worksheet_name,type)
    return {"response":response}
    