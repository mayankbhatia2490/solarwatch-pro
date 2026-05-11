import re

with open('ksolare.html', encoding='utf-8') as f:
    text = f.read()

keys = re.findall(r'company[-_]?key[\"\'\s:=]+([A-Za-z0-9]+)', text, re.IGNORECASE)
hex_strs = re.findall(r'[\"\']([A-Fa-f0-9]{16})[\"\']', text)

print('Keys:', keys)
print('Hex strings:', set(hex_strs))

# Also extract script tags to see what JS files to fetch
scripts = re.findall(r'src=[\"\'](.*?\.js[^\"]*)[\"\']', text)
print('Scripts:', scripts)
