# src/storage/sheets.py
import logging
import backoff
import gspread
import os

from oauth2client.service_account import ServiceAccountCredentials
from typing import List, Optional, Any

logger = logging.getLogger(__name__)

class GoogleSheetsHandler:
    """Class to handle Google Sheets operations"""
    
    def __init__(self, creds_file: str, spreadsheet_name: str, worksheet_name: str):
        self.creds_file = creds_file
        self.spreadsheet_name = spreadsheet_name
        self.worksheet_name = worksheet_name
        self.gs_client = None
        self.worksheet = None
        self.init_connection()
    
    def init_connection(self) -> bool:
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
                else:
                    logger.info("No admin email provided")
            
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
    def append_rows(self, rows: List[List[Any]]) -> bool:
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
    def get_existing_comments(self) -> set:
        """Retrieve existing comment IDs from the worksheet"""
        if not self.worksheet:
            if not self.init_connection():
                logger.error("Cannot get existing comments: No worksheet connection")
                return set()
        
        try:
            # Get all values from the worksheet
            all_values = self.worksheet.get_all_values()
            
            # Skip the header row and extract comment IDs (first column)
            comment_ids = {row[0] for row in all_values[1:] if row and row[0]}
            
            logger.info(f"Retrieved {len(comment_ids)} existing comment IDs from Google Sheets")
            return comment_ids
        
        except Exception as e:
            logger.error(f"Error retrieving existing comments from sheet: {e}")
            return set()