"""Free public property pages. No browser evasion, private APIs or account data."""
import argparse,datetime as dt,hashlib,html,importlib.util,json,re,time,urllib.request,urllib.parse,urllib.error,xml.etree.ElementTree as ET
from pathlib import Path
spec=importlib.util.spec_from_file_location('public',Path(__file__).with_name('collect-platforms.py'));p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
ROOT=Path(__file__).resolve().parents[1]
AGENT='HRI-AccommodationDirectory/1.0'
KINDS={'Hotel':'Hotel','LodgingBusiness':'Accommodation (type not reported)','Resort':'Resort','Hostel':'Hostel','Apartment':'Serviced apartment / aparthotel','ApartmentComplex':'Serviced apartment / aparthotel','BedAndBreakfast':'Guesthouse / B&B','Motel':'Motel','VacationRental':'Holiday rental'}
def types(n):
 v=n.get('@type',[]);return [v] if isinstance(v,str) else v
def plain(s):return ' '.join(html.unescape(re.sub('<[^>]+>',' ',s)).split())
def positive(v):
 if isinstance(v,dict):v=v.get('value')
 return int(v) if re.fullmatch(r'[1-9]\d{0,5}',str(v)) else None
def parse(text,url,platform,countries):
 doc=p.Document(text);nodes=[]
 for attrs,body in doc.scripts:
  if attrs.get('type')=='application/ld+json':
   try:nodes.extend(p.walk(json.loads(body)))
   except (ValueError,TypeError):pass
 candidates=[n for n in nodes if any(t in KINDS for t in types(n)) and n.get('name') and n.get('address')]
 record=None
 for n in candidates:
  # Ignore recommendations and unrelated nested properties.
  target=n.get('url') or n.get('@id')
  if target and urllib.parse.urljoin(url,str(target)).split('#')[0].rstrip('/')!=url.rstrip('/'):continue
  a=n['address'];a={'streetAddress':a} if isinstance(a,str) else a
  country=a.get('addressCountry');country=country.get('name') or country.get('@id') if isinstance(country,dict) else country
  code=countries.get(str(country).casefold())
  if not code:continue
  typ=next((t for t in types(n) if t in KINDS),'LodgingBusiness');g=n.get('geo') or {};lat=lon=None
  try:
   lat,lon=float(g['latitude']),float(g['longitude'])
   if not (-90<=lat<=90 and -180<=lon<=180) or (lat==lon==0):lat=lon=None
  except (ValueError,TypeError,KeyError):pass
  # Apartment numberOfRooms describes rooms inside a unit, not hotel capacity.
  rooms=positive(n.get('numberOfRooms')) if typ not in ['Apartment','ApartmentComplex','VacationRental'] else None
  brand=n.get('brand');brand=brand.get('name') if isinstance(brand,dict) else brand if isinstance(brand,str) else None
  record={'name':plain(str(n['name'])),'country':code,'city':a.get('addressLocality'),'region':a.get('addressRegion'),'postcode':a.get('postalCode'),
   'address':', '.join(str(a[k]) for k in ['streetAddress','postalCode','addressLocality','addressRegion'] if a.get(k)),
   'lat':lat,'lon':lon,'rooms':rooms,'roomsEvidence':'Published Schema.org numberOfRooms='+str(rooms) if rooms else None,
   'brand':brand or 'Brand not reported','brandId':'unreported','propertyType':KINDS[typ],'propertyTypeBasis':'Published Schema.org '+typ}
  break
 if not record and platform=='The Apartment Network':
  # The property heading/address and property-specific tan: metadata; never footer contacts.
  def meta(k):
   m=re.search(r'<meta\b[^>]*property=["\x27]tan:'+k+r'["\x27][^>]*content=["\x27]([^"\x27]*)',text,re.I);return html.unescape(m[1]) if m else None
  m=re.search(r'<div class="pd_cont">\s*<h1>(.*?)</h1>\s*<p>(.*?)</p>',text,re.S);code=countries.get(str(meta('country')).casefold())
  if m and code:record={'name':plain(m[1]),'address':plain(m[2]),'country':code,'city':meta('city'),'brand':'Brand not reported','brandId':'unreported','propertyType':'Serviced apartment / aparthotel','propertyTypeBasis':'Public serviced-apartment directory','rooms':None}
 if not record:return None
 if platform in ['Ostrovok','ZenHotels']:
  kinds=[]
  for attrs,body in doc.scripts:
   if attrs.get('id')=='__NEXT_DATA__':
    try:kinds=[n for n in p.walk(json.loads(body)) if 'roomsNumber' in n and 'kind' in n]
    except (ValueError,TypeError):pass
  if len(kinds)==1:
   kind=kinds[0]['kind'];record['propertyType']={'GUESTHOUSE':'Guesthouse / B&B','APARTMENT':'Apartment','HOSTEL':'Hostel','RESORT':'Resort','HOTEL':'Hotel'}.get(kind,'Accommodation (type not reported)');record['propertyTypeBasis']='Published property kind '+str(kind)
   if kind in ['HOTEL','GUESTHOUSE','HOSTEL','RESORT','MINIHOTEL','MOTEL','BNB']:
    facts=re.search(r'(?:Количество номеров|Number of rooms)</p>\s*<div[^>]*>\s*(\d+)\s',text)
    if facts:record['rooms']=int(facts[1]);record['roomsEvidence']='Published property fact: Количество номеров '+facts[1]
 record.update(id='listing:'+hashlib.sha256((platform+'|'+url).encode()).hexdigest()[:24],platforms=[platform],platformUrls={platform:url},source=platform+' public property page',sourceUrl=url,collectedAt=p.now(),status='Platform listing')
 if record.get('rooms'):record.update(roomsSourceUrl=url,roomsObservedAt=p.now(),roomsStatus='platform_reported')
 return record
