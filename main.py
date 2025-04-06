import csv
import json
import logging
import re
import os
import sys
import time
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional
from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError

from pydantic import BaseModel

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Define the models for our LinkedIn posts
class LinkedInPost(BaseModel):
    """Model representing a LinkedIn post"""
    text: str
    date: str
    likes: Optional[int] = 0
    comments: Optional[int] = 0
    shares: Optional[int] = 0
    url: Optional[str] = None

class LinkedInScrapingResults(BaseModel):
    """Model for the scraping results"""
    profile_name: str
    profile_url: str
    posts: List[LinkedInPost]
    scrape_date: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

class LinkedInScraperAgent:
    def __init__(self, use_existing_browser: bool = False, browser_ws_endpoint: Optional[str] = None):
        """
        Initialize the LinkedIn Scraper Agent

        Args:
            use_existing_browser: Whether to connect to an existing browser
            browser_ws_endpoint: WebSocket endpoint to connect to an existing browser (Chrome DevTools Protocol)
        """
        logger.info("Initializing LinkedInScraperAgent")
        self.use_existing_browser = use_existing_browser
        self.browser_ws_endpoint = browser_ws_endpoint
        self.playwright = None
        self.browser = None
        self.page = None

    def _init_browser(self):
        """Initialize the browser"""
        self.playwright = sync_playwright().start()

        if self.use_existing_browser and self.browser_ws_endpoint:
            # Connect to existing browser using CDP
            logger.info(f"Connecting to existing browser at {self.browser_ws_endpoint}")
            self.browser = self.playwright.chromium.connect_over_cdp(self.browser_ws_endpoint)
        else:
            # Launch a new browser
            logger.info("Launching new browser")
            # Setting longer timeouts and additional browser options
            self.browser = self.playwright.chromium.launch(
                headless=False,
                slow_mo=100,  # Slow down operations by 100ms
                timeout=60000,  # 60 second timeout for browser launch
                args=[
                    '--disable-blink-features=AutomationControlled',  # Hide automation
                    '--no-sandbox',
                    '--start-maximized',
                    '--disable-extensions',
                    '--disable-default-apps',
                    '--disable-popup-blocking'
                ]
            )

    def _close_browser(self):
        """Close the browser"""
        if self.browser:
            try:
                self.browser.close()
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception as e:
                logger.error(f"Error stopping Playwright: {e}")

    def login_to_linkedin(self) -> bool:
        """
        Open LinkedIn and check if already logged in, otherwise allow manual login

        Returns:
            bool: True if login was successful or already logged in
        """
        try:
            if not self.browser:
                self._init_browser()

            # Create a new page with correct parameters - Browser.new_page() doesn't take timeout
            self.page = self.browser.new_page(
                viewport={"width": 1280, "height": 1024}
            )

            # Set the default page timeout
            self.page.set_default_timeout(90000)  # 90 seconds

            # First, try visiting LinkedIn main page to check if already logged in
            logger.info("Checking if already logged in to LinkedIn...")
            try:
                self.page.goto(
                    "https://www.linkedin.com/",
                    wait_until="domcontentloaded",  # Less strict than networkidle
                    timeout=60000  # 60 second timeout for navigation
                )
                # Wait a bit for content to load
                self.page.wait_for_timeout(3000)
            except TimeoutError:
                logger.warning("Timeout while checking login status, but continuing...")
                # We can continue as the page might have loaded enough to interact with

            # Check if already logged in
            if not self._check_login_required(self.page):
                logger.info("Already logged in to LinkedIn")
                return True

            # If not logged in, go to login page
            logger.info("Not logged in. Opening LinkedIn login page...")
            try:
                self.page.goto(
                    "https://www.linkedin.com/login",
                    wait_until="domcontentloaded",
                    timeout=60000
                )
            except TimeoutError:
                logger.warning("Timeout while loading login page, but continuing...")

            logger.info("Please log in to LinkedIn manually...")
            logger.info("The script will wait until you're logged in and redirected to your feed.")

            # Wait for navigation to feed page or timeout after 5 minutes
            try:
                # Listen for navigation to feed or home page
                self.page.wait_for_url(
                    "**/feed/**",
                    timeout=300000,  # 5 minutes timeout
                    wait_until="domcontentloaded"
                )
                logger.info("Successfully logged in to LinkedIn")
                return True
            except Exception as e:
                logger.error(f"Login timeout or error: {e}")

                # Check if we're on a LinkedIn page that indicates successful login
                if "linkedin.com" in self.page.url and not "/login" in self.page.url:
                    logger.info(f"You appear to be logged in to LinkedIn (current URL: {self.page.url})")
                    return True

                # Try waiting a bit longer and check again - the user might be in the process of logging in
                logger.info("Waiting a bit longer for login...")
                self.page.wait_for_timeout(30000)  # Wait 30 more seconds

                # Check one more time
                if not self._check_login_required(self.page):
                    logger.info("Successfully logged in to LinkedIn after waiting")
                    return True

                return False

        except Exception as e:
            logger.error(f"Error during login: {e}")
            logger.error(traceback.format_exc())
            return False

    def scrape_linkedin_profile(self, profile_url: str, max_posts: int = 50) -> LinkedInScrapingResults:
        """
        Scrape posts from a LinkedIn profile

        Args:
            profile_url: URL of the LinkedIn profile to scrape
            max_posts: Maximum number of posts to scrape (default: 50)

        Returns:
            LinkedInScrapingResults object containing the scraped posts
        """
        logger.info(f"Starting scraping of LinkedIn profile: {profile_url}")

        try:
            if not self.browser:
                self._init_browser()

            if not self.page:
                self.page = self.browser.new_page(
                    viewport={"width": 1280, "height": 1024}
                )
                self.page.set_default_timeout(90000)  # 90 seconds

            # First get the profile name by visiting the main profile page
            logger.info(f"Navigating to profile page to get basic info: {profile_url}")
            try:
                self.page.goto(
                    profile_url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )
                # Wait a bit for content to load
                self.page.wait_for_timeout(5000)

            except TimeoutError as e:
                logger.warning(f"Timeout while navigating to profile, but continuing: {e}")

            # Check if login is required
            if self._check_login_required(self.page):
                logger.warning("LinkedIn login required")
                if not self.login_to_linkedin():
                    return LinkedInScrapingResults(
                        profile_name="Login Failed",
                        profile_url=profile_url,
                        posts=[
                            LinkedInPost(
                                text="LinkedIn login failed. Please try again.",
                                date=datetime.now().strftime("%Y-%m-%d"),
                            )
                        ]
                    )

                # After login, navigate back to the profile
                logger.info(f"Navigating back to {profile_url}")
                try:
                    self.page.goto(
                        profile_url,
                        wait_until="domcontentloaded",
                        timeout=60000
                    )
                    # Wait a bit for content to load
                    self.page.wait_for_timeout(5000)

                except TimeoutError as e:
                    logger.warning(f"Timeout while navigating back to profile, but continuing: {e}")

            # Take a screenshot of the profile page
            screenshot_path = f"linkedin_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            try:
                self.page.screenshot(path=screenshot_path)
                logger.info(f"Profile page screenshot saved to {screenshot_path}")
            except Exception as e:
                logger.warning(f"Failed to take screenshot: {e}")

            # Extract profile name
            profile_name = self._extract_profile_name(self.page)
            logger.info(f"Profile name: {profile_name}")

            # Extract posts using different strategies
            posts = []

            # Strategy 1: Try to navigate to the activity/posts tab
            if self._navigate_to_posts_tab(self.page):
                logger.info("Successfully navigated to posts/activity tab")
                activity_posts = self._extract_posts(self.page, max_posts)
                posts.extend(activity_posts)
                logger.info(f"Extracted {len(activity_posts)} posts from activity tab")

            # Strategy 2: If we didn't get enough posts, try direct activity URL
            if len(posts) < max_posts:
                try:
                    username = re.search(r'linkedin\.com/in/([^/]+)', profile_url)
                    if username:
                        username = username.group(1)
                        activity_url = f"https://www.linkedin.com/in/{username}/recent-activity/all/"
                        logger.info(f"Trying direct activity URL: {activity_url}")

                        self.page.goto(activity_url, wait_until="domcontentloaded", timeout=60000)
                        self.page.wait_for_timeout(5000)

                        direct_posts = self._extract_posts(self.page, max_posts - len(posts))

                        # Add new posts, avoiding duplicates
                        for post in direct_posts:
                            if post.text not in [p.text for p in posts]:
                                posts.append(post)

                        logger.info(f"Extracted {len(direct_posts)} posts from direct activity URL")
                except Exception as e:
                    logger.warning(f"Error with direct activity URL: {e}")

            # Strategy 3: If we still don't have enough posts, try the main feed
            if len(posts) < max_posts:
                try:
                    logger.info("Trying main feed as last resort")
                    self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
                    self.page.wait_for_timeout(5000)

                    # Try to search for the profile name in the search box
                    search_box = self.page.query_selector('input[placeholder*="Search"], input[aria-label*="Search"]')
                    if search_box and profile_name and profile_name != "Unknown Profile":
                        logger.info(f"Searching for: {profile_name}")
                        search_box.fill(profile_name)
                        search_box.press("Enter")
                        self.page.wait_for_timeout(5000)

                    feed_posts = self._extract_posts(self.page, max_posts - len(posts))

                    # Filter posts by author if possible
                    filtered_posts = []
                    for post in feed_posts:
                        # Only add posts we think are from the target profile
                        # This is imperfect but better than nothing
                        if profile_name in post.text:
                            if post.text not in [p.text for p in posts]:
                                filtered_posts.append(post)

                    posts.extend(filtered_posts)
                    logger.info(f"Added {len(filtered_posts)} posts from main feed")

                except Exception as e:
                    logger.warning(f"Error with main feed search: {e}")

            # Create result with whatever posts we found
            logger.info(f"Total posts found: {len(posts)}")
            result = LinkedInScrapingResults(
                profile_name=profile_name,
                profile_url=profile_url,
                posts=posts[:max_posts]  # Limit to max_posts
            )

            return result

        except Exception as e:
            logger.error(f"Error scraping LinkedIn profile: {e}")
            logger.error(traceback.format_exc())
            return LinkedInScrapingResults(
                profile_name="Error",
                profile_url=profile_url,
                posts=[
                    LinkedInPost(
                        text=f"Error scraping LinkedIn profile: {str(e)}",
                        date=datetime.now().strftime("%Y-%m-%d"),
                    )
                ]
            )

    def _check_login_required(self, page: Page) -> bool:
        """Check if login is required"""
        try:
            # Look for login button or form
            login_elements = page.query_selector_all('a[href*="login"], form[action*="login"]')
            signin_text = page.query_selector_all('text="Sign in"')
            join_now_text = page.query_selector_all('text="Join now"')

            # If the profile has limited visibility or shows a login wall
            limited_view = page.query_selector_all('.profile-unavailable, .guest-view')

            # Check URL for login page
            is_login_page = "login" in page.url or "signup" in page.url

            # Check if we're getting redirected to home page without being logged in
            is_home_page_with_guest_view = page.url == "https://www.linkedin.com/" and \
                                         (len(signin_text) > 0 or len(join_now_text) > 0)

            return len(login_elements) > 0 or \
                   len(signin_text) > 0 or \
                   len(join_now_text) > 0 or \
                   len(limited_view) > 0 or \
                   is_login_page or \
                   is_home_page_with_guest_view
        except Exception as e:
            logger.error(f"Error checking if login is required: {e}")
            return True  # Assume login is required if we can't check

    def _extract_profile_name(self, page: Page) -> str:
        """Extract the profile name"""
        try:
            # Try different selectors for the profile name
            name_selectors = [
                'h1.text-heading-xlarge',
                'h1.pv-top-card-section__name',
                'h1.pv-text-details__title',
                '.profile-card-one-to-one__container h1',
                '.ph5 h1',
                'h1'  # Any h1 as last resort
            ]

            for selector in name_selectors:
                try:
                    name_element = page.query_selector(selector)
                    if name_element:
                        name = name_element.inner_text().strip()
                        if name:
                            return name
                except Exception as e:
                    logger.warning(f"Error with selector {selector}: {e}")
                    continue

            # Fallback: Look for any text that might be a name
            try:
                title_element = page.query_selector('title')
                if title_element:
                    title = title_element.inner_text()
                    if " | LinkedIn" in title:
                        return title.split(" | LinkedIn")[0].strip()
            except Exception:
                pass

            return "Unknown Profile"
        except Exception as e:
            logger.error(f"Error extracting profile name: {e}")
            return "Unknown Profile"

    def _navigate_to_posts_tab(self, page: Page) -> bool:
        """Navigate to the posts/activity tab if available"""
        try:
            # Try different ways to navigate to posts
            tabs = [
                'a[href*="recent-activity/shares"]',
                'a[href*="recent-activity/posts"]',
                'a[href*="detail/recent-activity"]',
                'a:has-text("Activity")',
                'a:has-text("Posts")',
                'a:has-text("Articles")',
                'nav a:has-text("Activity")'
            ]

            for tab in tabs:
                try:
                    tab_element = page.query_selector(tab)
                    if tab_element:
                        logger.info(f"Clicking tab: {tab}")
                        tab_element.click()
                        page.wait_for_timeout(5000)  # Wait 5 seconds

                        # Take a screenshot after tab click
                        screenshot_path = f"linkedin_tab_clicked_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                        try:
                            page.screenshot(path=screenshot_path)
                            logger.info(f"Tab click screenshot saved to {screenshot_path}")
                        except Exception as e:
                            logger.warning(f"Failed to take tab click screenshot: {e}")

                        return True
                except Exception as e:
                    logger.warning(f"Error clicking tab {tab}: {e}")
                    continue

            # If we can't find a tab, try going directly to recent-activity URL
            try:
                current_url = page.url
                username = ""

                # Extract username from URL
                match = re.search(r'linkedin\.com/in/([^/]+)', current_url)
                if match:
                    username = match.group(1)
                    activity_url = f"https://www.linkedin.com/in/{username}/recent-activity/all/"
                    logger.info(f"Trying direct navigation to activity URL: {activity_url}")

                    page.goto(activity_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(5000)  # Wait 5 seconds

                    # Take screenshot after direct navigation
                    screenshot_path = f"linkedin_direct_activity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    page.screenshot(path=screenshot_path)
                    logger.info(f"Direct activity navigation screenshot saved to {screenshot_path}")

                    return True
            except Exception as e:
                logger.warning(f"Error navigating directly to activity URL: {e}")

            # As a fallback, try checking the whole feed
            try:
                logger.info("Trying to access main feed as fallback")
                page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)

                # Take screenshot after feed navigation
                screenshot_path = f"linkedin_feed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                page.screenshot(path=screenshot_path)
                logger.info(f"Feed navigation screenshot saved to {screenshot_path}")

                # Attempt to search for the person's name to filter the feed
                search_box = page.query_selector('input[placeholder*="Search"], input[aria-label*="Search"]')
                if search_box:
                    profile_name = self._extract_profile_name(page)
                    if profile_name and profile_name != "Unknown Profile":
                        logger.info(f"Searching for posts by: {profile_name}")
                        search_box.fill(profile_name)
                        search_box.press("Enter")
                        page.wait_for_timeout(5000)

                return True
            except Exception as e:
                logger.warning(f"Error accessing main feed: {e}")

            logger.warning("Could not find activity/posts tab")
            return False

        except Exception as e:
            logger.error(f"Error navigating to posts tab: {e}")
            return False

    def _extract_posts(self, page: Page, max_posts: int) -> List[LinkedInPost]:
        """
        Extract posts from the profile page

        Args:
            page: Playwright page object
            max_posts: Maximum number of posts to extract

        Returns:
            List of LinkedInPost objects
        """
        posts = []

        try:
            # Scroll down to load more posts
            last_height = page.evaluate('document.body.scrollHeight')
            post_count = 0
            scroll_count = 0
            max_scrolls = 20  # Limit scrolling attempts

            while post_count < max_posts and scroll_count < max_scrolls:
                # Scroll down
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                page.wait_for_timeout(2000)  # Wait for posts to load

                # Check if we've reached the bottom
                new_height = page.evaluate('document.body.scrollHeight')
                if new_height == last_height:
                    scroll_count += 1
                    if scroll_count >= 3:  # If we've been at the same height for 3 scrolls, break
                        break
                else:
                    scroll_count = 0  # Reset scroll count if height changed

                last_height = new_height

                # Extract posts after each scroll
                current_posts = self._extract_current_posts(page)
                for post in current_posts:
                    if post.text not in [p.text for p in posts]:  # Avoid duplicates
                        posts.append(post)

                post_count = len(posts)
                logger.info(f"Found {post_count} posts after scroll {scroll_count+1}")

                # Take a screenshot after scrolling
                if scroll_count % 5 == 0:  # Every 5 scrolls
                    screenshot_path = f"linkedin_scroll_{scroll_count}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    try:
                        page.screenshot(path=screenshot_path)
                        logger.info(f"Scroll screenshot saved to {screenshot_path}")
                    except Exception as e:
                        logger.warning(f"Failed to take scroll screenshot: {e}")

            # Cut down to max_posts if we found more
            result_posts = posts[:max_posts]
            return result_posts

        except Exception as e:
            logger.error(f"Error extracting posts: {e}")
            logger.error(traceback.format_exc())
            return []

    def _extract_current_posts(self, page: Page) -> List[LinkedInPost]:
        """Extract currently visible posts from the page"""
        posts = []

        # Various selectors for posts, trying to be comprehensive
        post_selectors = [
            '.update-components-actor',  # New LinkedIn UI
            '.feed-shared-update-v2',    # Main feed posts
            '.occludable-update',        # Activity posts
            '.profile-activity-card',    # Profile activity
            '.artdeco-card',             # General cards
            '.activity-card',            # Activity cards
            'div[data-urn]'              # Posts with data-urn attribute
        ]

        for selector in post_selectors:
            try:
                post_elements = page.query_selector_all(selector)
                logger.info(f"Found {len(post_elements)} elements with selector '{selector}'")

                for element in post_elements:
                    try:
                        # First, try to click any "see more" buttons to expand truncated posts
                        see_more_selectors = [
                            'button:has-text("see more")',
                            'button:has-text("See more")',
                            'button:has-text("...more")',
                            'button:has-text("Read more")',
                            'span:has-text("see more")',
                            'span:has-text("See more")',
                            'span:has-text("...more")',
                            'span:has-text("Read more")',
                            'a:has-text("see more")',
                            'a:has-text("See more")',
                            'a:has-text("...more")',
                            'a:has-text("Read more")'
                        ]

                        for see_more_selector in see_more_selectors:
                            try:
                                see_more_buttons = element.query_selector_all(see_more_selector)
                                for see_more_button in see_more_buttons:
                                    try:
                                        see_more_button.click()
                                        # Wait briefly for content to expand
                                        page.wait_for_timeout(500)
                                        logger.info("Expanded 'see more' content in post")
                                    except Exception as e:
                                        logger.debug(f"Could not click see more button: {e}")
                            except Exception:
                                continue

                        # Extract post text using different approaches
                        post_text = ""

                        # Approach 1: Try to get all paragraphs at once for multi-paragraph posts
                        paragraph_containers = [
                            '.feed-shared-update-v2__description',
                            '.feed-shared-text',
                            '.update-components-text',
                            '.feed-shared-update__description',
                            '.update-components-update-content',
                            '.activity-card__content'
                        ]

                        for container_selector in paragraph_containers:
                            try:
                                container = element.query_selector(container_selector)
                                if container:
                                    # Get all paragraphs within the container
                                    paragraphs = container.query_selector_all('p, span.break-words, div.break-words')
                                    if paragraphs and len(paragraphs) > 0:
                                        full_text = []
                                        for para in paragraphs:
                                            para_text = para.inner_text().strip()
                                            if para_text and not para_text.startswith("Translate") and not "...more" in para_text:
                                                full_text.append(para_text)

                                        if full_text:
                                            combined_text = "\n\n".join(full_text)
                                            if len(combined_text) > len(post_text):
                                                post_text = combined_text
                            except Exception as e:
                                logger.debug(f"Error extracting paragraphs: {e}")
                                continue

                        # Approach 2: If no paragraphs found, try fallback selectors for single text block
                        if not post_text:
                            text_selectors = [
                                '.feed-shared-update-v2__description',
                                '.feed-shared-text',
                                '.update-components-text',
                                '.feed-shared-update__description',
                                '.update-components-update-content',
                                '.update-components-text span',
                                '.activity-card__content',
                                'p, span'  # Any paragraph or span as last resort
                            ]

                            for text_selector in text_selectors:
                                try:
                                    text_elements = element.query_selector_all(text_selector)
                                    for text_element in text_elements:
                                        content = text_element.inner_text().strip()
                                        if content and len(content) > 5 and not content.startswith("Translate"):  # At least 5 chars to be a valid post
                                            if len(content) > len(post_text) and not "...more" in content:
                                                post_text = content  # Keep the longest text we find
                                except Exception:
                                    continue

                        if not post_text:
                            continue  # Skip posts without text

                        # Extract date
                        date_selectors = [
                            '.feed-shared-actor__sub-description',
                            '.feed-shared-time-ago',
                            '.update-components-actor__sub-description',
                            'time',
                            '.activity-card__date',
                            'span:has-text("ago")'  # Any span with "ago" text
                        ]

                        post_date = "Unknown date"
                        for date_selector in date_selectors:
                            try:
                                date_element = element.query_selector(date_selector)
                                if date_element:
                                    date_text = date_element.inner_text().strip()
                                    if date_text and ("ago" in date_text or "day" in date_text or "week" in date_text or "month" in date_text):
                                        post_date = date_text
                                        break
                            except Exception:
                                continue

                        # Extract engagement metrics
                        likes = 0
                        comments = 0
                        shares = 0

                        # Try to get likes
                        likes_selectors = [
                            '.social-details-social-counts__reactions-count',
                            'span[data-test-id="social-actions__reaction-count"]',
                            'button[aria-label*="reactions"]',
                            'span:has-text("Like")'
                        ]

                        for likes_selector in likes_selectors:
                            try:
                                likes_element = element.query_selector(likes_selector)
                                if likes_element:
                                    likes_text = likes_element.inner_text().strip()
                                    likes = self._parse_count(likes_text)
                                    break
                            except Exception:
                                continue

                        # Create post object
                        post = LinkedInPost(
                            text=post_text,
                            date=post_date,
                            likes=likes,
                            comments=comments,
                            shares=shares
                        )

                        posts.append(post)

                    except Exception as e:
                        logger.error(f"Error processing post element: {e}")
            except Exception as e:
                logger.error(f"Error with selector '{selector}': {e}")

        return posts

    def _parse_count(self, count_text: str) -> int:
        """Parse count from text like '1K', '2,3K', etc."""
        try:
            # Extract numbers using regex
            match = re.search(r'(\d+(?:[,.]\d+)?)\s*([KkMm])?', count_text)
            if not match:
                return 0

            number = match.group(1).replace(',', '.')
            multiplier = match.group(2).upper() if match.group(2) else ''

            value = float(number)
            if multiplier == 'K':
                value *= 1000
            elif multiplier == 'M':
                value *= 1000000

            return int(value)
        except:
            return 0

    def save_to_csv(self, data: LinkedInScrapingResults, output_file: Optional[str] = None) -> str:
        """
        Save the scraped data to a CSV file

        Args:
            data: LinkedInScrapingResults object containing the scraped posts
            output_file: Optional file path for the CSV output

        Returns:
            Path to the saved CSV file
        """
        # Generate default filename if not provided
        if not output_file:
            profile_name = data.profile_name.replace(" ", "_").replace("/", "_")
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"linkedin_posts_{profile_name}_{date_str}.csv"

        logger.info(f"Saving data to CSV file: {output_file}")

        # Write data to CSV
        try:
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                # Use custom quoting to ensure multi-line text is properly escaped
                csv_writer = csv.writer(
                    csvfile,
                    quoting=csv.QUOTE_ALL,  # Quote all fields
                    doublequote=True,       # Use double quotes to escape quotes
                    escapechar='\\',        # Use backslash as escape character
                    lineterminator='\n'     # Consistent line termination
                )

                # Write header information
                csv_writer.writerow(["Profile Name", "Profile URL", "Scrape Date"])
                csv_writer.writerow([data.profile_name, data.profile_url, data.scrape_date])
                csv_writer.writerow([])  # Empty row for separation

                # Write posts header
                csv_writer.writerow(["Post Text", "Date", "Likes", "Comments", "Shares", "URL"])

                # Write each post - ensure post.text is properly formatted for multi-paragraph content
                for post in data.posts:
                    # Clean up the post text - remove any trailing "...more" or "see more" text
                    clean_text = post.text
                    if clean_text.endswith("...more") or clean_text.endswith("see more") or clean_text.endswith("See more"):
                        clean_text = clean_text[:-7]  # Remove the trailing text

                    csv_writer.writerow([
                        clean_text,  # This will properly preserve newlines and quotes in CSV
                        post.date,
                        post.likes,
                        post.comments,
                        post.shares,
                        post.url
                    ])

                logger.info(f"Successfully saved {len(data.posts)} posts to CSV")
                return output_file

        except Exception as e:
            logger.error(f"Error saving to CSV: {e}")
            logger.error(traceback.format_exc())
            raise

