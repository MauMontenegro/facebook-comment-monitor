# src/api/facebook.py
import requests
import logging
import backoff
from typing import Dict, Tuple, Optional, Any

logger = logging.getLogger(__name__)

class FacebookAPI:
    """Class to handle Facebook Graph API interactions"""
    
    def __init__(self, access_token: str, api_version: str):
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = f"https://graph.facebook.com/{api_version}"
    
    @backoff.on_exception(backoff.expo, 
                          (requests.exceptions.RequestException, 
                           requests.exceptions.HTTPError,
                           requests.exceptions.ConnectionError),
                          max_tries=3,
                          max_time=60)
    def make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a request to the Facebook Graph API with exponential backoff on failure"""
        if params is None:
            params = {}
        
        # Ensure access_token is in params
        params["access_token"] = self.access_token
        
        url = f"{self.base_url}/{endpoint}"
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error to Facebook API: {e}")
            raise
        except Exception as e:
            logger.error(f"API request failed: {e}")
            raise
    
    def get_post_content(self, post_id: str) -> Optional[Dict]:
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
                
        except requests.exceptions.ConnectionError:
            logger.warning("Network connection failed, skipping post content fetch")
            return None
        except Exception as e:
            logger.error(f"Error getting post content: {e}")
            return None
    
    def get_comments(self, post_id: str, limit: int = 100, after: Optional[str] = None) -> Tuple[Dict, Optional[str]]:
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
                
        except requests.exceptions.ConnectionError:
            logger.warning("Network connection failed, returning empty comments")
            return {}, None
        except Exception as e:
            logger.error(f"Error fetching comments: {e}")
            return {}, None