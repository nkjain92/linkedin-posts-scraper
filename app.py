import os
import logging
import sys
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from threading import Thread
import tempfile
import urllib.parse
from datetime import datetime
import json
import subprocess

# Import our LinkedIn scraper
from main import LinkedInScraperAgent, LinkedInScrapingResults

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management

# Store active scraping sessions
active_scrapers = {}
results_files = {}

@app.route('/')
def home():
    """Home page with scraper form"""
    return render_template('index.html')

@app.route('/start_scrape', methods=['POST'])
def start_scrape():
    """Start a LinkedIn scraping session"""
    try:
        # Get parameters from form
        profile_url = request.form.get('profile_url', '')
        max_posts = int(request.form.get('max_posts', 50))

        # Generate a unique session ID
        session_id = datetime.now().strftime("%Y%m%d%H%M%S")
        session['session_id'] = session_id

        # Check if Chrome/Edge debugger is already running
        browser_ws_endpoint = find_chrome_browser_endpoint()
        use_existing_browser = browser_ws_endpoint is not None

        # Initialize the scraper data
        active_scrapers[session_id] = {
            'status': 'initializing',
            'message': 'Starting LinkedIn scraper...',
            'progress': 0
        }

        # Launch scraper in a separate thread to not block the web server
        thread = Thread(target=run_scraper, args=(session_id, profile_url, max_posts, use_existing_browser, browser_ws_endpoint))
        thread.daemon = True
        thread.start()

        return redirect(url_for('scrape_status', session_id=session_id))

    except Exception as e:
        logger.error(f"Error starting scrape: {e}")
        return render_template('error.html', error=str(e))

@app.route('/scrape_status/<session_id>')
def scrape_status(session_id):
    """Show status page for scraping session"""
    if session_id not in active_scrapers:
        return render_template('error.html', error="Invalid session ID")

    return render_template('status.html',
                          session_id=session_id,
                          status=active_scrapers[session_id]['status'],
                          message=active_scrapers[session_id]['message'],
                          progress=active_scrapers[session_id]['progress'])

@app.route('/api/status/<session_id>')
def api_status(session_id):
    """API endpoint to get current scraping status"""
    if session_id not in active_scrapers:
        return jsonify({'error': 'Invalid session ID'}), 404

    return jsonify({
        'status': active_scrapers[session_id]['status'],
        'message': active_scrapers[session_id]['message'],
        'progress': active_scrapers[session_id]['progress']
    })

@app.route('/download/<session_id>')
def download_results(session_id):
    """Download the CSV results file"""
    if session_id not in results_files:
        return render_template('error.html', error="Results not available")

    return send_file(results_files[session_id],
                    mimetype='text/csv',
                    download_name=os.path.basename(results_files[session_id]),
                    as_attachment=True)

def find_chrome_browser_endpoint():
    """
    Try to find a Chrome/Edge browser debugging port
    Returns WebSocket endpoint if found, None otherwise
    """
    try:
        # Try common debugging ports
        ports = [9222, 9223, 9224]

        for port in ports:
            try:
                # Use curl to fetch browser debugging info
                result = subprocess.run(
                    ["curl", "-s", f"http://localhost:{port}/json/version"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )

                if result.returncode == 0 and result.stdout:
                    try:
                        data = json.loads(result.stdout)
                        if "webSocketDebuggerUrl" in data:
                            logger.info(f"Found browser debugging WebSocket at port {port}")
                            return data["webSocketDebuggerUrl"]
                    except json.JSONDecodeError:
                        continue
            except:
                pass

        logger.warning("Could not find an existing browser debugging session")
        return None
    except:
        return None

def run_scraper(session_id, profile_url, max_posts, use_existing_browser=False, browser_ws_endpoint=None):
    """Run the LinkedIn scraper in a background thread"""
    try:
        # Initialize the scraper
        scraper = LinkedInScraperAgent(use_existing_browser=use_existing_browser, browser_ws_endpoint=browser_ws_endpoint)
        active_scrapers[session_id]['scraper'] = scraper

        # Start the login process
        active_scrapers[session_id]['status'] = 'checking_login'
        active_scrapers[session_id]['message'] = 'Checking if already logged in to LinkedIn...'
        active_scrapers[session_id]['progress'] = 20

        if not scraper.login_to_linkedin():
            active_scrapers[session_id]['status'] = 'error'
            active_scrapers[session_id]['message'] = 'Failed to log in to LinkedIn.'
            return

        # Start scraping
        active_scrapers[session_id]['status'] = 'scraping'
        active_scrapers[session_id]['message'] = f'Scraping {max_posts} posts from {profile_url}...'
        active_scrapers[session_id]['progress'] = 30

        results = scraper.scrape_linkedin_profile(profile_url, max_posts)

        # Save results to CSV
        active_scrapers[session_id]['status'] = 'saving'
        active_scrapers[session_id]['message'] = 'Saving results to CSV file...'
        active_scrapers[session_id]['progress'] = 90

        csv_path = scraper.save_to_csv(results)

        # Finalize
        active_scrapers[session_id]['status'] = 'complete'
        active_scrapers[session_id]['message'] = f'Successfully saved {len(results.posts)} posts to CSV.'
        active_scrapers[session_id]['progress'] = 100
        results_files[session_id] = csv_path

    except Exception as e:
        logger.error(f"Error in scraper thread: {e}")
        active_scrapers[session_id]['status'] = 'error'
        active_scrapers[session_id]['message'] = f'Error: {str(e)}'

    finally:
        # Clean up
        if session_id in active_scrapers and 'scraper' in active_scrapers[session_id]:
            try:
                # Don't close the browser here - we'll keep it open for reuse
                pass
            except:
                pass

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)

    # Run the Flask app
    app.run(debug=True, port=5000)