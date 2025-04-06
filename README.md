# LinkedIn Profile Post Scraper

A web application that allows you to scrape and extract posts from LinkedIn profiles. This tool provides a user-friendly interface and supports manual login for accounts with two-factor authentication (2FA).

## Features

- Web-based interface for easy usage
- Opens LinkedIn in a new tab of the same browser
- Detects if you're already logged in to LinkedIn
- Extracts complete post content (fixes truncation issues with "...see more")
- Supports manual login with 2FA if needed
- Exports results to CSV with proper formatting
- Shows real-time progress updates
- Works with various LinkedIn profile layouts

## Setup Instructions

### 1. Install Python Requirements

```bash
pip install -r requirements.txt
```

### 2. Install Playwright Browsers

```bash
playwright install chromium
```

### 3. Start Your Browser with Remote Debugging (Optional but recommended)

For the best experience (using your current browser with existing LinkedIn sessions), start your browser with remote debugging enabled:

#### Windows

**Chrome:**

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

**Edge:**

```
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222
```

#### macOS

**Chrome:**

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
```

**Edge:**

```bash
/Applications/Microsoft\ Edge.app/Contents/MacOS/Microsoft\ Edge --remote-debugging-port=9222
```

#### Linux

**Chrome:**

```bash
google-chrome --remote-debugging-port=9222
```

**Edge:**

```bash
microsoft-edge --remote-debugging-port=9222
```

### 4. Run the Application

```bash
python app.py
```

The web interface will be available at http://127.0.0.1:5000/

## Usage Guide

1. Navigate to http://127.0.0.1:5000/ in your web browser
2. Enter the LinkedIn profile URL you want to scrape
3. Specify the maximum number of posts to extract
4. Click "Start Scraping"
5. LinkedIn will open in a new tab of your browser
6. If you're already logged in to LinkedIn, scraping will begin automatically
7. If not logged in, you'll need to log in first (supports two-factor authentication)
8. The scraper will automatically navigate to the profile and extract posts
9. You'll see progress updates in real-time
10. When completed, you can download the results as a CSV file

## CSV Format

The CSV output includes:

- Profile information (name, URL, scrape date)
- Post text (full content, including multi-paragraph posts)
- Post date
- Engagement metrics (likes, comments, shares where available)

## Troubleshooting

- If the login process fails, make sure you're using valid LinkedIn credentials
- If posts are not being found, check if the profile has public posts or if you have permission to view them
- If scraping stops midway, LinkedIn might be rate-limiting your account - try again later
- For the best experience, start your browser with remote debugging enabled before running the application

### Common Issues

1. **Cannot connect to browser**: Make sure your browser is running with remote debugging enabled on port 9222
2. **Browser launches new window instead of tab**: This happens when the application can't connect to an existing browser with remote debugging enabled
3. **Permission issues**: Some browsers require you to run them with specific flags for security reasons
4. **"No such file or directory" error on macOS**: Make sure the path to your browser executable is correct

## Technical Details

The application uses:

- Flask for the web interface
- Playwright for browser automation
- Pydantic for data modeling
- Bootstrap for the frontend UI
