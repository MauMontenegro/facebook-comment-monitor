# Facebook Comment Monitor

A tool for monitoring comments on Facebook posts and saving them to local files and Google Sheets.

## Project Structure

```
facebook-monitor/
│
├── .env                      # Environment variables and configuration
├── README.md                 # Project documentation
├── requirements.txt          # Dependencies list
│
├── src/                      # Main source code directory
│   ├── __init__.py           # Makes src a proper package
│   ├── main.py               # Entry point that starts the application
│   │
│   ├── api/                  # API related code
│   │   ├── __init__.py
│   │   └── facebook.py       # Facebook Graph API wrapper
│   │
│   ├── storage/              # Data storage solutions
│   │   ├── __init__.py
│   │   ├── file_storage.py   # JSON and CSV file handling
│   │   └── sheets.py         # Google Sheets integration
│   │
│   └── monitor/              # Core monitoring functionality
│       ├── __init__.py
│       └── facebook_monitor.py # Main monitoring logic
│
└── logs/                     # Log files directory
```

## Installation

1. Clone this repository
2. Install dependencies:
```
pip install -r requirements.txt
```
3. Create a `.env` file with your configuration (see example in the repository)
4. Set up Google API credentials (save as `credentials.json`)

## Usage

Run the monitor:

```
python -m src.main
```

## Configuration

The following environment variables are required:

- `PAGE_ID`: Facebook page ID
- `TARGET_POST_ID`: ID of the post to monitor
- `GRAPH_API_TOKEN`: Facebook Graph API access token

Optional configuration:

- `API_VERSION`: Facebook Graph API version (default: "v22.0")
- `INTERVAL`: Check interval in seconds (default: 60)
- `BATCH_SIZE`: Max comments to upload at once (default: 7)
- `UPLOAD_INTERVAL`: Max time between uploads in seconds (default: 300)
- `LOG_DIR`: Directory to store logs and data (default: "facebook_monitor_logs")
- `GOOGLE_SHEETS_CREDS_FILE`: Path to Google API credentials file (default: "credentials.json")
- `SPREADSHEET_NAME`: Name of Google Spreadsheet (default: "Facebook Comments Tracker")
- `WORKSHEET_NAME`: Name of worksheet (default: "Comments")
- `ADMIN_EMAIL`: Email to share spreadsheet with (optional)

## Features

- Monitors Facebook post comments in real-time
- Tracks changes to post content
- Saves data locally in JSON and CSV formats
- Syncs comments to Google Sheets
- Implements exponential backoff for API retries
- Includes pagination support for large comment threads
- Handles error recovery and reconnection