def find_chrome_browser_endpoint():
    """
    Try to find a Chrome/Chromium browser debugging port
    Returns WebSocket endpoint if found, None otherwise
    """
    import subprocess
    import json

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
                    data = json.loads(result.stdout)
                    if "webSocketDebuggerUrl" in data:
                        logger.info(f"Found browser debugging WebSocket at port {port}")
                        return data["webSocketDebuggerUrl"]
            except:
                pass

        logger.warning("Could not find an existing browser debugging session")
        return None
    except:
        return None

def main():
    try:
        logger.info("Starting LinkedIn scraper...")

        # Initialize the LinkedIn scraper agent
        scraper = LinkedInScraperAgent()

        # Login to LinkedIn first
        logger.info("Starting the LinkedIn login process...")
        if not scraper.login_to_linkedin():
            logger.error("Failed to log in to LinkedIn. Exiting.")
            return

        logger.info("Successfully logged in to LinkedIn!")

        # Get LinkedIn profile URL from user input or use the default one
        default_url = "https://www.linkedin.com/in/deepak-garg-4204b439/"
        profile_url = input(f"Enter LinkedIn profile URL (press Enter for default: {default_url}): ") or default_url

        # Set the maximum number of posts to scrape
        max_posts = int(input("Enter maximum number of posts to scrape (default: 50): ") or "50")

        try:
            # Scrape the LinkedIn profile
            logger.info(f"Scraping {max_posts} posts from {profile_url}...")
            results = scraper.scrape_linkedin_profile(profile_url, max_posts)

            # Save the results to CSV
            logger.info("Saving results to CSV file...")
            csv_path = scraper.save_to_csv(results)

            logger.info(f"Successfully saved {len(results.posts)} posts to CSV file:")
            logger.info(f"File saved at: {csv_path}")

        except Exception as e:
            logger.error(f"Error during scraping or saving: {e}")
            logger.error(traceback.format_exc())

    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    main()