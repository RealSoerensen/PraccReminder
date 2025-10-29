"""
Flask wrapper for running the Discord bot on Azure Web App.
Azure Web Apps require an HTTP server, so this provides a minimal Flask app
while running the Discord bot in a background thread.
"""

from flask import Flask, jsonify, request
import threading
import logging
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Bot status
bot_status = {
    "running": False,
    "started": False,
    "error": None,
    "startup_attempted": False
}

# Bot thread reference
bot_thread = None

def ensure_bot_started():
    """Ensure the bot thread is started (call this on first request)."""
    global bot_thread
    
    if bot_status["startup_attempted"]:
        return  # Already attempted to start
    
    try:
        logger.info("=== First request - Starting Discord bot thread ===")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Working directory: {os.getcwd()}")
        logger.info(f"Environment check - DISCORD_TOKEN set: {bool(os.getenv('DISCORD_TOKEN'))}")
        logger.info(f"Environment check - SPREADSHEET_ID set: {bool(os.getenv('SPREADSHEET_ID'))}")
        
        bot_thread = threading.Thread(target=run_bot, daemon=True, name="DiscordBotThread")
        bot_thread.start()
        logger.info(f"Bot thread started - Thread alive: {bot_thread.is_alive()}")
        
    except Exception as e:
        logger.error(f"Failed to start bot thread: {e}", exc_info=True)
        bot_status["error"] = f"Failed to start: {str(e)}"

def run_bot():
    """Run the Discord bot in a separate thread."""
    try:
        logger.info("=== Starting Discord bot thread ===")
        bot_status["startup_attempted"] = True
        bot_status["started"] = True
        
        # Import and run the bot
        logger.info("Importing bot module...")
        from main import bot, DISCORD_TOKEN
        
        if not DISCORD_TOKEN:
            raise ValueError("DISCORD_TOKEN not found in environment")
        
        logger.info("Discord token found, starting bot...")
        bot_status["running"] = True
        bot.run(DISCORD_TOKEN)
        
    except Exception as e:
        logger.error(f"Bot thread error: {e}", exc_info=True)
        bot_status["running"] = False
        bot_status["error"] = str(e)

@app.route('/')
def home():
    """Health check endpoint."""
    logger.info("Root endpoint accessed")
    return jsonify({
        "status": "ok",
        "service": "PraccReminder Discord Bot",
        "bot_running": bot_status["running"],
        "bot_started": bot_status["started"],
        "startup_attempted": bot_status["startup_attempted"],
        "error": bot_status["error"],
        "python_version": sys.version,
        "cwd": os.getcwd()
    })

@app.route('/health')
def health():
    """Health check for Azure."""
    logger.info("Health endpoint accessed")
    if bot_status["running"]:
        return jsonify({"status": "healthy", "bot_running": True}), 200
    elif bot_status["started"]:
        return jsonify({"status": "starting", "bot_running": False}), 200
    else:
        return jsonify({
            "status": "unhealthy",
            "error": bot_status["error"]
        }), 503

@app.route('/status')
def status():
    """Detailed status endpoint."""
    logger.info("Status endpoint accessed")
    return jsonify({
        "bot_status": bot_status,
        "environment": {
            "python_version": sys.version,
            "working_directory": os.getcwd(),
            "discord_token_set": bool(os.getenv("DISCORD_TOKEN")),
            "spreadsheet_id_set": bool(os.getenv("SPREADSHEET_ID")),
            "channel_id": os.getenv("CHANNEL_ID", "not set")
        }
    })

@app.before_request
def log_request():
    """Log all incoming requests and ensure bot is started."""
    ensure_bot_started()
    logger.info(f"Request: {request.method} {request.path} from {request.remote_addr}")

# Module initialization logging
logger.info("=== Webapp module loaded by gunicorn ===")
logger.info("Bot will start on first HTTP request")

if __name__ == '__main__':
    # This is only for local development
    logger.info("=== Running in development mode ===")
    
    # Start bot immediately in dev mode
    ensure_bot_started()
    
    # Get port from environment (Azure sets this)
    port = int(os.environ.get('PORT', 8000))
    
    logger.info(f"Starting Flask development server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

