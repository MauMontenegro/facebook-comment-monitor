import time
import requests
import json
import csv
import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import backoff

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("facebook_monitor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("facebook_monitor")

# Load environment variables
load_dotenv()

# Configuration
required_env_vars = ["PAGE_ID", "TARGET_POST_ID", "GRAPH_API_TOKEN"]
missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

FB_PAGE_ID = os.getenv("PAGE_ID")              
TARGET_POST_ID = os.getenv("TARGET_POST_ID")
ACCESS_TOKEN = os.getenv("GRAPH_API_TOKEN")
API_VERSION = os.getenv("API_VERSION", "v22.0")  # Use the latest version available
INTERVAL = int(os.getenv("INTERVAL", "60"))  # Default to 60 seconds

# Google Sheets Configuration
GOOGLE_SHEETS_CREDS_FILE = os.getenv("GOOGLE_SHEETS_CREDS_FILE", "credentials.json")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Facebook Comments Tracker")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Comments")

# Batch size and upload interval
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "7"))  # Maximum number of comments to upload at once
UPLOAD_INTERVAL = int(os.getenv("UPLOAD_INTERVAL", "300"))  # Upload batch every 5 minutes (300 seconds)


class FacebookAPI:
    """Class to handle Facebook Graph API interactions"""
    
    def __init__(self, access_token, api_version):
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = f"https://graph.facebook.com/{api_version}"
    
    @backoff.on_exception(backoff.expo, 
                          (requests.exceptions.RequestException, 
                           requests.exceptions.HTTPError),
                          max_tries=5)
    def make_request(self, endpoint, params=None):
        """Make a request to the Facebook Graph API with exponential backoff on failure"""
        if params is None:
            params = {}
        
        # Ensure access_token is in params
        params["access_token"] = self.access_token
        
        url = f"{self.base_url}/{endpoint}"
        
        response = requests.get(url, params=params)
        
        # Raise an exception for bad status codes
        response.raise_for_status()
        
        return response.json()
    
    def get_post_content(self, post_id):
        """Get content of a specific post"""
        try:
            data = self.make_request(
                post_id,
                params={"fields": "message,created_time,permalink_url"}
            )
            
            return {
                "message": data.get("message", "No message content"),
                "created_time": data.get("created_time", "Unknown time"),
                "url": data.get("permalink_url", "Unknown URL")
            }
                
        except Exception as e:
            logger.error(f"Error getting post content: {e}")
            return None
    
    def get_comments(self, post_id, limit=100, after=None):
        """Get comments for a specific post with pagination support"""
        params = {
            "fields": "id,created_time,message,from,attachment",
            "limit": limit
        }
        
        if after:
            params["after"] = after
            
        try:
            data = self.make_request(f"{post_id}/comments", params=params)
            
            comments = {comment['id']: {
                'from': comment.get('from', {'name': 'Unknown', 'id': 'Unknown'}),
                'created_time': comment['created_time'],
                'message': comment.get('message', 'No message'),
                'image': comment.get('attachment'),
            } for comment in data.get('data', [])}
            
            # Check for pagination
            paging = data.get('paging', {})
            next_page = paging.get('cursors', {}).get('after')
            
            return comments, next_page
                
        except Exception as e:
            logger.error(f"Error fetching comments: {e}")
            return {}, None


class GoogleSheetsHandler:
    """Class to handle Google Sheets operations"""
    
    def __init__(self, creds_file, spreadsheet_name, worksheet_name):
        self.creds_file = creds_file
        self.spreadsheet_name = spreadsheet_name
        self.worksheet_name = worksheet_name
        self.gs_client = None
        self.worksheet = None
        self.init_connection()
    
    def init_connection(self):
        """Initialize connection to Google Sheets"""
        try:
            # Define the scope
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            # Add credentials to the account
            creds = ServiceAccountCredentials.from_json_keyfile_name(self.creds_file, scope)
            
            # Authorize the client
            self.gs_client = gspread.authorize(creds)
            
            # Get or create the spreadsheet
            try:
                spreadsheet = self.gs_client.open(self.spreadsheet_name)
                logger.info(f"Connected to existing spreadsheet: {self.spreadsheet_name}")
            except gspread.exceptions.SpreadsheetNotFound:
                spreadsheet = self.gs_client.create(self.spreadsheet_name)
                logger.info(f"Created new spreadsheet: {self.spreadsheet_name}")
                
                # Share with email if provided
                admin_email = os.getenv("ADMIN_EMAIL")
                if admin_email:
                    spreadsheet.share(admin_email, perm_type='user', role='writer')
                    logger.info(f"Shared spreadsheet with {admin_email}")
            
            # Get or create the worksheet
            try:
                self.worksheet = spreadsheet.worksheet(self.worksheet_name)
                logger.info(f"Using existing worksheet: {self.worksheet_name}")
            except gspread.exceptions.WorksheetNotFound:
                self.worksheet = spreadsheet.add_worksheet(title=self.worksheet_name, rows=1000, cols=20)
                logger.info(f"Created new worksheet: {self.worksheet_name}")
                
                # Add headers
                headers = ['comment_id', 'user_id', 'user_name', 'created_time', 'message', 'has_attachment', 'detected_time']
                self.worksheet.update('A1:G1', [headers])
                logger.info("Added headers to worksheet")
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets: {e}")
            return False
    
    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    def append_rows(self, rows):
        """Append rows to the worksheet with retry logic"""
        if not self.worksheet:
            if not self.init_connection():
                logger.error("Cannot append rows: No worksheet connection")
                return False
        
        try:
            self.worksheet.append_rows(rows)
            return True
        except gspread.exceptions.APIError as e:
            if "invalid_grant" in str(e) or "token expired" in str(e).lower():
                logger.warning("Google Sheets token expired, refreshing...")
                self.init_connection()
                # Let backoff retry with the refreshed connection
                raise
            else:
                raise


