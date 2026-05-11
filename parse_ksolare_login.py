import re
text = open('ksolare_login.html', encoding='utf-8').read()
keys = re.findall(r'company.*', text, re.IGNORECASE)
for k in keys: print(k[:100].encode('ascii', 'ignore').decode())
print('Hex strings:', set(re.findall(r'[\"\']([A-Fa-f0-9]{16})[\"\']', text)))

# Also extract script tags to see what JS files to fetch
scripts = re.findall(r'src=[\"\'](.*?\.js[^\"]*)[\"\']', text)
print('Scripts:', scripts)
