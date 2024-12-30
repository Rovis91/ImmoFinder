"""
Browser management using Playwright for property scraping.
"""

import asyncio
from typing import Optional, List
import logging
from playwright.async_api import async_playwright, Browser, Page, Playwright
from .config import Config

logger = logging.getLogger(__name__)

class BrowserManager:
    """
    Manages browser instance and page interactions for scraping.
    """

    def __init__(self, config: Config):
        """
        Initialize the browser manager with configuration settings.

        Args:
            config (Config): Configuration object containing browser settings.
        """
        self.config = config
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._context = None

    async def _initialize_playwright(self) -> None:
        """
        Initialize the Playwright instance for browser management.
        """
        if not self._playwright:
            logger.debug("Initializing Playwright")
            self._playwright = await async_playwright().start()

    async def connect(self) -> None:
        """
        Start a new browser session and create a page context for interactions.

        Raises:
            RuntimeError: If Playwright initialization fails.
        """
        try:
            await self._initialize_playwright()
            if not self._playwright:
                raise RuntimeError("Failed to initialize Playwright")

            logger.info("Launching browser...")
            self._browser = await self._playwright.chromium.launch(
                headless=self.config.browser.headless
            )

            self._context = await self._browser.new_context(
                user_agent=self.config.browser.user_agent,
                viewport={
                    'width': self.config.browser.viewport_width,
                    'height': self.config.browser.viewport_height
                }
            )

            self._page = await self._context.new_page()
            self._page.set_default_timeout(self.config.browser.default_timeout)
            self._page.set_default_navigation_timeout(self.config.browser.navigation_timeout)

            logger.info("Browser launched successfully")
        except Exception as e:
            logger.error(f"Failed to launch browser: {str(e)}")
            await self.close()
            raise

    async def close(self) -> None:
        """
        Clean up browser resources, closing the browser, context, and page.
        """
        try:
            if self._page:
                await self._page.close()
                self._page = None

            if self._context:
                await self._context.close()
                self._context = None

            if self._browser:
                await self._browser.close()
                self._browser = None

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

            logger.info("Browser resources cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    async def get_properties(self, url: str, retry_count: int = 0) -> List[str]:
        """
        Fetch HTML content for property elements from a given URL.

        Args:
            url (str): The target URL to scrape.
            retry_count (int): Current retry attempt number (default: 0).

        Returns:
            List[str]: List of HTML strings for each property.

        Raises:
            RuntimeError: If the browser is not initialized.
            Exception: If all retries fail.
        """
        if not self._page:
            raise RuntimeError("Browser not initialized. Call connect() first.")

        html_elements = []

        try:
            logger.info(f"Navigating to {url}")
            await self._page.goto(url, wait_until='networkidle')
            await asyncio.sleep(5)

            property_list = await self._page.wait_for_selector(
                self.config.selectors.property_list,
                timeout=self.config.browser.default_timeout
            )

            if not property_list:
                logger.warning("Property list selector not found")
                return html_elements

            property_elements = await self._page.query_selector_all(
                self.config.selectors.property_item
            )

            for element in property_elements:
                html = await element.inner_html()
                if html:
                    html_elements.append(html)

            count = len(html_elements)
            logger.info(f"Found {count} properties for URL: {url}")
            return html_elements
        except Exception as e:
            logger.error(f"Error fetching properties from {url}: {str(e)}")
            if retry_count < self.config.scraping.max_retries:
                logger.info(f"Retrying ({retry_count + 1}/{self.config.scraping.max_retries})")
                await asyncio.sleep(self.config.scraping.retry_delay / 1000)
                return await self.get_properties(url, retry_count + 1)
            raise

    async def get_page_content(self, url: str) -> Optional[str]:
        """
        Retrieve the full HTML content of a page.

        Args:
            url (str): The target URL to fetch content from.

        Returns:
            Optional[str]: HTML content if successful, None otherwise.
        """
        try:
            await self._page.goto(
                url,
                wait_until='networkidle',
                timeout=self.config.browser.navigation_timeout
            )
            await asyncio.sleep(5)

            content = await self._page.content()
            logger.debug(f"Fetched content length: {len(content)}")

            if len(content) < 1000:
                logger.warning("Content seems too short, might be incomplete")
            elif "prices-summary" not in content:
                logger.warning("Expected content markers not found in page")

            return content
        except Exception as e:
            logger.error(f"Failed to get page content: {str(e)}")
            return None

    async def __aenter__(self):
        """
        Enter the async context manager, starting the browser session.

        Returns:
            BrowserManager: Instance of the browser manager.
        """
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the async context manager, cleaning up resources.
        """
        await self.close()
