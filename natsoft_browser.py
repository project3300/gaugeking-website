"""Discover the newest Natsoft result with a fresh Chromium navigation each poll."""
from urllib.parse import urlparse, urljoin
import re
import json
import zlib
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

def safe(url):
    p=urlparse(url)
    return p.scheme in ("http","https") and p.hostname in ("racing.natsoft.com.au","www.racing.natsoft.com.au")

def fetch_natsoft_raw(url, context, timeout):
    """Read raw bytes to tolerate Natsoft's nonstandard deflate responses."""
    if not safe(url):
        raise ValueError("Unexpected result host")
    cookies = {c["name"]: c["value"] for c in context.cookies() if "natsoft.com.au" in c.get("domain", "")}
    with requests.get(url, headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache", "User-Agent": "Mozilla/5.0"}, cookies=cookies, timeout=timeout, stream=True, allow_redirects=True) as response:
        response.raise_for_status()
        if not safe(response.url):
            raise RuntimeError("Natsoft result redirected to another host")
        raw = response.raw.read(decode_content=False)
        encoding = response.headers.get("Content-Encoding", "").lower()
        if encoding == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        elif encoding == "gzip":
            raw = zlib.decompress(raw, zlib.MAX_WBITS | 16)
        charset = response.encoding or "utf-8"
        html = raw.decode(charset, errors="replace")
        print(f"Natsoft raw result fetched: status={response.status_code} bytes={len(raw)} url={response.url}", flush=True)
        return html, dict(response.headers), response.status_code


def discover_meetings(date_text, track_text, timeout=30):
    """Render Natsoft's Circuit Racing list and return only verified meeting rows."""
    from datetime import datetime
    from playwright.sync_api import sync_playwright
    target_date = datetime.strptime(date_text, "%Y-%m-%d")
    aliases = {target_date.strftime("%d/%m/%Y"), target_date.strftime("%d/%m/%y"),
               target_date.strftime("%d-%m-%Y"), target_date.strftime("%d-%m-%y")}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(ignore_https_errors=True)
        try:
            page.goto("http://racing.natsoft.com.au/results/", wait_until="domcontentloaded", timeout=timeout*1000)
            page.locator('img#Discipline_0').wait_for(state="visible", timeout=45000)
            page.locator('img#Discipline_0').click()
            page.locator('[id^="MeetingList#r"][id$="c1"]').first.wait_for(timeout=30000)
            # Natsoft initially lists the current year. Historical meeting lookup
            # must explicitly select the requested year before filtering rows.
            year = str(target_date.year)
            year_selects = page.locator('select').filter(has=page.locator('option').filter(has_text=year))
            selected = False
            for index in range(year_selects.count()):
                dropdown = year_selects.nth(index)
                opts = dropdown.locator('option').all()
                for option in opts:
                    if option.inner_text().strip() == year:
                        value = option.get_attribute('value')
                        dropdown.select_option(value=value if value is not None else None, label=year)
                        selected = True
                        print(f"Natsoft discovery selected year {year}", flush=True)
                        break
                if selected:
                    break
            if not selected:
                raise RuntimeError(f"Natsoft year selector for {year} was not found")
            page.wait_for_timeout(2200)
            page.locator('[id^="MeetingList#r"][id$="c1"]').first.wait_for(timeout=30000)
            rows = page.locator('[id^="MeetingList#r"][id$="c1"]').evaluate_all("""
              (cells) => cells.map(cell => {
                const match = cell.id.match(/^(MeetingList#r\\d+)c1$/);
                if (!match) return null;
                const base = match[1];
                const date = document.getElementById(base+'c0');
                const fields = Array.from(document.querySelectorAll('[id^="'+base+'c"]'));
                return {id:base, name:(cell.innerText||'').trim(),
                        date:(date?.innerText||'').trim(),
                        fields:fields.map(c=>(c.innerText||'').trim())};
              }).filter(Boolean)
            """)
            result=[]
            for row in rows:
                combined=" ".join(row["fields"]).casefold()
                if not any(d in combined for d in aliases):
                    continue
                if track_text.casefold() not in combined:
                    continue
                result.append({"id":row["id"],"name":row["name"],"date":date_text,
                               "track":track_text,"details":row["fields"]})
            return result
        finally:
            browser.close()

def discover_live_result(url, timeout=30, meeting=None):
    if not safe(url):
        raise ValueError("Invalid Natsoft URL")
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(ignore_https_errors=True, service_workers="block", extra_http_headers={"Cache-Control":"no-cache","Pragma":"no-cache"})
        page=context.new_page()
        page.set_default_timeout(timeout*1000)
        discovered=[]
        result_responses=[]
        errors=[]
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.on('requestfailed', lambda req: errors.append('Request failed: '+req.url))
        def capture(response):
            if safe(response.url) and ("/object_" in response.url.lower() or "/view?" in response.url.lower()):
                discovered.append(response.url)
                result_responses.append(response)
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
        # The saved #4 test refers to the SubiNats meeting. Natsoft renders
        # meeting rows as div elements (MeetingList#rNc1), not anchors.
        target_name = (meeting or {}).get("name", "SubiNats 2026")
        if meeting and meeting.get("date"):
            from datetime import datetime
            requested_date = datetime.strptime(meeting["date"], "%Y-%m-%d")
            year = str(requested_date.year)
            # Natsoft may still be on the discipline splash after the click.
            # Wait for its JavaScript to populate the year control, rather
            # than checking the DOM immediately and treating loading as no data.
            def wait_for_year():
                page.wait_for_function(
                    """year => [...document.querySelectorAll('select')].some(s =>
                        [...s.options].some(o => o.textContent.trim() === year))""",
                    arg=year, timeout=30000
                )
            try:
                wait_for_year()
            except Exception:
                # One retry if the first click raced the Natsoft application startup.
                retry = page.locator('img#Discipline_0[title="Circuit Racing"]')
                if retry.count() and retry.is_visible():
                    retry.click(force=True, timeout=6000)
                try:
                    wait_for_year()
                except Exception:
                    Path("natsoft-debug").mkdir(exist_ok=True)
                    page.screenshot(path="natsoft-debug/year-not-ready.png", full_page=True)
                    Path("natsoft-debug/year-not-ready.html").write_text(page.content(), encoding="utf-8")
                    raise RuntimeError(f"Natsoft did not load its year selector for {year}")
            year_dropdown = page.locator("select").filter(
                has=page.locator("option").filter(has_text=year)
            ).first
            year_dropdown.select_option(label=year)
            page.wait_for_timeout(2200)
            page.locator('[id^="MeetingList#r"][id$="c1"]').first.wait_for(timeout=30000)
            print(f"Tracking Natsoft year {year}", flush=True)
        target_meeting = page.locator('[id^="MeetingList#r"][id$="c1"]').filter(has_text=target_name).first
        if target_meeting.count():
            print(f"Opening selected meeting: {target_name}", flush=True)
            row = target_meeting.locator('xpath=ancestor::*[starts-with(@id,"MeetingList#r") and not(contains(substring-after(@id,"#"),"c"))][1]')
            date_link = row.locator('[id$="c0"]').first
            if not date_link.count():
                raise RuntimeError("Selected meeting date link not found")
            date_link.click(timeout=6000)
            page.wait_for_timeout(3000)
            Path("natsoft-debug").mkdir(exist_ok=True)
            page.screenshot(path="natsoft-debug/after-meeting-click.png", full_page=True)
            Path("natsoft-debug/after-meeting-click.html").write_text(page.content(), encoding="utf-8")
        else:
            raise RuntimeError(f"Meeting {target_name!r} absent from Natsoft index; refusing wrong event")

        # Natsoft uses div-based rows for session results as well. Capture
        # network object responses produced by clicking a current Result cell.
        for attempt in range(3):
            result_cells = page.locator('[id*="Result"], [id*="result"]').filter(has_text=re.compile(r"Result", re.I))
            print(f"Session result controls: {result_cells.count()}", flush=True)
            if result_cells.count():
                candidate = result_cells.last
                before = len(discovered)
                candidate.click(timeout=5000)
                page.wait_for_timeout(1500)
                if len(discovered) > before:
                    result_url = discovered[-1]
                    html, headers, status = fetch_natsoft_raw(result_url, context, timeout)
                    browser.close()
                    return result_url, "Latest Published Result", html, headers, status
            page.wait_for_timeout(1200)
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
                    body, headers, status = fetch_natsoft_raw(target, context, timeout)
                    browser.close()
                    return target, label, body, headers, status
                before=len(discovered)
                try:
                    link.click(timeout=4000)
                    page.wait_for_timeout(1800)
                except Exception:
                    pass
                if len(discovered)>before:
                    target=discovered[-1]
                    body, headers, status = fetch_natsoft_raw(target, context, timeout)
                    browser.close()
                    return target, label, body, headers, status
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
