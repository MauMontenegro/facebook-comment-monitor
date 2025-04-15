# src/monitor/facebook_monitor.py
import time
import logging
from datetime import datetime
from typing import Set, List, Dict, Any, Optional

from ..api.facebook import FacebookAPI
from ..storage.file_storage import DataStorage
from ..storage.sheets import GoogleSheetsHandler

logger = logging.getLogger(__name__)

class FacebookMonitor:
    """Main class to monitor Facebook comments"""
    
    def __init__(self, fb_api: FacebookAPI, data_storage: DataStorage, 
                 sheets_handler: Optional[GoogleSheetsHandler], 
                 post_id: str, target_post_id: str, 
                 interval: int, batch_size: int, upload_interval: int):
        self.post_id = post_id
        self.target_post_id = target_post_id
        self.interval = interval
        self.batch_size = batch_size
        self.upload_interval = upload_interval
        
        # Initialize components
        self.fb_api = fb_api
        self.data_storage = data_storage
        self.sheets_handler = sheets_handler
        self.sheets_enabled = sheets_handler is not None
        
        # Load existing data and initialize state
        self._init_state()
    
    def _init_state(self) -> None:
        """Initialize state from stored data"""
        # Load existing comments
        all_comments = self.data_storage.load_comments()
        self.known_comments = set(all_comments.keys())
        
        # Load post content
        self.last_post = self.data_storage.load_post_content(self.target_post_id)
        if self.last_post:
            self.last_content = self.last_post.get("message")
        else:
            self.last_content = None
        
        # Create a batch for comments
        self.comment_batch = []
        self.last_upload_time = datetime.now()
    
    def process_comment(self, comment_id: str, comment_data: Dict) -> Dict:
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
            'has_attachment': comment_data['image']['media']['image']['src'] if comment_data.get('image') else 'No',
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
    
    def upload_batch_to_sheets(self, force: bool = False) -> None:
        """Upload batched comments to Google Sheets if conditions are met"""
        if not self.sheets_enabled or not self.comment_batch:
            return
        
        current_time = datetime.now()
        time_since_last_upload = (current_time - self.last_upload_time).total_seconds()
        
        # Upload if batch is full or enough time has passed
        if (len(self.comment_batch) >= self.batch_size or 
            (force and len(self.comment_batch) > 0) or
            (time_since_last_upload >= self.upload_interval and len(self.comment_batch) > 0)):
            
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
    
    def fetch_all_comments(self) -> Dict:
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
    
    def check_and_update_post_content(self) -> Optional[Dict]:
        """Check if post content has changed and update if needed"""
        content = self.fb_api.get_post_content(self.post_id)
        
        # Check if content has changed since last check
        content_changed = False
        if content and self.last_content:
            if content.get("message") != self.last_content:
                content_changed = True
        
        # Save Post content only if there is no last_content or content change
        if content and (not self.last_content or content_changed):
            self.data_storage.save_post_content(self.target_post_id, content)
            self.last_content = content.get("message")
            logger.info("Post content updated and saved")
        
        return content
    
    def monitor(self) -> None:
        """Main monitoring loop"""
        logger.info(f"Starting to monitor post {self.post_id}...")
        
        # Get initial post content and save it
        initial_content = self.fb_api.get_post_content(self.post_id)
        if initial_content and initial_content.get("message") != self.last_content:
            self.data_storage.save_post_content(self.target_post_id, initial_content)
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
                    time.sleep(self.interval)
                    
                except Exception as e:
                    consecutive_errors += 1
                    
                    if consecutive_errors >= max_consecutive_errors:
                        logger.critical(f"Too many consecutive errors ({consecutive_errors}). Exiting.")
                        break
                    
                    # Calculate backoff time
                    backoff_time = min(self.interval * (2 ** consecutive_errors), 3600)  # Max 1 hour
                    
                    logger.error(f"Error in monitoring loop (attempt {consecutive_errors}/{max_consecutive_errors}): {e}")
                    logger.info(f"Backing off for {backoff_time} seconds before retry...")
                    
                    time.sleep(backoff_time)
        
        finally:
            # Upload any remaining comments in the batch before exiting
            logger.info("Uploading remaining comments before exiting...")
            self.upload_batch_to_sheets(force=True)
            logger.info("Final batch upload complete")