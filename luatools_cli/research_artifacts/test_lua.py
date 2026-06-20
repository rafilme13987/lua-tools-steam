import requests
import browser_cookie3

def test_lua_tools():
    try:
        cj = browser_cookie3.load(domain_name='lua.tools')
        client = requests.Session()
        client.cookies.update(cj)
        
        client.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': 'application/json'
        })
        
        # Test auth
        res = client.get('https://lua.tools/api/manifest/check?appid=1091500')
        print("Status code:", res.status_code)
        print("Response:", res.text)
        
    except Exception as e:
        print("Error:", e)

if __name__ == '__main__':
    test_lua_tools()
