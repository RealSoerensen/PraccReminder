from typing import Optional, Any, cast

import gspread
from oauth2client.service_account import ServiceAccountCredentials

import week
from config import AUTH_FILE, SPREADSHEET_ID, logger


def get_sheet() -> Optional[gspread.Worksheet]:
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(AUTH_FILE, cast(Any, scope))
        client = gspread.authorize(creds)

        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        week_name = week.get_week()

        worksheet = spreadsheet.worksheet(week_name)
        return worksheet
    except gspread.exceptions.WorksheetNotFound:
        week_name = week.get_week()
        logger.error("Worksheet '%s' not found!", week_name)
        try:
            worksheets = spreadsheet.worksheets()  # type: ignore[name-defined]
            available = [ws.title for ws in worksheets]
            logger.info("Available worksheets: %s", available)
        except Exception:
            pass
        return None
    except FileNotFoundError:
        logger.error("Auth file '%s' not found", AUTH_FILE)
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error accessing spreadsheet: %s", exc, exc_info=True)
        return None
