import requests
import re

html = requests.get('https://ksolare.shinemonitor.com/').text
scripts = re.findall(r'src=[\"\'](.*?\.js[^\"]*)[\"\']', html)
print('Found scripts:', scripts)
for s in scripts:
    url = s if s.startswith('http') else 'https://ksolare.shinemonitor.com/' + s
    try:
        content = requests.get(url).text
        keys = re.findall(r'company[-_]?key[\"\'\s:=]+([A-Za-z0-9]+)', content, re.IGNORECASE)
        hex_strs = re.findall(r'[\"\']([A-F0-9]{16})[\"\']', content, re.IGNORECASE)
        if keys: print(f'Found keys in {url}:', keys)
        if hex_strs: print(f'Found hex strings in {url}:', set(hex_strs))
    except Exception as e:
        print("Err:", e)
