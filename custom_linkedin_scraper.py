"""
A lightweight Selenium-based LinkedIn job scraper.

Compatible with the existing scraper.py workflow:
    from linkedin_scraper import LinkedinScraper
    from linkedin_scraper import Events, EventData, EventBegin
    from linkedin_scraper import Query, QueryOptions

This module uses a persistent Chrome profile for login. It does not read,
export, or store LinkedIn passwords or cookies outside that profile.
"""

# Import dataclass support for simple event and query objects.
from dataclasses import dataclass, field

# Import event enumeration support.
from enum import Enum

# Import logging for the existing pagination monitor.
import logging

# Import filesystem helpers for the Chrome profile.
from pathlib import Path

# Import regular expressions for job IDs and text cleanup.
import re

# Import timing helpers for waits and pacing.
import time

# Import URL helpers for normalising job links.
from urllib.parse import urljoin, urlparse, parse_qs

# Import Selenium browser controls.
from selenium import webdriver

# Import Chrome launch options.
from selenium.webdriver.chrome.options import Options

# Import Selenium selectors.
from selenium.webdriver.common.by import By

# Import explicit wait support.
from selenium.webdriver.support.ui import WebDriverWait

# Import expected Selenium conditions.
from selenium.webdriver.support import expected_conditions as EC

# Import Selenium exceptions used during dynamic page loading.
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    WebDriverException,
)


# Keep the logger name compatible with the existing scraper.py monitor.
logger = logging.getLogger("li:scraper")


# Define the events supported by the existing callbacks.
class Events(Enum):
    BEGIN = "begin"
    DATA = "data"
    ERROR = "error"
    END = "end"


# Store the approximate number of results announced at search start.
@dataclass
class EventBegin:
    job_total: int = 0


# Store the fields consumed by the existing SQLite callback.
@dataclass
class EventData:
    link: str = ""
    title: str = ""
    company: str = ""
    place: str = ""
    date_text: str = ""
    description: str = ""
    company_link: str = ""
    insights: list = field(default_factory=list)


# Store a LinkedIn search URL and its options.
@dataclass
class Query:
    url: str
    options: object = None


# Store the maximum number of jobs to collect.
@dataclass
class QueryOptions:
    limit: int = 25


