"""Supplementary real-corpus before/after evidence, never sent to upstream."""
import functools
import html
import http.server
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading

from playwright.sync_api import sync_playwright

root = Path(os.environ['GITHUB_WORKSPACE'])
work = Path(os.environ['RUNNER_TEMP']) / 'visual'
out = root / '.verification' / 'out' / 'visual'
out.mkdir(parents=True, exist_ok=True)
os.chdir(work)
sys.path.insert(0, str(work / 'src'))
from benchmark_radar import email_brief, site_pages
from benchmark_radar.blog import build_posts
from benchmark_radar.snapshots import load_snapshots

days = load_snapshots(Path('data/snapshots'))
posts = {post.slug: post for post in build_posts(days)}
day = next(d for d in days if d['date'] == '2026-08-24')
index = json.loads(Path('site/data/benchmark-index.json').read_text())['benchmarks']
report = {'base': os.environ['BASE_SHA'], 'snapshot_days': len(days), 'catalog_records': len(index), 'catalog_sources': sorted({str(r.get('source')) for r in index}), 'browser': []}
original_email = email_brief.render_email(day)
report['email_before'] = html.unescape(re.search(r'<h1[^>]*>(.*?)</h1>', original_email.html).group(1))
report['email_expected'] = posts[day['date']].title
before_dates = site_pages.benchmark_sitemap_entries(Path('site/data/benchmarks'))
report['sitemap_before_dated'] = sum(date is not None for _, date in before_dates)
report['sitemap_examples_before'] = [(url, date) for url, date in before_dates if date][:5]

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(work / 'site')))
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}/?q=protein%20structure%20prediction&lang=en'

with sync_playwright() as p:
    executable = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
    browser = p.chromium.launch(executable_path=executable, args=['--no-sandbox'])
    report['browser_version'] = browser.version
    for phase in ('before', 'after'):
        if phase == 'after':
            for issue in ('863', '987', '1077'):
                subprocess.run(['git', 'apply', str(root / '.verification' / 'patches' / f'{issue}-fix.patch')], check=True)
            importlib.reload(email_brief)
            importlib.reload(site_pages)
            corrected = email_brief.render_email(day, days=days)
            report['email_after'] = html.unescape(re.search(r'<h1[^>]*>(.*?)</h1>', corrected.html).group(1))
            assert report['email_after'] == report['email_expected']
            assert corrected.subject == original_email.subject
            report['email_parity_days'] = 0
            for snapshot in days:
                try:
                    rendered = email_brief.render_email(snapshot, days=days)
                except email_brief.EmailError:
                    continue
                heading = html.unescape(re.search(r'<h1[^>]*>(.*?)</h1>', rendered.html).group(1))
                assert heading == posts[str(snapshot['date'])].title, snapshot['date']
                report['email_parity_days'] += 1
            after_dates = site_pages.benchmark_sitemap_entries(Path('site/data/benchmarks'))
            assert [u for u, _ in before_dates] == [u for u, _ in after_dates]
            assert all(d is None for _, d in after_dates)
            report['sitemap_after_dated'] = 0
            report['sitemap_preserved_urls'] = len(after_dates)
        email_html = original_email.html if phase == 'before' else corrected.html
        (out / f'email-{phase}.html').write_text(email_html)
        for name, width, height in [('desktop', 1280, 900), ('mobile', 390, 844)]:
            for theme in ('light', 'dark'):
                context = browser.new_context(viewport={'width': width, 'height': height}, color_scheme=theme, is_mobile=name == 'mobile', has_touch=name == 'mobile')
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith('http://127.0.0.1:') else route.abort())
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
                page.wait_for_function("() => { const n = document.getElementById('today-benchmarks-note'); return n && n.textContent.includes('Registry records matching'); }", timeout=90000)
                note = page.locator('#today-benchmarks-note').inner_text()
                if phase == 'after':
                    assert 'share only some' in note, note
                else:
                    assert 'share only some' not in note, note
                page.locator('#today-benchmarks').evaluate('(el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 150)')
                page.wait_for_timeout(400)
                page.screenshot(path=str(out / f'today-{phase}-{name}-{theme}.png'))
                report['browser'].append({'phase': phase, 'viewport': name, 'theme': theme, 'note': note, 'page_errors': errors, 'horizontal_overflow': page.evaluate('document.documentElement.scrollWidth > innerWidth')})
                assert not errors, errors
                page.set_content(email_html, wait_until='domcontentloaded')
                page.screenshot(path=str(out / f'email-{phase}-{name}-{theme}.png'))
                context.close()
    browser.close()
server.shutdown()
(out / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
lines = ['# Small-fix rendered evidence', '', 'Built from the full committed corpus at `' + report['base'] + '`. The screenshots compare the same viewport and color preference. External requests are blocked; all catalog data and site assets are local. No email is sent.', '', '## Today search (#863)', '']
for name in ('desktop', 'mobile'):
    for theme in ('light', 'dark'):
        lines += [f'### {name}, {theme}', '', f'![Before](today-before-{name}-{theme}.png)', f'![After](today-after-{name}-{theme}.png)', '']
lines += ['## Email title (#1077)', '', 'Snapshot: 2026-08-24. The heading after the fix is the title of the same day\'s blog post.', '', f'Before: {report["email_before"]}', '', f'After: {report["email_after"]}', '']
for name in ('desktop', 'mobile'):
    for theme in ('light', 'dark'):
        lines += [f'### {name}, {theme}', '', f'![Before](email-before-{name}-{theme}.png)', f'![After](email-after-{name}-{theme}.png)', '']
lines += ['## Sitemap (#987)', '', f'{report["sitemap_preserved_urls"]} benchmark URLs retained; {report["sitemap_before_dated"]} unsupported evidence-derived modification dates removed. Actual per-page change dates are not tracked, so none is invented.', '', 'See [report.json](report.json) for counts, title parity checks and browser results.']
(out / 'README.md').write_text('\n'.join(lines) + '\n')
print(json.dumps(report, indent=2, ensure_ascii=False))
