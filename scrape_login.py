import requests
import re

html = requests.get('https://ksolare.shinemonitor.com/main.html').text
scripts = re.findall(r'src=\"(.*?\.js[^\"]*)\"', html)
print('Found scripts:', scripts)
for s in scripts:
    url = s if s.startswith('http') else 'https://ksolare.shinemonitor.com/' + s
    try:
        content = requests.get(url).text
        # Look for companyKey assignments or values
        keys = re.findall(r'company[-_]?Key[\"\'\s:=]+([A-Za-z0-9]+)', content, re.IGNORECASE)
        # Also just look for 16-char hex strings if they match the manual's format
        hex_strs = re.findall(r'[\"\']([A-F0-9]{16})[\"\']', content, re.IGNORECASE)
        
        if keys: 
            print(f'Found keys in {url}:', keys)
        if hex_strs:
            print(f'Found hex strings in {url}:', hex_strs)
    except Exception as e:
        print("Error on", url, e)
