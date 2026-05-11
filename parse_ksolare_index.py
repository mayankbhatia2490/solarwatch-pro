import requests
import re
headers = {'User-Agent': 'Mozilla/5.0'}
html = requests.get('https://ksolare.shinemonitor.com/index.html', headers=headers, timeout=10).text
keys = re.findall(r'company.*', html, re.IGNORECASE)
for k in keys: print(k[:100].encode('ascii', 'ignore').decode())
print('Hex strings:', set(re.findall(r'[\"\']([A-Fa-f0-9]{16})[\"\']', html)))
scripts = re.findall(r'src=[\"\'](.*?\.js[^\"]*)[\"\']', html)
print('Scripts:', scripts)
