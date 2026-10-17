"""Ping IndexNow (Bing, Yandex, Seznam, Naver, Yep) with every URL in site/sitemap.xml.
Free, no account: ownership is proven by the key file build.py writes at /<key>.txt.
Run after deploy so the key file is already live. Never fails the workflow."""
import json, os, re, sys, urllib.request
ROOT=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,ROOT)
KEY=re.search(r"INDEXNOW_KEY='([0-9a-f]+)'",open(os.path.join(ROOT,'build.py')).read()).group(1)
SITE=os.environ.get('SITE_URL','https://readdailyfive.com').rstrip('/')
urls=re.findall(r'<loc>([^<]+)</loc>',open(os.path.join(ROOT,'site','sitemap.xml')).read())
body=json.dumps({'host':SITE.split('//',1)[1],'key':KEY,'keyLocation':f'{SITE}/{KEY}.txt','urlList':urls[:10000]}).encode()
req=urllib.request.Request('https://api.indexnow.org/indexnow',data=body,headers={'Content-Type':'application/json; charset=utf-8'})
try:
    with urllib.request.urlopen(req,timeout=30) as r: print('IndexNow',r.status,len(urls),'urls')
except urllib.error.HTTPError as e: print('IndexNow HTTP',e.code,e.read()[:300])
except Exception as e: print('IndexNow skipped:',e)
