# src/storage/file_storage.py
import json
import csv
import os
import logging
from typing import Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class DataStorage:
    """Class to handle local data storage operations"""
    
    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        
        # Create log directory if it doesn't exist
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        
        self.comments_path = os.path.join(self.log_dir, "all_comments.json")
        self.csv_comments_path = os.path.join(self.log_dir, "all_comments.csv")
    
    def load_comments(self) -> Dict:
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
    
    def save_comments(self, comments: Dict) -> bool:
        """Save all comments to JSON file"""
        try:
            with open(self.comments_path, 'w', encoding='utf-8') as f:
                json.dump(comments, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error saving comments to JSON: {e}")
            return False
    
    def save_post_content(self, post_id: str, content: Dict) -> bool:
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
    
    def load_post_content(self, post_id: str) -> Dict:
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
    
    def append_to_csv(self, comment_data: Dict) -> bool:
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