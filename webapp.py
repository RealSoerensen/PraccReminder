"""
Flask wrapper for running the Discord bot on Azure Web App.
Azure Web Apps require an HTTP server, so this provides a minimal Flask app
while running the Discord bot in a background thread.
"""

from flask import Flask, jsonify
import threading
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Bot status
bot_status = {
    "running": False,
    "error": None
}

def run_bot():
    """Run the Discord bot in a separate thread."""
    try:
        logger.info("Starting Discord bot thread")
        bot_status["running"] = True
        
        # Import and run the bot
        from main import bot, DISCORD_TOKEN
        
        if not DISCORD_TOKEN:
            raise ValueError("DISCORD_TOKEN not found in environment")
        
        bot.run(DISCORD_TOKEN)
        
    except Exception as e:
        logger.error(f"Bot thread error: {e}", exc_info=True)
        bot_status["running"] = False
        bot_status["error"] = str(e)

@app.route('/')
def home():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "service": "PraccReminder Discord Bot",
        "bot_running": bot_status["running"],
        "error": bot_status["error"]
    })

@app.route('/health')
def health():
    """Health check for Azure."""
    if bot_status["running"]:
        return jsonify({"status": "healthy"}), 200
    else:
        return jsonify({
            "status": "unhealthy",
            "error": bot_status["error"]
        }), 503

@app.route('/status')
def status():
    """Detailed status endpoint."""
    return jsonify(bot_status)

if __name__ == '__main__':
    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Get port from environment (Azure sets this)
    port = int(os.environ.get('PORT', 8000))
    
    logger.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port)