class PublicHTTP:
 def __init__(self,hosts,delay=3):self.hosts=set(hosts);self.domains={h.removeprefix('www.').removeprefix('hotels.').removeprefix('hotel.') for h in hosts};self.last={};self.rules={};self.delay=delay
 def allowed(self,host):return bool(host) and any(host==d or host.endswith('.'+d) for d in self.domains)
 def raw(self,url,limit=20_000_000,truncate=False):
  u=urllib.parse.urlparse(url)
  if u.scheme!='https' or not self.allowed(u.hostname):raise ValueError('Host outside configured public source')
  time.sleep(max(0,self.delay-(time.monotonic()-self.last.get(u.hostname,0))));self.last[u.hostname]=time.monotonic()
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':AGENT,'Accept-Language':'en'}),timeout=25) as r:
   if not self.allowed(urllib.parse.urlparse(r.url).hostname):raise ValueError('Redirected outside public source')
   b=r.read(limit+1)
  if len(b)>limit and not truncate:raise ValueError('Published page exceeds bounded size')
  if b[:2]==b'\x1f\x8b':
   import zlib
   b=zlib.decompressobj(16+zlib.MAX_WBITS).decompress(b,limit+1)
   if len(b)>limit and not truncate:raise ValueError('Expanded public page exceeds size limit')
  return b.decode('utf-8','replace')
 def robots(self,host):
  if host in self.rules:return self.rules[host]
  try:text=self.raw('https://'+host+'/robots.txt',500_000)
  except urllib.error.HTTPError as e:
   if e.code==404:text='User-agent: *\nAllow: /'
   else:raise
  if '<html' in text.lower():raise ValueError('No usable robots policy returned')
  groups=[];agents=[];rules=[]
  for line in text.splitlines()+['User-agent: END']:
   line=line.split('#')[0].strip()
   if ':' not in line:continue
   k,v=map(str.strip,line.split(':',1));k=k.lower()
   if k=='user-agent':
    if rules:groups.append((agents,rules));agents=[];rules=[]
    agents.append(v.lower())
   elif k in ['allow','disallow'] and v:rules.append((k,v))
  if rules:groups.append((agents,rules))
  selected=[r for a,r in groups if any(x!='*' and x in AGENT.lower() for x in a)] or [r for a,r in groups if '*' in a]
  result=(text,[x for r in selected for x in r]);self.rules[host]=result;return result
 def get(self,url,sitemap=False):
  u=urllib.parse.urlparse(url);_,rules=self.robots(u.hostname);path=u.path+('?' + u.query if u.query else '')
  matches=[]
  for action,pattern in rules:
   regex='^'+re.escape(pattern).replace(r'\*','.*');regex=regex[:-2]+'$' if regex.endswith(r'\$') else regex
   if re.search(regex,path):matches.append((len(pattern.replace('*','')),action=='allow'))
  if matches and not max(matches)[1]:raise ValueError('Disallowed by public robots policy')
  return self.raw(url,truncate=sitemap)
def locations(text):
 try:
  root=ET.fromstring(text);return root.tag.endswith('sitemapindex'),[e.text for e in root.iter() if e.tag.endswith('}loc') and e.text]
 except ET.ParseError:
  if '<urlset' in text[:500]:return False,[html.unescape(x) for x in re.findall(r'<loc>(https://[^<]+)</loc>',text)]
  raise
