import urllib.request
import json

url = "https://api.github.com/repos/jonathands/dados-abertos-receita-cnpj/releases?per_page=5"
req = urllib.request.Request(
    url,
    headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github.v3+json"},
)
r = urllib.request.urlopen(req, timeout=15)
releases = json.loads(r.read())

for rel in releases:
    print("Release:", rel["tag_name"], "-", rel["name"])
    for asset in rel.get("assets", []):
        mb = asset["size"] / 1024 / 1024
        print("  Asset:", asset["name"], "({:.1f} MB)".format(mb))
        print("  URL:", asset["browser_download_url"])
    if not rel.get("assets"):
        print("  (no assets, body preview):", rel.get("body", "")[:300])
    print()
