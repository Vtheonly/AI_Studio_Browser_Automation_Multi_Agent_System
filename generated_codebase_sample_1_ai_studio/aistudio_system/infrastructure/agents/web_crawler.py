# aistudio_system/infrastructure/agents/web_crawler.py
import urllib.parse
from typing import List, Dict
from core.interfaces.agent import IWebAgent
from core.interfaces.browser import IBrowserManager
from core.models import WebResult
from logger import TraceLogger
import config


class WebCrawler(IWebAgent):
    def __init__(self, browser_manager: IBrowserManager):
        self.logger = TraceLogger.get_logger("WebCrawler")
        self.browser = browser_manager

    async def execute_search(self, query: str) -> List[Dict[str, str]]:
        self.logger.info(f"Querying search indexer: '{query}'")
        encoded_query = urllib.parse.quote_plus(query)
        search_target = f"{config.SEARCH_ENGINE_URL}?q={encoded_query}"

        page = await self.browser.create_secondary_page()
        links: List[Dict[str, str]] = []
        try:
            await page.goto(search_target, wait_until="domcontentloaded")
            # Parse search results safely
            links = await page.evaluate(
                """() => {
                    const results = [];
                    const anchors = document.querySelectorAll('a.result__url');
                    anchors.forEach((a) => {
                        const titleElem = a.closest('.result__body')?.querySelector('a.result__snippet');
                        results.push({
                            title: titleElem ? titleElem.innerText.strip() : a.innerText.strip(),
                            url: a.href
                        });
                    });
                    return results.slice(0, 3); // Return top 3 hits
                }"""
            )
            self.logger.info(f"Found {len(links)} reference web links.")
        except Exception as e:
            self.logger.error(f"Search index parser failed: {e}")
        finally:
            await page.close()
        return links

    async def scrape_target(self, url: str) -> WebResult:
        self.logger.info(f"Scraping content from target: {url}")
        page = await self.browser.create_secondary_page()

        try:
            await page.goto(url, wait_until="domcontentloaded")

            # Extract title and strip navigation and style bloat from the page context
            page_meta = await page.evaluate(
                """() => {
                    // Strip scripts, headers, styles, footers, and sidebars
                    const elementsToRemove = document.querySelectorAll(
                        'script, style, iframe, nav, footer, header, noscript, .sidebar, .ads, [role="banner"]'
                    );
                    elementsToRemove.forEach(el => el.remove());

                    return {
                        title: document.title,
                        text: document.body.innerText || ""
                    };
                }"""
            )

            raw_text = page_meta["text"]
            # Basic whitespace compression
            clean_lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            compressed_text = "\n".join(clean_lines[:120])  # Cap extraction to manage prompt context windows

            return WebResult(
                url=url,
                title=page_meta["title"],
                raw_content="",
                text_content=compressed_text,
                success=True,
            )
        except Exception as e:
            self.logger.error(f"Failure scraping page target {url}: {e}")
            return WebResult(
                url=url,
                title="",
                raw_content="",
                text_content="",
                success=False,
                error_message=str(e),
            )
        finally:
            await page.close()