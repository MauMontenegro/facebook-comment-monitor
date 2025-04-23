from fastapi import FastAPI
from src.routers.scrap_post import router as get_post_router

app= FastAPI(title="Redpetroil Facebook Scraper",version="1.0")

app.include_router(get_post_router,prefix="/get",tags=["Scraper"])

@app.get("/")
def read_root():
    return{"message":"RedPetroil Scraper is Online"}
