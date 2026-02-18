import time
import logging
from datetime import datetime
from typing import Set, List, Dict, Any, Optional

from ..api.facebook import FacebookAPI
from ..storage.file_storage import DataStorage
from ..storage.sheets import GoogleSheetsHandler

logger = logging.getLogger(__name__)

class FacebookMonitor:
    """Main class to monitor Facebook comments - Optimized for large volumes"""
    
    def __init__(self, fb_api: FacebookAPI, data_storage: DataStorage, 
                 sheets_handler: Optional[GoogleSheetsHandler], 
                 post_id: str, target_post_id: str, 
                 interval: int, batch_size: int, upload_interval: int, type: str):
        self.post_id = post_id
        self.target_post_id = target_post_id
        self.interval = interval
        self.batch_size = batch_size
        self.upload_interval = upload_interval
        self.monitor_type = type 
        
        # Initialize components
        self.fb_api = fb_api
        self.data_storage = data_storage
        self.sheets_handler = sheets_handler
        self.sheets_enabled = sheets_handler is not None
        
        # Load existing data and initialize state
        self._init_state()
    
    def _init_state(self) -> None:
        """Initialize state from Google Sheets data"""
        self.known_comments = set()
        
        if self.sheets_enabled:
            self.known_comments = self.sheets_handler.get_existing_comments()
            logger.info(f"Loaded {len(self.known_comments)} known comments from Google Sheets")
        else:
            logger.warning("Google Sheets not enabled, no existing comments will be tracked")
        
        self.last_post = self.data_storage.load_post_content(self.target_post_id)
        self.last_content = self.last_post.get("message") if self.last_post else None
        
        self.comment_batch = []
        self.last_upload_time = datetime.now()

    def process_comment(self, comment_id: str, comment_data: Dict) -> None:
        """Mantiene tu lógica original de guardado en CSV y preparación de batch"""
        comment_data['timestamp'] = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if comment_data.get('image'):
            csv_data = {
                'comment_id': comment_id,
                'user_id': comment_data['from'].get('id', 'Unknown'),
                'user_name': comment_data['from'].get('name', 'Unknown'),
                'created_time': comment_data['created_time'],
                'message': comment_data['message'],
                'has_attachment': comment_data['image']['media']['image']['src'] if comment_data.get('image') else 'No',
                'detected_time': comment_data['timestamp']
            }
            
            self.data_storage.append_to_csv(csv_data)

            if self.sheets_enabled:
                row_data = [
                    csv_data['comment_id'], csv_data['user_id'], csv_data['user_name'],
                    csv_data['created_time'], csv_data['message'], 
                    csv_data['has_attachment'], csv_data['detected_time']
                ]
                self.comment_batch.append(row_data)
                self.known_comments.add(comment_id)
                logger.info(f"Comment {comment_id} added to batch ({len(self.comment_batch)})")
        else:
            logger.info(f"Comment {comment_id} has no image attached.")
            
    def upload_batch_to_sheets(self, force: bool = False) -> None:
        """Mantiene tu lógica original de subida a Google Sheets"""
        if not self.sheets_enabled or not self.comment_batch:
            return
        
        current_time = datetime.now()
        time_since_last_upload = (current_time - self.last_upload_time).total_seconds()
        
        if (len(self.comment_batch) >= self.batch_size or 
            (force and len(self.comment_batch) > 0) or
            (time_since_last_upload >= self.upload_interval and len(self.comment_batch) > 0)):
            
            existing_comment_ids = self.sheets_handler.get_existing_comments()
            filtered_batch = [row for row in self.comment_batch if row[0] not in existing_comment_ids]
            
            if not filtered_batch:
                self.comment_batch = []
                self.last_upload_time = current_time
                return
            
            logger.info(f"Uploading {len(filtered_batch)} comments to Sheets...")
            if self.sheets_handler.append_rows(filtered_batch):
                self.comment_batch = []
                self.last_upload_time = current_time
                logger.info("Upload successful")
            else:
                logger.error("Upload failed")

    def check_and_update_post_content(self) -> Optional[Dict]:
        """Mantiene tu lógica original de actualización de contenido del post"""
        content = self.fb_api.get_post_content(self.post_id)
        if content and (not self.last_content or content.get("message") != self.last_content):
            self.data_storage.save_post_content(self.target_post_id, content)
            self.last_content = content.get("message")
            logger.info("Post content updated")
        return content

    def monitor(self) -> None:
        """
        Main loop redesigned for 'Streaming'. 
        Procesa página por página para evitar bloqueos en Render.
        """
        logger.info(f"Starting monitor for post {self.post_id}...")
        
        # Guardado inicial
        self.check_and_update_post_content()
        logger.info("Initial post content check complete")

        consecutive_errors = 0
        max_consecutive_errors = 5
        
        try:
            while True:
                try:
                    next_page = None
                    total_new_found = 0
                    page_num = 1
                    
                    # --- INICIO DEL STREAMING ---
                    while True:
                        logger.info(f"Fetching page {page_num}...")
                        # Pedimos una sola página a la API
                        current_page_data, next_page = self.fb_api.get_comments(self.post_id, after=next_page)
                        
                        if not current_page_data:
                            break

                        # Procesamos los comentarios DE ESTA PÁGINA inmediatamente
                        for cid, cdata in current_page_data.items():
                            if cid not in self.known_comments:
                                self.process_comment(cid, cdata)
                                total_new_found += 1
                        
                        # Si el batch se llenó procesando esta página, subimos de una vez
                        if len(self.comment_batch) >= self.batch_size:
                            self.upload_batch_to_sheets()

                        if not next_page:
                            break
                        
                        page_num += 1
                        time.sleep(0.5) # Respiro para la API
                    # --- FIN DEL STREAMING ---

                    if total_new_found > 0:
                        logger.info(f"Cycle total: {total_new_found} new comments found.")
                    
                    # Forzar subida de lo que haya quedado
                    self.upload_batch_to_sheets(force=True)
                    
                    consecutive_errors = 0
                    if self.monitor_type == 'one-click':
                        break
                        
                    time.sleep(self.interval)
                    
                except Exception as e:
                    consecutive_errors += 1
                    logger.error(f"Error (attempt {consecutive_errors}): {e}")
                    if consecutive_errors >= max_consecutive_errors: break
                    time.sleep(min(self.interval * (2 ** consecutive_errors), 3600))
        
        finally:
            self.upload_batch_to_sheets(force=True)
            logger.info("Monitor shutdown complete.")