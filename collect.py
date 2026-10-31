#!/usr/bin/env python3
"""An index of the Gazette of India (egazette.gov.in), and a personal copy of its Acts and Rules. PDFs are never kept in this repository.
Stage 1, catalogue: walks the Search by Publish Date listing month by month into catalogue.jsonl.
Stage 2, download: fetches the gazettes that are Acts or Rules (see wanted()) into pdf/<year>/.
Gentle by design: one request at a time, DELAY seconds apart, stops after repeated failures. Safe to stop and rerun.
  collect.py catalogue 2026-10 2025-01     newest month first
  collect.py download
  collect.py report
"""
import subprocess, re, html, time, json, os, sys, urllib.parse, calendar, collections
HOME = os.path.dirname(os.path.abspath(__file__))
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15'
SITE, DELAY = 'https://egazette.gov.in', 3
CAT, DONE, LOG, HAVE = HOME + '/catalogue.jsonl', HOME + '/months_done.txt', HOME + '/collect.log', HOME + '/have.txt'
DEADLINE = [float('inf')]                # a capped run stops starting new work after this time
MON = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()

def log(*a):
    s = time.strftime('%H:%M:%S ') + ' '.join(str(x) for x in a)
    print(s, flush=True)
    open(LOG, 'a').write(s + '\n')

def curl(url, data=None, ref=None):
    a = ['curl', '-sL', '-m', '60', '-A', UA, '-w', '\n%{http_code} %{url_effective}']
    if ref: a += ['-e', ref]
    if data is not None: a += ['--data-binary', urllib.parse.urlencode(data), '-H', 'Content-Type: application/x-www-form-urlencoded']
    out = subprocess.run(a + [url], capture_output=True, text=True, errors='ignore').stdout
    body, _, tail = out.rpartition('\n')
    code, _, eff = tail.partition(' ')
    time.sleep(DELAY)
    if code != '200': raise IOError(f'http {code}')
    return body, eff

