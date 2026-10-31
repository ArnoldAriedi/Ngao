import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from tests.ui.mock_api import MockApi


@pytest.fixture(scope="session")
def site():
    api = MockApi()
    yield api
    api.stop()


@pytest.fixture(scope="session")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed: pip install -r requirements-dev.txt && playwright install chromium")
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def api(site):
    site.reset()
    return site


@pytest.fixture
def new_page(browser, api):
    pages = []

    def make(width=1100, height=900):
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_default_timeout(6000)
        page.script_errors, page.outside_requests = [], []

        def route(handler):
            if handler.request.url.startswith(api.url):
                return handler.continue_()
            page.outside_requests.append(handler.request.url)
            return handler.abort()

        page.route("**/*", route)
        page.on("pageerror", lambda error: page.script_errors.append(str(error)))
        pages.append(page)
        return page

    yield make
    errors = [error for page in pages for error in page.script_errors]
    for page in pages:
        page.close()
    assert errors == [], f"uncaught script errors: {errors}"


@pytest.fixture
def app_page(new_page):
    return new_page()