class DataStorage:
    """Class to handle local data storage operations"""
    
    def __init__(self, log_dir):
        self.log_dir = log_dir
        
        # Create log directory if it doesn't exist
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        
        self.comments_path = os.path.join(self.log_dir, "all_comments.json")
        self.csv_comments_path = os.path.join(self.log_dir, "all_comments.csv")
    
    def load_comments(self):
        """Load existing comments from JSON file"""
        if os.path.exists(self.comments_path):
            try:
                with open(self.comments_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error(f"Error reading comments file: {self.comments_path}")
                return {}
        else:
            return {}
    
    def save_comments(self, comments):
        """Save all comments to JSON file"""
        try:
            with open(self.comments_path, 'w', encoding='utf-8') as f:
                json.dump(comments, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error saving comments to JSON: {e}")
            return False
    
    def save_post_content(self, post_id, content):
        """Save the post content to a file"""
        if not content:
            return False
        
        filename = os.path.join(self.log_dir, f"post_content_{post_id}.json")
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(content, f, indent=4)
            
            logger.info(f"Post content saved to {filename}")
            return True
        except Exception as e:
            logger.error(f"Error saving post content: {e}")
            return False
    
    def load_post_content(self, post_id):
        """Load post content from file"""
        filename = os.path.join(self.log_dir, f"post_content_{post_id}.json")
        
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error(f"Error reading post content file: {filename}")
                return {}
        else:
            return {}
    
    def append_to_csv(self, comment_data):
        """Append comment data to CSV file"""
        try:
            file_exists = os.path.exists(self.csv_comments_path)
            
            with open(self.csv_comments_path, 'a', newline='', encoding='utf-8') as f:
                fieldnames = ['comment_id', 'user_id', 'user_name', 'created_time', 'message', 'has_attachment', 'detected_time']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                # Write header only if file is new
                if not file_exists:
                    writer.writeheader()
                
                writer.writerow(comment_data)
            
            return True
        except Exception as e:
            logger.error(f"Error appending to CSV: {e}")
            return False


class FacebookMonitor:
    """Main class to monitor Facebook comments"""
    
    def __init__(self):
        self.post_id = f"{FB_PAGE_ID}_{TARGET_POST_ID}"
        self.log_dir = "facebook_monitor_logs"
        
        # Initialize components
        self.fb_api = FacebookAPI(ACCESS_TOKEN, API_VERSION)
        self.data_storage = DataStorage(self.log_dir)
        
        # Try to initialize Google Sheets
        try:
            self.sheets_handler = GoogleSheetsHandler(
                GOOGLE_SHEETS_CREDS_FILE,
                SPREADSHEET_NAME,
                WORKSHEET_NAME
            )
            self.sheets_enabled = True
        except Exception as e:
            logger.warning(f"Google Sheets integration disabled: {e}")
            self.sheets_handler = None
            self.sheets_enabled = False
        
        # Load existing data
        all_comments = self.data_storage.load_comments()
        self.known_comments = set(all_comments.keys())
        
        # Load post content
        self.last_post = self.data_storage.load_post_content(TARGET_POST_ID)
        if self.last_post:
            self.last_content = self.last_post.get("message")
        else:
            self.last_content = None
        
        # Create a batch for comments
        self.comment_batch = []
        self.last_upload_time = datetime.now()
    
    def process_comment(self, comment_id, comment_data):
        """Process a new comment: save to storage and add to batch"""
        # Add timestamp to comment data
        comment_data['timestamp'] = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Get all current comments
        all_comments = self.data_storage.load_comments()
        
        # Add or update the comment
        all_comments[comment_id] = comment_data
        
        # Save back to storage
        self.data_storage.save_comments(all_comments)
        
        # Prepare CSV data
        csv_data = {
            'comment_id': comment_id,
            'user_id': comment_data['from'].get('id', 'Unknown'),
            'user_name': comment_data['from'].get('name', 'Unknown'),
            'created_time': comment_data['created_time'],
            'message': comment_data['message'],
            'has_attachment': "Yes" if comment_data.get('image') else 'No',
            'detected_time': comment_data['timestamp']
        }
        
        # Save to CSV
        self.data_storage.append_to_csv(csv_data)
        
        # Add to batch for Google Sheets
        if self.sheets_enabled:
            row_data = [
                csv_data['comment_id'],
                csv_data['user_id'],
                csv_data['user_name'],
                csv_data['created_time'],
                csv_data['message'],
                csv_data['has_attachment'],
                csv_data['detected_time']
            ]
            
            self.comment_batch.append(row_data)
        
        logger.info(f"Comment {comment_id} processed and added to batch (size: {len(self.comment_batch)})")
        
        return all_comments
    
    def upload_batch_to_sheets(self, force=False):
        """Upload batched comments to Google Sheets if conditions are met"""
        if not self.sheets_enabled or not self.comment_batch:
            return
        
        current_time = datetime.now()
        time_since_last_upload = (current_time - self.last_upload_time).total_seconds()
        
        # Upload if batch is full or enough time has passed
        if (len(self.comment_batch) >= BATCH_SIZE or 
            (force and len(self.comment_batch) > 0) or
            (time_since_last_upload >= UPLOAD_INTERVAL and len(self.comment_batch) > 0)):
            
            batch_size = len(self.comment_batch)
            logger.info(f"Uploading batch of {batch_size} comments to Google Sheets...")
            
            success = self.sheets_handler.append_rows(self.comment_batch)
            
            if success:
                logger.info(f"Successfully uploaded {batch_size} comments to Google Sheets")
                
                # Clear batch and reset timer
                self.comment_batch = []
                self.last_upload_time = current_time
            else:
                logger.error("Failed to upload batch to Google Sheets")
    
    def fetch_all_comments(self):
        """Fetch all comments with pagination support"""
        all_comments = {}
        next_page = None
        
        while True:
            comments, next_page = self.fb_api.get_comments(self.post_id, after=next_page)
            all_comments.update(comments)
            
            if not next_page:
                break
                
            # Small delay to avoid rate limits
            time.sleep(1)
        
        return all_comments
    
    def check_and_update_post_content(self):
        """Check if post content has changed and update if needed"""
        content = self.fb_api.get_post_content(self.post_id)
        
        # Check if content has changed since last check
        content_changed = False
        if content and self.last_content:
            if content.get("message") != self.last_content:
                content_changed = True
        
        # Save Post content only if there is no last_content or content change
        if content and (not self.last_content or content_changed):
            self.data_storage.save_post_content(TARGET_POST_ID, content)
            self.last_content = content.get("message")
            logger.info("Post content updated and saved")
        
        return content
    
    def monitor(self):
        """Main monitoring loop"""
        logger.info(f"Starting to monitor post {self.post_id}...")
        
        # Get initial post content and save it
        initial_content = self.fb_api.get_post_content(self.post_id)
        if initial_content and initial_content.get("message") != self.last_content:
            self.data_storage.save_post_content(TARGET_POST_ID, initial_content)
            self.last_content = initial_content.get("message")
            logger.info("Initial post content saved")
        
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        try:
            while True:
                try:
                    # Get current comments
                    current_comments = self.fetch_all_comments()
                    
                    # Check if there are new comments
                    current_comment_ids = set(current_comments.keys())
                    new_comments = current_comment_ids - self.known_comments
                    
                    if new_comments:
                        logger.info(f"Found {len(new_comments)} new comments!")
                        
                        # Extract and save post content
                        self.check_and_update_post_content()
                        
                        # Log the new comments
                        for comment_id in new_comments:
                            comment_data = current_comments[comment_id]
                            logger.info(f"New comment at {comment_data['created_time']}: {comment_id}")
                            self.process_comment(comment_id, comment_data)
                        
                        # Update known comments
                        self.known_comments = current_comment_ids
                    
                    # Check if it's time to upload batch
                    self.upload_batch_to_sheets()
                    
                    # Reset consecutive errors counter on success
                    consecutive_errors = 0
                    
                    # Wait before checking again
                    time.sleep(INTERVAL)
                    
                except Exception as e:
                    consecutive_errors += 1
                    
                    if consecutive_errors >= max_consecutive_errors:
                        logger.critical(f"Too many consecutive errors ({consecutive_errors}). Exiting.")
                        break
                    
                    # Calculate backoff time
                    backoff_time = min(INTERVAL * (2 ** consecutive_errors), 3600)  # Max 1 hour
                    
                    logger.error(f"Error in monitoring loop (attempt {consecutive_errors}/{max_consecutive_errors}): {e}")
                    logger.info(f"Backing off for {backoff_time} seconds before retry...")
                    
                    time.sleep(backoff_time)
        
        finally:
            # Upload any remaining comments in the batch before exiting
            logger.info("Uploading remaining comments before exiting...")
            self.upload_batch_to_sheets(force=True)
            logger.info("Final batch upload complete")


if __name__ == "__main__":
    monitor = FacebookMonitor()
    try:
        logger.info("Facebook Comment Monitor Initialized")
        monitor.monitor()
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user. Uploading final batch...")
        monitor.upload_batch_to_sheets(force=True)
        logger.info("Shutdown complete.")