def hidden(h):
    return {html.unescape(n): html.unescape(v) for n, v in re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', h)}

def rows(r):
    out = []
    for tr in re.findall(r'(?is)<tr[^>]*>(.*?)</tr>', r):
        if 'imgbtndownload' not in tr: continue
        c = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', x))).strip() for x in re.findall(r'(?is)<td[^>]*>(.*?)</td>', tr)]
        c = [x for x in c if x]
        # the Gazette ID sits just before the file size (CG-…, SG-…, or on older ones "NOT available ( 166503 )")
        i = next((k - 1 for k in range(len(c) - 1, 0, -1) if re.fullmatch(r'[\d.]+\s*[KMG]B', c[k])), None)
        if i is None or not re.search(r'\d+\s*\)?$', c[i]): continue
        num = re.search(r'(\d+)\s*\)?$', c[i]).group(1)
        out.append({'id': c[i], 'num': num, 'size': c[i + 1] if i + 1 < len(c) else '', 'published': c[i - 1], 'issued': c[i - 2], 'part': c[i - 3], 'category': c[i - 4], 'subject': c[i - 5], 'ministry': c[1] if i > 6 else ''})
    return out

def session():
    h, u = curl(SITE + '/')
    b = u.rsplit('/', 1)[0]
    h, u = curl(b + '/SearchMenu.aspx', ref=b + '/default.aspx')
    d = hidden(h); d['btnPublish'] = 'Search by Publish Date'
    return curl(u, data=d, ref=u)

def month(y, m):
    """every gazette published in that month"""
    h, u = session()
    d = hidden(h); last = calendar.monthrange(y, m)[1]
    if (y, m) == time.localtime()[:2]: last = time.localtime().tm_mday          # (the site refuses a future date)
    dates = {'txtDateFrom': f'01-{MON[m-1]}-{y}', 'txtDateTo': f'{last:02d}-{MON[m-1]}-{y}'}
    d.update(dates); d.update({'ImgSubmit.x': '10', 'ImgSubmit.y': '10'})
    r, u = curl(u, data=d, ref=u)
    t = re.search(r'Total No\. of Gazettes\s*:\s*(\d+)', r)
    if not t: raise IOError('no result count: ' + str(re.findall(r"alert\('([^']*)'", r)[:1]))   # never read as "none that month"
    total = int(t.group(1))
    got = rows(r); page = 1
    while len(got) < total:
        page += 1
        d = hidden(r); d.update(dates); d['__EVENTTARGET'] = 'gvGazetteList'; d['__EVENTARGUMENT'] = f'Page${page}'     # (as a browser's form sends it)
        r, u = curl(u, data=d, ref=u)
        new = rows(r)
        if not new: raise IOError(f'empty page {page}')
        got += new
    return total, got

def catalogue(a, b):
    y, m = map(int, a.split('-')); ey, em = map(int, b.split('-'))
    seen = set(open(DONE).read().split()) if os.path.exists(DONE) else set()
    fails = 0
    while (y, m) >= (ey, em) and time.time() < DEADLINE[0]:
        k = f'{y}-{m:02d}'
        if k not in seen:
            try:
                total, got = month(y, m)
                if len(got) != total: raise IOError(f'listed {total}, read {len(got)}')
                with open(CAT, 'a') as f:
                    for r in got: f.write(json.dumps(r, ensure_ascii=False) + '\n')
                open(DONE, 'a').write(k + '\n')
                log(k, 'listed', total, 'got', len(got)); fails = 0
            except Exception as e:
                fails += 1; log(k, 'failed', e)
                if fails >= 3: log('stopping after repeated failures'); return
                time.sleep(120); continue
        m -= 1
        if not m: y, m = y - 1, 12

ACT = re.compile(r'Part II-? ?Section 1\b(?!-?A)', re.I)
RULE_PART = re.compile(r'Part II-? ?Section 3-? ?Sub-? ?Section \(i\)|Part III-? ?Section 4', re.I)
RULE_WORD = re.compile(r'\b(rules?|regulations?|bye-?laws?)\b', re.I)
NOT_RULE = re.compile(r'in pursuance of sub.?rule|under rule \d|of rule \(?\d|rule \(?\d+\)? of', re.I)       # (a notice made under a rule is not a Rule)
def wanted(r):
    if ACT.search(r['part']): return 'act'
    if RULE_PART.search(r['part']) and RULE_WORD.search(r['subject']) and not NOT_RULE.search(r['subject']): return 'rule'
    return None

def entries():
    seen = {}
    for l in open(CAT):
        r = json.loads(l); seen[r['num']] = r
    return list(seen.values())

def download():
    fails = 0
    have = set(open(HAVE).read().split()) if os.path.exists(HAVE) else set()
    for r in entries():
        if time.time() >= DEADLINE[0]: return
        kind = wanted(r)
        if not kind or r['num'] in have: continue
        y = r['published'][-4:]; num = r['num']
        p = f'{HOME}/pdf/{y}/{num}.pdf'
        if os.path.exists(p): continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        q = subprocess.run(['curl', '-sL', '-m', '180', '-A', UA, '-o', p + '.part', '-w', '%{http_code}', f'{SITE}/WriteReadData/{y}/{num}.pdf'], capture_output=True, text=True).stdout
        ok = q == '200' and open(p + '.part', 'rb').read(5) == b'%PDF-'
        if ok: os.replace(p + '.part', p); fails = 0; open(HAVE, 'a').write(r['num'] + '\n')
        else:
            if os.path.exists(p + '.part'): os.remove(p + '.part')
            fails += 1; log('no pdf', r['id'], q)
            if fails >= 8: log('stopping after repeated failures'); return
        time.sleep(DELAY)

def report():
    e = entries(); c = collections.Counter(wanted(r) or 'other' for r in e)
    n = sum(len(fs) for _, _, fs in os.walk(HOME + '/pdf')) if os.path.isdir(HOME + '/pdf') else 0
    print('catalogued', len(e), dict(c), 'pdfs', n)

# ---------- OneDrive: through a door in the gatekeeper that can only open upload slots in "Gazette Collection" ----------
MIN_FREE = 25 * 1024 ** 3                # OneDrive is shared with the chamber's own files: stop while this much is still free

def gate(body):
    """Ask the gatekeeper (address and key are GitHub secrets, never printed)."""
    o = subprocess.run(['curl', '-s', '-m', '60', '-X', 'POST', '-H', 'X-Gazette-Key: ' + os.environ['GATE_KEY'], '-H', 'Content-Type: application/json', '-d', json.dumps(body), os.environ['GATE_URL'].rstrip('/') + '/api/gazette/slot'], capture_output=True, text=True).stdout
    try: return json.loads(o)
    except ValueError: raise IOError('gatekeeper gave no answer')

def upload(path, name):
    """One PDF, through an upload session (any size), in 10 MB pieces."""
    j = gate({'path': name}); url = j.get('uploadUrl')
    if not url: raise IOError('no upload slot: ' + str(j.get('error'))[:160])
    size, step = os.path.getsize(path), 10 * 1024 * 1024 - (10 * 1024 * 1024) % 327680
    with open(path, 'rb') as f:
        for at in range(0, size, step):
            part = f.read(step); end = at + len(part) - 1
            q = subprocess.run(['curl', '-s', '-m', '300', '-o', '/dev/null', '-w', '%{http_code}', '-X', 'PUT', '-H', f'Content-Range: bytes {at}-{end}/{size}', '--data-binary', '@-', url], input=part, capture_output=True).stdout.decode()
            if q not in ('200', '201', '202'): raise IOError('upload http ' + q)

def fetch(minutes):
    """One capped run of the wanted PDFs: from the Gazette to OneDrive, and off this machine."""
    DEADLINE[0] = time.time() + float(minutes) * 60
    free = gate({'space': True}).get('free', 0)
    got, fails = 0, 0
    have = set(open(HAVE).read().split()) if os.path.exists(HAVE) else set()
    for r in entries():
        if time.time() >= DEADLINE[0]: break
        kind = wanted(r)
        if not kind or r['num'] in have: continue
        y = r['published'][-4:]; num = r['num']; p = f'/tmp/{num}.pdf'
        q = subprocess.run(['curl', '-sL', '-m', '180', '-A', UA, '-o', p, '-w', '%{http_code}', f'{SITE}/WriteReadData/{y}/{num}.pdf'], capture_output=True, text=True).stdout
        if q == '200' and open(p, 'rb').read(5) == b'%PDF-':
            free -= os.path.getsize(p)
            if free < MIN_FREE: log('stopping: OneDrive is nearly full'); os.remove(p); break
            upload(p, f'{kind}s/{y}/{num}.pdf')
            open(HAVE, 'a').write(num + '\n'); got += 1; fails = 0
        else:
            fails += 1; log('no pdf', r['id'], q)
            if fails >= 8: log('stopping after repeated failures'); break
        if os.path.exists(p): os.remove(p)
        time.sleep(DELAY)
    log('uploaded', got)

def index(minutes):
    """One capped run of the catalogue: months not yet listed, newest first."""
    DEADLINE[0] = time.time() + float(minutes) * 60
    now = time.localtime()
    catalogue(f'{now.tm_year}-{now.tm_mon:02d}', '2008-01')
    report()

def probe():
    h, u = session()
    print('session ok', u.split('/')[-1])
    d = hidden(h); d.update({'txtDateFrom': '20-Oct-2026', 'txtDateTo': '24-Oct-2026', 'ImgSubmit.x': '9', 'ImgSubmit.y': '9'})
    r, _ = curl(u, data=d, ref=u)
    print('rows', len(rows(r)), re.findall(r'Total No\. of Gazettes\s*:\s*\d+', r))

if __name__ == '__main__':
    {'catalogue': lambda: catalogue(sys.argv[2], sys.argv[3]), 'download': download, 'report': report, 'probe': probe, 'index': lambda: index(sys.argv[2]), 'fetch': lambda: fetch(sys.argv[2])}[sys.argv[1]]()
