import requests, re, concurrent.futures
urls = [
    'https://fares.top/_next/static/chunks/62667a9c2b1a40d3.js', 
    'https://fares.top/_next/static/chunks/cfd2fc2db7dd9053.js', 
    'https://fares.top/_next/static/chunks/b00cb0583ac0bf08.js', 
    'https://fares.top/_next/static/chunks/b566ad4c4ac60e4f.js', 
    'https://fares.top/_next/static/chunks/turbopack-b28f1496963f693c.js', 
    'https://fares.top/_next/static/chunks/ff1a16fafef87110.js', 
    'https://fares.top/_next/static/chunks/650b0d2d0b895b93.js', 
    'https://fares.top/_next/static/chunks/0dbca6a179450450.js', 
    'https://fares.top/_next/static/chunks/61bc785dc6bd3109.js', 
    'https://fares.top/_next/static/chunks/78d7cb2640eadc86.js', 
    'https://fares.top/_next/static/chunks/3d69d369188ca1b7.js', 
    'https://fares.top/_next/static/chunks/e027ab9e6928ab79.js', 
    'https://fares.top/_next/static/chunks/9ba69c6b755ef4fe.js', 
    'https://fares.top/_next/static/chunks/8b216cee6e07f7fa.js', 
    'https://fares.top/_next/static/chunks/e08ceb8f158ba5cc.js', 
    'https://fares.top/_next/static/chunks/a6dad97d9634a72d.js', 
    'https://fares.top/_next/static/chunks/66a8c16702b8a250.js'
]
def fetch(u): return requests.get(u).text 
with concurrent.futures.ThreadPoolExecutor() as e: 
    res = list(e.map(fetch, urls))
for i, r in enumerate(res): 
    m = re.findall(r'/api/[a-zA-Z0-9/_-]+', r)
    if m:
        print(urls[i].split('/')[-1], set(m))
