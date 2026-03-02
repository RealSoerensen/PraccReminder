import logging
from typing import Optional

import gspread
from oauth2client.service_account import ServiceAccountCredentials

import week


logger = logging.getLogger(__name__)


def get_sheet(auth_file: str, spreadsheet_id: str) -> Optional[gspread.Worksheet]:
    """
    Get the worksheet for the current week.

    Returns:
        The worksheet if found, None otherwise.
    """
    logger.debug("Attempting to access Google Sheets")
    spreadsheet = None
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(auth_file, scope)
        client = gspread.authorize(creds)
        logger.debug("Authorized with Google Sheets API")

        spreadsheet = client.open_by_key(spreadsheet_id)
        logger.debug(f"Opened spreadsheet: {spreadsheet_id}")

        week_name = week.get_week()
        logger.info(f"Looking for worksheet: '{week_name}'")

        worksheet = spreadsheet.worksheet(week_name)
        logger.info(f"Successfully found worksheet: '{week_name}'")
        return worksheet

    except gspread.exceptions.WorksheetNotFound:
        week_name = week.get_week()
        logger.error(f"Worksheet '{week_name}' not found!")
        if spreadsheet is not None:
            worksheets = spreadsheet.worksheets()
            available = [ws.title for ws in worksheets]
            logger.info(f"Available worksheets: {available}")
        return None
    except FileNotFoundError:
        logger.error(f"Auth file '{auth_file}' not found")
        return None
    except Exception as e:
        logger.error(f"Error accessing spreadsheet: {e}", exc_info=True)
        return None