import requests, re, concurrent.futures
urls = [
    'https://lua.tools/_next/static/chunks/app/(app)/page-3c8aaf5d1a22e8bd.js',
    'https://lua.tools/_next/static/chunks/666-d3a2cfcb5b7fdea2.js',
    'https://lua.tools/_next/static/chunks/33-1551fa00ff6c489a.js',
    'https://lua.tools/_next/static/chunks/main-app-6fca1515cee9a03c.js'
]
def fetch(u): return requests.get(u).text
with concurrent.futures.ThreadPoolExecutor() as e:
    res = list(e.map(fetch, urls))
for i, r in enumerate(res):
    print(urls[i].split('/')[-1])
    print(set(re.findall(r'/api/[a-zA-Z0-9/-]+', r)))
