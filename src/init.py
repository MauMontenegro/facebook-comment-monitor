# src/main.py
import os
import logging
from dotenv import load_dotenv

from src.api.facebook import FacebookAPI
from src.storage.file_storage import DataStorage
from src.storage.sheets import GoogleSheetsHandler
from src.monitor.facebook_monitor import FacebookMonitor

# Set up logging
def setup_logging():
    log_dir = os.getenv("LOG_DIR", "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f"{log_dir}/facebook_monitor.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("facebook_monitor")

def validate_env_vars():
    """Validate required environment variables"""
    required_env_vars = ["PAGE_ID", "TARGET_POST_ID", "GRAPH_API_TOKEN"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

def main(post,sheet,worksheet,type):
    """Main entry point for the application"""
    # Load environment variables
    load_dotenv()
    
    # Setup logging
    logger = setup_logging()
    
    # Validate environment variables
    validate_env_vars()

    # request Variables
    target_post_id = post
    spreadsheet_name = sheet
    worksheet_name = worksheet

    # Get configuration from environment variables
    fb_page_id = os.getenv("PAGE_ID")    
    access_token = os.getenv("LONG_LIVE_TOKEN")
    api_version = os.getenv("API_VERSION", "v22.0")
    interval = int(os.getenv("INTERVAL", "60"))
    batch_size = int(os.getenv("BATCH_SIZE", "7"))
    upload_interval = int(os.getenv("UPLOAD_INTERVAL", "300"))
    log_dir = os.getenv("LOG_DIR", "facebook_monitor_logs")
    
    # Google Sheets Configuration
    sheets_creds_file = os.getenv("GOOGLE_SHEETS_CREDS_FILE", "credentials.json")
    
        # Initialize components
    fb_api = FacebookAPI(access_token, api_version)
    data_storage = DataStorage(log_dir)
    
    # Try to initialize Google Sheets (optional)
    sheets_handler = None
    try:
        sheets_handler = GoogleSheetsHandler(
            sheets_creds_file,
            spreadsheet_name,
            worksheet_name
        )
    except Exception as e:
        logger.warning(f"Google Sheets integration disabled: {e}")        
    
    # Create and run monitor
    post_id = f"{fb_page_id}_{target_post_id}"
    monitor = FacebookMonitor(
        fb_api=fb_api,
        data_storage=data_storage,
        sheets_handler=sheets_handler,
        post_id=post_id,
        target_post_id=target_post_id,
        interval=interval,
        batch_size=batch_size,
        upload_interval=upload_interval,
        type=type
    )
    
    try:
        logger.info("Facebook Comment Monitor Initialized")
        monitor.monitor()
        return "Success"
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user. Uploading final batch...")
        monitor.upload_batch_to_sheets(force=True)
        logger.info("Shutdown complete.")
        return "Monitor Stopped By User"

if __name__ == "__main__":
    main("","","",'one-click')