def collect(root,platform,minutes=15,limit=100,sitemap_limit=8,delay=3):
 cfg=json.loads((root/'config/accommodation-platforms.json').read_text(encoding='utf-8'));source=next(x for x in cfg['platforms'] if x['name']==platform)
 scope=json.loads((root/'config/platform-seeds.json').read_text(encoding='utf-8'));europe=set(scope['europeCountries']);countries={str(k).casefold():v for k,v in scope.get('countryCodes',{}).items()};countries.update({x['name'].casefold():x['code'] for x in scope['countries']});countries.update({x.casefold():x for x in europe});countries.update({'united kingdom':'GB','czech republic':'CZ','türkiye':'TR'})
 host=urllib.parse.urlparse(source['website']).hostname;hosts={host,host.removeprefix('www.'),'www.'+host.removeprefix('www.')};http=PublicHTTP(hosts,max(10 if platform=='The Apartment Network' else 3,delay));deadline=time.monotonic()+minutes*60
 key=re.sub('[^a-z0-9]+','-',platform.lower()).strip('-');file=root/'data/platforms'/('public-'+key+'.json');old=json.loads(file.read_text(encoding='utf-8')) if file.exists() else [];records={x['id']:x for x in old}
 report={'source':platform,'updatedAt':p.now(),'complete':False,'saved':len(records),'failures':[],'detailPagesAttempted':0,'discoveredPropertyUrls':0,'status':'attempting public collection'}
 try:
  robot,_=http.robots(host)
  maps=re.findall(r'(?im)^sitemap:\s*(https://\S+)',robot) or ['https://'+host+'/sitemap.xml']
  def priority(u):return (2 if re.search(r'review|image|blog|attraction|themed|post-',u,re.I) else 0 if re.search(r'hotel|apartment|property|detail',u,re.I) else 1,u)
  maps=sorted(maps,key=priority)[:sitemap_limit]
  if platform=='TheSqua.re':maps=['https://www.thesqua.re/corporate/europe/detail-sitemap.xml','https://www.thesqua.re/corporate/london-uk/detail-sitemap.xml']
  if platform=='The Apartment Network':maps=['https://www.theapartmentnetwork.com/apartments-sitemap'+('' if i==1 else str(i))+'.xml' for i in range(1,7)]
  if platform=='Agoda':maps=['https://www.agoda.com/sitemaps-wl_1_lang_1_pagetype_7_page_'+str(i)+'.xml' for i in range(1,3)]
  queue=[];seen=set();visited=set()
  if platform=='Ostrovok':
   for city in ['berlin','munich','hamburg']:
    try:
     for link in p.Document(http.get('https://ostrovok.ru/hotel/germany/'+city+'/')).links:
      link=urllib.parse.urljoin('https://ostrovok.ru',link).split('?')[0]
      if re.search(r'/hotel/germany/[^/]+/mid\d+/',link) and link not in seen:seen.add(link);queue.append(link)
    except Exception as exc:report['failures'].append({'url':city,'error':str(exc)[:160]})

  while maps and len(visited)<sitemap_limit and time.monotonic()<deadline:
   u=maps.pop(0)
   if u in visited:continue
   visited.add(u)
   try:
    index,links=locations(http.get(u,sitemap=True))
    if index:maps[0:0]=sorted((x for x in links if re.search('hotel|apartment|detail|sitemap',x,re.I) and not re.search('blog|image|post-|review|attraction',x,re.I)),key=priority)
    else:
     for x in links:
      if x in seen or not re.search(r'(?i)/hotel/|hotel-detail|/apartments/[^/]+|/serviced-apartments/[^/]+|Hotel-Information|/ho\d+|/hi/|\.ksp$|/rooms/\d+|/HOTEL/\d+',x):continue
      if platform in ['Ostrovok','ZenHotels'] and not re.search(r'/mid\d+/',x):continue
      if platform=='Agoda' and not re.search(r'-(?:'+ '|'.join(c.lower() for c in europe)+r')\.html$',x):continue
      seen.add(x);queue.append(x)
   except Exception as exc:report['failures'].append({'url':u,'error':str(exc)[:160]})
  # Refresh old observations first, rotating the untouched queue using a persisted cursor.
  statefile=root/'data/source-coverage'/('platform-public-'+key+'.json');previous=json.loads(statefile.read_text(encoding='utf-8')) if statefile.exists() else {};queue.sort(key=lambda u:(0 if re.search(r"/germany/|/berlin/|/munich/|/frankfurt/|-de\.html$",u) else 1,u));cursor=previous.get('nextCursor',0)%max(1,len(queue));ordered=queue[cursor:]+queue[:cursor];attempted=0
  for u in ordered:
   if attempted>=limit or time.monotonic()>deadline:break
   attempted+=1;report['detailPagesAttempted']=attempted
   try:
    row=parse(http.get(u),u,platform,countries)
    if row and row['country'] in europe:records[row['id']]=row
    elif not row:report['failures'].append({'url':u,'error':'No supported public property data; no record invented'})
   except Exception as exc:
    report['failures'].append({'url':u,'error':str(exc)[:160]})
    if isinstance(exc,urllib.error.HTTPError) and exc.code in [403,429]:break
   if attempted%10==0:p.atomic(file,list(records.values()))
  report.update(nextCursor=(cursor+attempted)%max(1,len(queue)),discoveredPropertyUrls=len(queue),saved=len(records),status='partial public observations' if records else 'Public import attempted; no usable observations')
 except Exception as exc:report['status']='Public source unavailable; prior observations retained';report['failures'].append({'url':source['website'],'error':str(exc)[:160]})
 if records:p.atomic(file,list(records.values()))
 p.atomic(root/'data/source-coverage'/('platform-public-'+key+'.json'),report);print(json.dumps({k:v for k,v in report.items() if k!='failures'}),flush=True)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--root',type=Path,default=ROOT);a.add_argument('--platform',required=True);a.add_argument('--minutes',type=float,default=15);a.add_argument('--limit',type=int,default=100);a.add_argument('--delay',type=float,default=3);args=a.parse_args();collect(args.root,args.platform,args.minutes,args.limit,delay=args.delay)