# Define the scraper with a compatible constructor and callback interface.
class LinkedinScraper:

    # Initialise browser settings and event listeners.
    def __init__(
        self,
        chrome_executable_path=None,
        chrome_binary_location=None,
        chrome_options=None,
        headless=False,
        max_workers=1,
        slow_mo=0.8,
        adaptive_slow_mo=True,
        page_load_timeout=40,
        user_data_dir=None,
        interactive_login=True,
    ):
        # Keep the optional ChromeDriver executable path.
        self.chrome_executable_path = chrome_executable_path

        # Keep the optional Chrome binary path.
        self.chrome_binary_location = chrome_binary_location

        # Keep caller-supplied Chrome options when provided.
        self.chrome_options = chrome_options

        # Force visible mode for manual login and reliable inspection.
        self.headless = False

        # Keep one browser because one profile cannot be shared safely.
        self.max_workers = 1

        # Enforce a sensible minimum delay between job extractions.
        self.slow_mo = max(float(slow_mo), 0.5)

        # Keep the adaptive pacing setting for interface compatibility.
        self.adaptive_slow_mo = adaptive_slow_mo

        # Keep the page load timeout.
        self.page_load_timeout = page_load_timeout

        # Use the supplied persistent profile directory.
        self.user_data_dir = user_data_dir

        # Keep the login setting for interface compatibility.
        self.interactive_login = interactive_login

        # Start without a browser.
        self.driver = None

        # Create an empty callback registry.
        self.listeners = {event: [] for event in Events}

    # Register a callback for an event.
    def on(self, event, callback, once=False):
        # Reject unknown event types.
        if event not in self.listeners:
            raise ValueError(f"Unknown scraper event: {event}")

        # Store the callback and its one-shot setting.
        self.listeners[event].append((callback, once))

    # Execute callbacks registered for an event.
    def emit(self, event, *args):
        # Iterate over a copy to allow callback changes.
        for callback, once in list(self.listeners[event]):
            # Call the listener with the supplied event data.
            callback(*args)

            # Remove one-shot callbacks after successful execution.
            if once:
                self.listeners[event].remove((callback, once))

    # Build Chrome options without changing the user's normal profile.
    def _build_options(self):
        # Reuse explicitly supplied options when available.
        options = self.chrome_options or Options()

        # Keep the browser visible for manual authentication.
        options.headless = False

        # Set the Chrome binary only when explicitly configured.
        if self.chrome_binary_location:
            options.binary_location = self.chrome_binary_location

        # Create and attach a dedicated persistent profile directory.
        if self.user_data_dir:
            profile_path = Path(self.user_data_dir).expanduser()
            profile_path.mkdir(parents=True, exist_ok=True)
            options.add_argument(f"--user-data-dir={profile_path.resolve()}")

        # Add conservative launch arguments.
        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")

        # Return the configured options.
        return options

    # Start Chrome only when a search needs it.
    def _start_browser(self):
        # Reuse the existing browser between searches.
        if self.driver is not None:
            try:
                self.driver.current_url
                return
            except WebDriverException:
                self.driver = None

        # Build the Chrome launch options.
        options = self._build_options()

        # Use an explicitly supplied ChromeDriver when configured.
        if self.chrome_executable_path:
            service = webdriver.chrome.service.Service(
                executable_path=self.chrome_executable_path
            )
            self.driver = webdriver.Chrome(service=service, options=options)
        else:
            # Let Selenium Manager locate a compatible ChromeDriver.
            self.driver = webdriver.Chrome(options=options)

        # Set the maximum navigation wait.
        self.driver.set_page_load_timeout(self.page_load_timeout)

        # Allow the browser to settle after launch.
        time.sleep(2)

    # Wait for the user to sign in manually when necessary.
    def _ensure_login(self):
        # Check the current page without visiting the LinkedIn homepage.
        current_url = self.driver.current_url.lower()
        login_required = (
            "/login" in current_url
            or "/checkpoint/" in current_url
            or "/authwall" in current_url
        )

        # Ask for manual login only when LinkedIn requires it.
        if login_required:
            print("\nLinkedIn requires you to sign in.")
            print("Please log in in the opened Chrome window.")
            print("The scraper will continue once the jobs page is accessible.\n")

            # Wait up to ten minutes for the user to complete login.
            deadline = time.time() + 600

            # Check the browser until authentication succeeds or times out.
            while time.time() < deadline:
                current_url = self.driver.current_url.lower()

                # Treat the absence of sign-in redirects as a successful login.
                if not any(
                    marker in current_url
                    for marker in ("/login", "/checkpoint/", "/authwall")
                ):
                    return

                # Poll at a gentle interval.
                time.sleep(2)

            # Stop clearly if login did not complete.
            raise TimeoutException("Timed out waiting for LinkedIn login.")

    # Read text from the first matching selector.
    def _text(self, parent, selectors):
        # Try selectors in priority order.
        for selector in selectors:
            try:
                # Find the first matching element.
                element = parent.find_element(By.CSS_SELECTOR, selector)

                # Return cleaned text when present.
                value = element.text.strip()
                if value:
                    return value
            except Exception:
                # Continue when a selector is absent.
                pass

        # Return an empty string when nothing matches.
        return ""

    # Read an attribute from the first matching selector.
    def _attribute(self, parent, selectors, attribute):
        # Try selectors in priority order.
        for selector in selectors:
            try:
                # Find the first matching element.
                element = parent.find_element(By.CSS_SELECTOR, selector)

                # Return the requested attribute when present.
                value = element.get_attribute(attribute)
                if value:
                    return value
            except Exception:
                # Continue when a selector is absent.
                pass

        # Return an empty string when nothing matches.
        return ""

    # Extract a LinkedIn job ID from a job URL.
    def _job_id(self, link):
        # Match the numeric ID in standard LinkedIn job URLs.
        match = re.search(r"/jobs/view/(\d+)", link or "")

        # Return the ID or an empty value.
        return match.group(1) if match else ""

    # Find fresh job cards, retrying after LinkedIn rerenders.
    def _find_cards(self):
        # Retry briefly when LinkedIn replaces the results column.
        for attempt in range(3):
            try:
                # Locate LinkedIn's semantic results container.
                containers = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    '[data-testid="lazy-column"][data-component-type="LazyColumn"][componentkey="SearchResultsMainContent"]',
                )

                # Find cards using their stable component-key prefix.
                for container in containers:
                    try:
                        # Read the currently attached job-card elements.
                        cards = container.find_elements(
                            By.CSS_SELECTOR,
                            '[role="button"][componentkey^="job-card-component-ref-"]',
                        )
                        if cards:
                            return cards
                    except StaleElementReferenceException:
                        # Retry after LinkedIn replaces this container.
                        break

                # Check legacy structures when the modern list is absent.
                selectors = [
                    "li[data-occludable-job-id]",
                    "li.jobs-search-results__list-item",
                    "div.job-card-job-posting-card-wrapper",
                    "div.job-card-container",
                    "[data-job-id]",
                ]
                for selector in selectors:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        return elements

                # Return an empty list when no cards are present.
                return []
            except StaleElementReferenceException:
                # Wait briefly before querying the new page structure.
                time.sleep(0.3)

        # Return no cards after repeated page rerenders.
        return []

    # Extract a job URL from a result card.
    def _card_link(self, card):
        # Read a conventional job URL when available.
        link = self._attribute(
            card,
            [
                "a.job-card-list__title--link",
                "a.job-card-container__link",
                "a[data-control-name='job_card_title']",
                "a[href*='/jobs/view/']",
            ],
            "href",
        )

        # Resolve conventional URLs against LinkedIn.
        if link:
            return urljoin("https://www.linkedin.com", link)

        # Extract the job ID from LinkedIn's current card component key.
        component_key = card.get_attribute("componentkey") or ""
        match = re.search(r"job-card-component-ref-(\d+)", component_key)

        # Construct the standard job URL from the component key.
        if match:
            return f"https://www.linkedin.com/jobs/view/{match.group(1)}/"

        # Return an empty URL when no job identifier exists.
        return ""

    # Read the active page from either LinkedIn pagination layout.
    def _pagination_state(self):
        # Prefer the older visible page counter when present.
        try:
            element = self.driver.find_element(
                By.CSS_SELECTOR,
                ".jobs-search-pagination__page-state",
            )
            state = (element.text or "").strip()
            if state:
                return state
        except Exception:
            pass

        # Read the active numbered button in the newer layout.
        try:
            element = self.driver.find_element(
                By.CSS_SELECTOR,
                '[data-testid="pagination-controls-list"] button[aria-current="true"], '
                '[data-testid="pagination-controls-list"] button[aria-current="page"]',
            )
            return (element.get_attribute("aria-label") or element.text or "").strip()
        except Exception:
            return ""

    # Advance to the next LinkedIn results page when available.
    def _advance_page(self):
        # Capture the current page before LinkedIn replaces its results.
        old_state = self._pagination_state()

        # Support both the older and newer next-button selectors.
        next_selector = (
            'button[data-testid="pagination-controls-next-button-visible"], '
            'button[aria-label="View next page"], '
            '.jobs-search-pagination__button--next'
        )

        # Locate the next button afresh to avoid stale references.
        buttons = self.driver.find_elements(By.CSS_SELECTOR, next_selector)

        # Stop only when no recognised next button exists.
        if not buttons:
            logger.info("No recognised next-page button found; pagination selectors checked: %s", next_selector)
            return False

        # Select the first visible next button.
        button = next((item for item in buttons if item.is_displayed()), None)

        # Stop when the next button is not visible.
        if button is None:
            logger.info("Next-page button exists but is not visible.")
            return False

        # Check both HTML and ARIA disabled states.
        if (button.get_attribute("disabled") is not None
                or button.get_attribute("aria-disabled") == "true"):
            logger.info("Next-page button is disabled; search is exhausted.")
            return False

        try:
            # Click the current button through JavaScript.
            self.driver.execute_script("arguments[0].click();", button)

            # Wait until LinkedIn marks a different page as active.
            WebDriverWait(self.driver, self.page_load_timeout).until(
                lambda driver: bool(self._pagination_state())
                and self._pagination_state() != old_state
            )

            # Wait briefly for the new result cards to render.
            WebDriverWait(self.driver, self.page_load_timeout).until(
                lambda driver: bool(self._find_cards())
            )

            # Report the newly selected results page.
            logger.info("Advanced LinkedIn results from %s to %s", old_state, self._pagination_state())
            return True

        except StaleElementReferenceException:
            # Recheck page state if LinkedIn replaced pagination mid-click.
            try:
                WebDriverWait(self.driver, 5).until(
                    lambda driver: bool(self._pagination_state())
                    and self._pagination_state() != old_state
                )
                logger.info("Pagination advanced to %s after DOM refresh", self._pagination_state())
                return True
            except TimeoutException:
                logger.warning("Pagination button became stale; page remained %r", old_state)
                return False

        except TimeoutException:
            # Report a failed page transition without losing collected jobs.
            logger.warning("Next-page click did not change page from %r", old_state)
            return False

    # Scroll LinkedIn's actual lazy-column results list.
    def _scroll_results(self):
        # Locate the current semantic results column and its scroll parent.
        metrics = self.driver.execute_script(
            """const list = document.querySelector(
                '[data-testid="lazy-column"][data-component-type="LazyColumn"][componentkey="SearchResultsMainContent"]'
            );
            if (!list) return {target: 'lazy-column-not-found'};
            let panel = list;
            let node = list;
            while (node && node !== document.body) {
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                if (/(auto|scroll)/.test(style.overflowY) &&
                    node.scrollHeight > node.clientHeight + 5 &&
                    rect.width > 150 && rect.height > 100) {
                    panel = node;
                    break;
                }
                node = node.parentElement;
            }
            const before = panel.scrollTop;
            const step = Math.max(300, Math.floor(panel.clientHeight * 0.8));
            panel.scrollTop = Math.min(panel.scrollHeight, before + step);
            panel.dispatchEvent(new Event('scroll', {bubbles: true}));
            return {
                target: panel === list ? 'SearchResultsMainContent' : 'lazy-column-scroll-parent',
                className: String(panel.className),
                before,
                after: panel.scrollTop,
                height: panel.scrollHeight,
                client: panel.clientHeight,
                width: panel.getBoundingClientRect().width,
                cards: list.querySelectorAll('[componentkey^="job-card-component-ref-"]').length
            };"""
        )

        # Log the selected list and actual movement.
        logger.debug("Scroll diagnostics: %s", metrics)

        # Allow LinkedIn to load additional cards.
        time.sleep(2.5)

    # Open a job card and extract its detail pane.
    def _extract_job(self, card, link):
        # Read initial card information before clicking.
        title = self._text(
            card,
            [
                "p span[aria-hidden='true']",
                "p.djeljd span[aria-hidden='true']",
                "a.job-card-list__title--link",
                "a.job-card-container__link",
                "a[href*='/jobs/view/']",
            ],
        )

        # Read company and location from modern result-card paragraphs.
        modern_metadata = [
            item.text.strip()
            for item in card.find_elements(By.CSS_SELECTOR, "p.djeloo")
            if item.text.strip()
        ]

        # Prefer legacy company selectors before modern paragraph fallback.
        company = self._text(
            card,
            [
                ".artdeco-entity-lockup__subtitle",
                ".job-card-container__primary-description",
                ".job-card-list__company-name",
            ],
        ) or (modern_metadata[0] if modern_metadata else "")

        # Prefer legacy location selectors before modern paragraph fallback.
        place = self._text(
            card,
            [
                ".job-card-container__metadata-item",
                ".artdeco-entity-lockup__caption",
                ".job-card-list__location",
            ],
        ) or (modern_metadata[1] if len(modern_metadata) > 1 else "")

        # Read the posted date from the card.
        date_text = self._text(card, ["time", ".job-card-container__listed-time"])

        # Read any company link from the card.
        company_link = self._attribute(
            card,
            ["a.job-card-container__company-name", "a[href*='/company/']"],
            "href",
        )

        # Read supplementary card insights.
        insights = [
            element.text.strip()
            for element in card.find_elements(
                By.CSS_SELECTOR,
                ".job-card-container__footer-item, .job-card-list__footer-item",
            )
            if element.text.strip()
        ]

        # Click the card to populate LinkedIn's detail pane.
        try:
            self.driver.execute_script("arguments[0].click();", card)
        except Exception:
            card.click()

        # Wait for the selected job details to finish updating.
        try:
            WebDriverWait(self.driver, 10).until(
                lambda driver: (
                    self._text(driver, [
                        ".jobs-unified-top-card__job-title",
                        ".jobs-search__job-details--container h1",
                        "h1.t-24",
                    ]) or title
                )
            )
        except TimeoutException:
            # Continue with card data if the title never appears.
            logger.warning("Job detail title did not appear within 10 seconds: %s", link)

        # Read the title from the detail pane when available.
        detail_title = self._text(
            self.driver,
            [
                ".jobs-search__job-details--container h1",
                ".jobs-unified-top-card__job-title",
                "h1.t-24",
            ],
        )

        # Prefer the detail title over the card title.
        title = detail_title or title

        # Read the company from current and legacy detail-pane layouts.
        company_selectors = [
            ".jobs-unified-top-card__company-name",
            ".jobs-details-top-card__company-url",
            ".job-details-jobs-unified-top-card__company-name",
            "[class*='top-card'] a[href*='/company/']",
            "a[href*='/company/']",
        ]
        detail_company = self._text(self.driver, company_selectors)
        company = detail_company or company

        # Extract the description from several known LinkedIn layouts.
        description_selectors = [
            ".jobs-description__content",
            ".jobs-box__html-content",
            "#job-details",
            ".jobs-description-content__text",
            ".jobs-description",
            ".jobs-description__container",
            '[data-testid="expandable-text-box"]',
            '[class*="jobs-description"]',
            '[id*="job-details"]',
        ]
        description = self._text(self.driver, description_selectors)

        # Retry after waiting when LinkedIn has not rendered the description.
        for attempt in range(2):
            if description.strip():
                break
            try:
                WebDriverWait(self.driver, 8).until(
                    lambda driver: self._text(driver, description_selectors).strip()
                )
            except TimeoutException:
                # Re-click the selected card once before the final attempt.
                if attempt == 0:
                    try:
                        self.driver.execute_script("arguments[0].click();", card)
                    except Exception:
                        pass
            description = self._text(self.driver, description_selectors)

        # Retry company extraction after the detail pane has settled.
        if not company:
            company = self._text(self.driver, company_selectors)

        # Read the detail-pane location when available.
        detail_place = self._text(
            self.driver,
            [
                ".jobs-unified-top-card__primary-description",
                ".jobs-details-top-card__job-info",
            ],
        )

        # Use the detail location only if the card location was absent.
        place = place or detail_place

        # Return the extracted job in the expected event structure.
        return EventData(
            link=link,
            title=title,
            company=company,
            place=place,
            date_text=date_text,
            description=description,
            company_link=company_link,
            insights=insights,
        )

    # Run a supplied LinkedIn search URL.
    def run(self, queries, options=None):
        # Accept one query or a list of queries.
        if not isinstance(queries, list):
            queries = [queries]

        # Start or reuse the same Chrome browser for all searches.
        self._start_browser()

        # Process each query sequentially without homepage detours.
        for query in queries:
            # Read the search URL.
            search_url = query.url

            # Prefer query-specific limit, then run-level limit.
            query_limit = getattr(getattr(query, "options", None), "limit", None)
            run_limit = getattr(options, "limit", None)
            limit = query_limit or run_limit or 25

            # Navigate directly to the requested search URL.
            logger.info("Opening %s", search_url)
            self.driver.get(search_url)

            # Check authentication only if this search was redirected.
            self._ensure_login()

            # Wait for search results or a recognisable empty state.
            try:
                WebDriverWait(self.driver, self.page_load_timeout).until(
                    lambda driver: bool(self._find_cards())
                    or bool(driver.find_elements(
                        By.CSS_SELECTOR, "a[href*='/jobs/view/']"
                    ))
                    or "no results" in driver.page_source.lower()
                )
            except TimeoutException:
                logger.warning("Timed out waiting for LinkedIn search results.")

            # Announce the beginning of this search.
            cards = self._find_cards()
            if not cards:
                job_links = self.driver.find_elements(
                    By.CSS_SELECTOR, "a[href*='/jobs/view/']"
                )
                logger.warning(
                    "No job cards detected. URL=%s | title=%s | job_links=%s | page_text=%r",
                    self.driver.current_url,
                    self.driver.title,
                    len(job_links),
                    self.driver.find_element(By.TAG_NAME, "body").text[:500],
                )
            else:
                logger.info("Detected %s job cards on initial page.", len(cards))
            self.emit(Events.BEGIN, EventBegin(job_total=len(cards)))

            # Track unique jobs across scrolling and rerendering.
            seen_ids = set()
            collected = 0
            unchanged_rounds = 0

            # Continue until the limit or all result pages are exhausted.
            while collected < limit:
                # Snapshot cards because LinkedIn may rerender during extraction.
                cards = self._find_cards()
                new_jobs_this_round = 0

                # Visit each currently rendered card.
                for index in range(len(cards)):
                    # Stop when the requested limit is reached.
                    if collected >= limit:
                        break

                    try:
                        # Refresh the card list after any detail-pane interaction.
                        current_cards = self._find_cards()

                        # Skip indexes no longer present.
                        if index >= len(current_cards):
                            continue

                        # Select the current result card.
                        card = current_cards[index]

                        # Extract its job URL.
                        link = self._card_link(card)

                        # Skip cards without a recognisable job URL.
                        if not link:
                            continue

                        # Extract the LinkedIn job ID.
                        job_id = self._job_id(link)

                        # Use the URL as a fallback unique identifier.
                        unique_id = job_id or link

                        # Skip jobs already collected.
                        if unique_id in seen_ids:
                            continue

                        # Extract the job and its detail pane.
                        data = self._extract_job(card, link)

                        # Skip cards without a title or URL.
                        if not data.title or not data.link:
                            logger.warning(
                                "Job card had no title after extraction: %s", link
                            )
                            continue

                        # Mark the job seen only after successful extraction.
                        seen_ids.add(unique_id)

                        # Send the job to the user's existing callback.
                        self.emit(Events.DATA, data)

                        # Update the extracted-job count.
                        collected += 1
                        new_jobs_this_round += 1

                        # Preserve the existing pagination monitor's log pattern.
                        logger.info("Processed %s", data.title)

                        # Pause between jobs to avoid rapid requests.
                        time.sleep(self.slow_mo)

                    except StaleElementReferenceException:
                        # Let the next scroll round refresh stale cards.
                        continue

                    except Exception as exc:
                        # Log one failed card without ending the whole search.
                        logger.warning("Could not extract one job: %s", exc)

                # Count rounds that produced no new jobs.
                if new_jobs_this_round == 0:
                    unchanged_rounds += 1
                else:
                    unchanged_rounds = 0

                # Try the next numbered page after scrolling stalls.
                if unchanged_rounds >= 4 and collected < limit:
                    if self._advance_page():
                        unchanged_rounds = 0
                        continue
                    break

                # Scroll to load additional cards on this page.
                if collected < limit:
                    self._scroll_results()

            # Report the final count for this search.
            logger.info("Search finished: collected %s jobs", collected)

            # Notify listeners that this query has ended.
            self.emit(Events.END)

    # Close Chrome cleanly when the caller is finished.
    def close(self):
        # Quit the browser only when it exists.
        if self.driver is not None:
            try:
                self.driver.quit()
            finally:
                self.driver = None

    # Support context-manager cleanup.
    def __enter__(self):
        # Return this scraper instance.
        return self

    # Close the browser when leaving a context manager.
    def __exit__(self, exc_type, exc_value, traceback):
        # Release the Chrome process and profile lock.
        self.close()
