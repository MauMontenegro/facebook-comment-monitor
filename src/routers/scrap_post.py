from fastapi import APIRouter,BackgroundTasks
from src.schemas.request_schemas import ScrapResponse,ScrapRequest
from src.init import main as initialize

router = APIRouter()

@router.post("/postid",response_model=ScrapResponse)
async def get_post(scrap_request:ScrapRequest,background_tasks:BackgroundTasks)->ScrapResponse:
    """Scrap a facebook post and send it to G-Sheets"""

    # Get variables
    post_id = scrap_request.post_id
    sheet_name = scrap_request.sheet_name
    worksheet_name = scrap_request.worksheet_name

    run_type = 'one-click'
    background_tasks.add_task(initialize, post_id, sheet_name, worksheet_name, run_type)
    return {
        "response":"Success: El proceso de scraping ha iniciado. Los datos se actualizarán en Google Sheets gradualmente."
    }
    