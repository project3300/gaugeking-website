"""Discover the newest Natsoft result with a fresh Chromium navigation each poll."""
from urllib.parse import urlparse, urljoin
import re
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

def safe(url):
    p=urlparse(url)
    return p.scheme in ("http","https") and p.hostname in ("racing.natsoft.com.au","www.racing.natsoft.com.au")

def discover_live_result(url, timeout=30):
    if not safe(url):
        raise ValueError("Invalid Natsoft URL")
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(ignore_https_errors=True, service_workers="block", extra_http_headers={"Cache-Control":"no-cache","Pragma":"no-cache"})
        page=context.new_page()
        page.set_default_timeout(timeout*1000)
        discovered=[]
        errors=[]
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.on('requestfailed', lambda req: errors.append('Request failed: '+req.url))
        def capture(response):
            if safe(response.url) and ("/object_" in response.url.lower() or "/view?" in response.url.lower()):
                discovered.append(response.url)
        page.on("response",capture)
        page.goto(url,wait_until="domcontentloaded",timeout=timeout*1000)
        try:
            page.locator('#LoadingPage').wait_for(state='hidden', timeout=45000)
        except Exception:
            print('Natsoft startup splash still visible after 45 seconds')
        page.wait_for_timeout(2500)
        # Natsoft's #4 route starts at the discipline selector in a fresh browser.
        # The icons are clickable images, not anchor links.
        circuit = page.locator('img#Discipline_0[title="Circuit Racing"]')
        if circuit.count() and circuit.is_visible():
            print("Entering Natsoft Circuit Racing discipline via #Discipline_0", flush=True)
            circuit.scroll_into_view_if_needed()
            circuit.click(force=True, timeout=6000)
            page.wait_for_timeout(5000)
            Path("natsoft-debug").mkdir(exist_ok=True)
            page.screenshot(path="natsoft-debug/after-circuit-click.png", full_page=True)
            Path("natsoft-debug/after-circuit-click.html").write_text(page.content(), encoding="utf-8")
            print("After Circuit Racing click:", page.url, page.locator("body").inner_text()[:800], flush=True)
        else:
            print("Circuit Racing button not found or not visible", flush=True)
        print("Natsoft drill-through stage:", page.url, flush=True)
        for depth in range(4):
            for frame in page.frames:
                try:
                    links=frame.get_by_role("link",name=re.compile(r"\bResult\b",re.I)).all()
                    links=[a for a in links if "times" not in (a.inner_text(timeout=1000) or "").lower()]
                except Exception:
                    continue
                if not links:
                    continue
                link=links[-1]
                label=link.inner_text(timeout=2000).strip()
                href=link.get_attribute("href") or ""
                target=urljoin(frame.url,href)
                if safe(target) and ("/object_" in target.lower() or "/view?" in target.lower()):
                    # Click to generate the object rather than trusting a stored snapshot.
                    try:
                        link.click(timeout=4000)
                        page.wait_for_timeout(1000)
                    except Exception:
                        pass
                    browser.close()
                    return target,label
                before=len(discovered)
                try:
                    link.click(timeout=4000)
                    page.wait_for_timeout(1800)
                except Exception:
                    pass
                if len(discovered)>before:
                    target=discovered[-1]
                    browser.close()
                    return target,label
            # Do not silently select a different event if Natsoft changes its UI.
            break
        Path("natsoft-debug").mkdir(exist_ok=True)
        page.screenshot(path="natsoft-debug/page.png", full_page=True)
        Path("natsoft-debug/page.html").write_text(page.content(), encoding="utf-8")
        Path("natsoft-debug/errors.json").write_text(json.dumps(errors[-100:], indent=2), encoding="utf-8")
        for n, frame in enumerate(page.frames):
            try:
                Path(f"natsoft-debug/frame-{n}.html").write_text(frame.content(), encoding="utf-8")
            except Exception:
                pass
        browser.close()
        raise RuntimeError("Natsoft link missing; inspect natsoft-debug artifact")
