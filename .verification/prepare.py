"""Build one isolated candidate, prove red/green, and commit only its topic."""
import os
from pathlib import Path
import subprocess
import sys

issue = os.environ['ISSUE']
root = Path(os.environ['GITHUB_WORKSPACE'])
work = Path(os.environ['RUNNER_TEMP']) / 'candidate'
out = root / '.verification' / 'out' / issue
out.mkdir(parents=True, exist_ok=True)
plans = {
    '863': ('Explain partial Today search matches', ['site/assets/app.js', 'tests/today_benchmark_search_harness.mjs', 'tests/test_today_benchmark_search.py'], ['tests/test_today_benchmark_search.py']),
    '987': ('Omit unverified benchmark sitemap modification dates', ['src/benchmark_radar/site_pages.py', 'tests/test_site_pages.py'], ['tests/test_site_pages.py', '-k', 'benchmark_sitemap_omits']),
    '1077': ('Keep email headings consistent with the blog history', ['src/benchmark_radar/email_brief.py', 'tests/test_email_brief.py'], ['tests/test_email_brief.py', '-k', 'email_and_blog_headings']),
}
title, paths, tests = plans[issue]
def run(*args):
    return subprocess.run(args, cwd=work, text=True, check=True)
run('git', 'apply', str(root / '.verification' / 'patches' / f'{issue}-tests.patch'))
red = subprocess.run(['pytest', '-q', *tests], cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(out / 'regression-before.txt').write_text(red.stdout)
print(red.stdout, flush=True)
assert red.returncode == 1 and 'AssertionError' in red.stdout and 'FAILED' in red.stdout, 'Expected assertion regression failure, not a collection/environment error'
run('git', 'apply', str(root / '.verification' / 'patches' / f'{issue}-fix.patch'))
python_paths = [p for p in paths if p.endswith('.py')]
run('ruff', 'format', *python_paths)
run('ruff', 'check', *python_paths)
green = subprocess.run(['pytest', '-q', *tests], cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(out / 'regression-after.txt').write_text(green.stdout)
print(green.stdout, flush=True)
assert green.returncode == 0, 'Fixed regression failed'
run('git', 'diff', '--check')
run('git', 'add', '--', *paths)
run('git', '-c', 'user.name=Shi Li', '-c', 'user.email=118102425+Li018@users.noreply.github.com', 'commit', '-m', title, '-m', f'Closes ktwu01/benchmark-radar#{issue}\n\nAgent-assisted implementation with failing-before/passing-after regression coverage.')
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=work, text=True).strip()
changed = subprocess.check_output(['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'], cwd=work, text=True).splitlines()
assert sorted(changed) == sorted(paths), changed
(out / 'commit.txt').write_text(sha + '\n')
(out / 'change.patch').write_bytes(subprocess.check_output(['git', 'show', '--format=fuller', 'HEAD'], cwd=work))
checked = Path(os.environ['RUNNER_TEMP']) / 'checked'
run('git', 'worktree', 'add', '--detach', str(checked), sha)
with open(os.environ['GITHUB_ENV'], 'a') as env:
    env.write(f'CHECKED={checked}\nCANDIDATE_SHA={sha}\nEVIDENCE={out}\n')
