"""Free public accommodation directories. No private APIs, accounts or paid services."""
import argparse, datetime as dt, html, json, re, time, urllib.error, urllib.parse, urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def now():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8');tmp.replace(path)
class Document(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=True);self.scripts=[];self.links=[];self.anchor_labels=[];self.anchor=None;self.label=[];self.in_script=False;self.body=[];self.attrs={};self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='script':self.in_script=True;self.body=[];self.attrs=a
        if tag=='a' and a.get('href'):self.links.append(a['href']);self.anchor=a['href'];self.label=[]
    def handle_data(self,text):
        if self.in_script:self.body.append(text)
        elif self.anchor:self.label.append(text)
    def handle_endtag(self,tag):
        if tag=='script' and self.in_script:self.scripts.append((self.attrs,''.join(self.body)));self.in_script=False
        if tag=='a' and self.anchor:self.anchor_labels.append((self.anchor,' '.join(' '.join(self.label).split())));self.anchor=None
def walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values():yield from walk(v)
    elif isinstance(x,list):
        for v in x:yield from walk(v)
def trip_links(text):
    return list(dict.fromkeys(urllib.parse.urljoin('https://www.trip.com',u).split('?')[0] for u in Document(text).links if re.search(r'/hotels/[^/]+-hotel-detail-\d+/',u)))
def trip_details(text,url):
    identity=re.search(r'-hotel-detail-(\d+)/',url)
    if not identity:return None
    for _,script in Document(text).scripts:
        m=re.fullmatch(r'\s*self\.__next_f\.push\((\[.*\])\)\s*;?\s*',script,re.S)
        if not m:continue
        try:
            chunk=json.loads(m[1])[1];payload=json.loads(chunk.split(':',1)[1])
        except (ValueError,IndexError,TypeError):continue
        for node in walk(payload):
            detail=node.get('hotelDetailResponse')
            if not isinstance(detail,dict):continue
            base=detail.get('hotelBaseInfo',{});position=detail.get('hotelPositionInfo',{});description=detail.get('hotelDescriptionInfo',{})
            if str(base.get('masterHotelId'))!=identity[1]:continue
            names=base.get('nameInfo',{});name=names.get('nameEn') or names.get('name')
            if not name:continue
            room_label=next((s for s in description.get('lables',[]) if re.fullmatch(r'Number of Rooms:\s*[\d,]+',str(s))),None)
            rooms=int(room_label.split(':')[1].replace(',','').strip()) if room_label else None
            if rooms is not None and not 0<rooms<100000:rooms=None
            coordinates=[]
            if position.get('preciseCoordinatesVisible') is True:
                try:
                    lat,lon=float(position['lat']),float(position['lng'])
                    if abs(lat)<=90 and abs(lon)<=180 and (lat or lon):coordinates=[lat,lon]
                except (KeyError,ValueError,TypeError):pass
            typ='Accommodation (type not reported)'
            for pattern,label in [(r'serviced apartment|aparthotel','Serviced apartment / aparthotel'),(r'\bhostel\b','Hostel'),(r'\bapartment[s]?\b','Apartment'),(r'\bresort\b','Resort'),(r'\bhotel\b','Hotel'),(r'\bmotel\b','Motel')]:
                if re.search(pattern,name,re.I):typ=label;break
            return {'id':'trip:'+identity[1],'name':name,'countryName':base.get('countryName'),'city':base.get('cityName'),'region':base.get('provinceName'),
              'brand':'Brand not reported','brandId':'unreported','propertyType':typ,'propertyTypeBasis':'Name wording; source type not independently verified',
              'address':position.get('address') if position.get('addressVisible') is not False else None,
              'lat':coordinates[0] if coordinates else None,'lon':coordinates[1] if coordinates else None,
              'coordinateBasis':'Published Trip.com property coordinates; map type '+str(position.get('mapType','not reported')),
              'rooms':rooms,'roomsEvidence':room_label,'roomsSourceUrl':url if rooms else None,'roomsObservedAt':now() if rooms else None,
              'roomsStatus':'platform_reported' if rooms else 'unknown','website':None,'platforms':['Trip.com'],'platformUrls':{'Trip.com':url},
              'source':'Trip.com public property page','sourceUrl':url,'collectedAt':now(),'status':'Announced opening' if (str(base.get('openYear','')).isdigit() and int(base['openYear'])>dt.datetime.now(dt.timezone.utc).year) or re.search(r'\bcoming soon\b|\bopening 20\d\d\b',name,re.I) else 'Platform listing'}
    return None
def jsonld_details(text,url):
    for attrs,body in Document(text).scripts:
        if attrs.get('type')!='application/ld+json':continue
        try:data=json.loads(html.unescape(body))
        except ValueError:continue
        for node in walk(data):
            kinds=node.get('@type',[]);kinds=[kinds] if isinstance(kinds,str) else kinds
            if not any(t in ['Hotel','LodgingBusiness','Resort','Hostel','ApartmentComplex','BedAndBreakfast','Motel'] for t in kinds):continue
            if not node.get('name'):continue
            address=node.get('address',{});address={'streetAddress':address} if isinstance(address,str) else address
            geo=node.get('geo',{});room=node.get('numberOfRooms');room=room.get('value') if isinstance(room,dict) else room
            try:room=int(room) if str(room).isdigit() and int(room)>0 else None
            except (ValueError,TypeError):room=None
            try:lat,lon=float(geo['latitude']),float(geo['longitude'])
            except (ValueError,TypeError,KeyError):lat,lon=None,None
            if lat is not None and (abs(lat)>90 or abs(lon)>180 or (lat==0 and lon==0)):lat,lon=None,None
            return {'name':html.unescape(node['name']),'address':', '.join(str(address.get(k,'')) for k in ['streetAddress','postalCode','addressLocality','addressRegion'] if address.get(k)),
              'countryName':address.get('addressCountry'),'city':address.get('addressLocality'),'region':address.get('addressRegion'),'lat':lat,'lon':lon,
              'rooms':room,'roomsEvidence':'Schema.org numberOfRooms='+str(room) if room else None,'roomsSourceUrl':url if room else None}
    return None

class Fetcher:
    def __init__(self,delay=2,cache=None):self.delay=delay;self.last=0;self.cache=cache
    def get(self,url):
        # Public SEO/official pages only. Do not turn this into a hidden API client.
        u=urllib.parse.urlparse(url)
        if u.scheme!='https' or u.hostname not in ['www.trip.com','www.frasershospitality.com','www.discoverasr.com']:raise ValueError('Unsupported public directory host')
        if u.hostname=='www.trip.com' and not re.match(r'^/hotels/(?:country/[a-z-]+\.html|[a-z0-9-]+-hotels-list-\d+/|[a-z0-9-]+-hotel-detail-\d+/[^?]*)$',u.path):raise ValueError('Not an allowed public hotel directory page')
        cachepath=None
        if self.cache:
            import hashlib
            cachepath=self.cache/(hashlib.sha256(url.encode()).hexdigest()+'.html')
            if cachepath.exists() and time.time()-cachepath.stat().st_mtime<6*3600:return cachepath.read_text(encoding='utf-8')
        time.sleep(max(0,self.delay-(time.monotonic()-self.last)));self.last=time.monotonic()
        request=urllib.request.Request(url,headers={'User-Agent':'HRI-AccommodationDirectory/1.0 (public business property research)','Accept-Language':'en'})
        with urllib.request.urlopen(request,timeout=25) as response:
            body=response.read(7*1024*1024+1)
            if len(body)>7*1024*1024:raise ValueError('Public page exceeds size limit')
            text=body.decode('utf-8','replace')
        if cachepath:cachepath.parent.mkdir(parents=True,exist_ok=True);cachepath.write_text(text,encoding='utf-8')
        return text

def collect(root,minutes=60,city_limit=8,detail_limit=400,delay=2):
    config=json.loads((root/'config/platform-seeds.json').read_text(encoding='utf-8'));fetch=Fetcher(delay,root/'.cache/platform-pages')
    countries={name.casefold():code for name,code in config.get('countryCodes',{}).items()};countries.update({s['name'].casefold():s['code'] for s in config['countries']});countries.update({'united kingdom':'GB','south korea':'KR','czech republic':'CZ','turkey':'TR','china':'CN','hong kong':'HK','taiwan':'TW','macau':'MO'})
    savedpath=root/'data/platforms/trip-com.json';saved=json.loads(savedpath.read_text(encoding='utf-8')) if savedpath.exists() else []
    records={h['id']:h for h in saved};queue={h['sourceUrl']:h.get('collectedAt','') for h in saved};coverage=[];deadline=time.monotonic()+minutes*60
    seeds=list(config.get('cities',[]));visited=set();fresh=0
    for spec in config['countries']:
        if time.monotonic()>deadline:break
        try:
            text=fetch.get('https://www.trip.com/hotels/country/'+spec['slug']+'.html')
            links=list(dict.fromkeys(urllib.parse.urljoin('https://www.trip.com',u).split('?')[0] for u in Document(text).links if re.search(r'/hotels/[a-z0-9-]+-hotels-list-\d+/',u)))
            for url in links[:city_limit]:seeds.append({'url':url,'country':spec['code']})
            coverage.append({'source':'Trip.com','country':spec['code'],'stage':'country directory','cityLinksFound':len(links),'citiesSelected':min(city_limit,len(links)),'status':'partial','collectedAt':now()})
        except Exception as exc:coverage.append({'source':'Trip.com','country':spec['code'],'stage':'country directory','status':'failed','error':str(exc)[:150],'collectedAt':now()})
        # Process each country during its turn, rather than spending the budget on country indexes alone.
        for seed in [s for s in seeds if s.get('country')==spec['code'] and s['url'] not in visited]:
            if time.monotonic()>deadline:break
            visited.add(seed['url'])
            try:
                links=trip_links(fetch.get(seed['url']))
                for url in links:queue.setdefault(url,'')
                coverage.append({'source':'Trip.com','country':spec['code'],'url':seed['url'],'stage':'city directory','linksFound':len(links),'status':'partial','collectedAt':now()})
            except Exception as exc:coverage.append({'source':'Trip.com','url':seed['url'],'status':'failed','error':str(exc)[:150],'collectedAt':now()})
    from collections import defaultdict,deque
    def balanced(urls):
        buckets=defaultdict(deque)
        for u in sorted(urls,key=lambda u:(queue[u],u)):buckets[u.split('-hotel-detail-')[0]].append(u)
        ordered=[]
        while buckets:
            for key in list(buckets):
                ordered.append(buckets[key].popleft())
                if not buckets[key]:del buckets[key]
        return ordered
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=7)).isoformat()
    pending=balanced([u for u in queue if queue[u] and queue[u]<cutoff])+balanced([u for u in queue if not queue[u]])+balanced([u for u in queue if queue[u] and queue[u]>=cutoff]);attempted=0
    for url in pending:
        if attempted>=detail_limit or time.monotonic()>deadline:break
        attempted+=1
        try:
            record=trip_details(fetch.get(url),url)
            if not record:raise ValueError('Published property schema unavailable; previous observation retained')
            country=record.pop('countryName',None);country=country.get('name') if isinstance(country,dict) else country
            record['country']=countries.get(str(country).casefold(),country if isinstance(country,str) and re.fullmatch('[A-Z]{2}',country) else 'ZZ')
            if record['country']=='ZZ':record['countryEvidence']=country;record['lat']=None;record['lon']=None
            record['firstSeen']=records.get(record['id'],{}).get('firstSeen',now());records[record['id']]=record;fresh+=1
            if fresh%20==0:atomic(savedpath,list(records.values()));print('Trip.com:',fresh,'property pages saved',flush=True)
        except Exception as exc:coverage.append({'source':'Trip.com','url':url,'stage':'property page','status':'failed','error':str(exc)[:150],'collectedAt':now()})
    atomic(savedpath,list(records.values()));atomic(root/'data/source-coverage/platform-trip-com.json',{'source':'Trip.com public directories','updatedAt':now(),'records':len(records),'newObservations':fresh,'detailPagesAttempted':attempted,'detailLinksDiscovered':len(queue),'complete':False,'coverage':coverage,'pendingDetailUrls':[u for u in pending if 'trip:'+re.search(r'-hotel-detail-(\d+)/',u)[1] not in records]})
    print(json.dumps({'source':'Trip.com','saved':len(records),'fresh':fresh,'queued':len(queue),'countriesAttempted':len({c.get('country') for c in coverage if c.get('country')}),'complete':False}),flush=True)
    return list(records.values())
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--minutes',type=float,default=60);p.add_argument('--cities-per-country',type=int,default=8);p.add_argument('--detail-limit',type=int,default=400);p.add_argument('--delay',type=float,default=2)
    a=p.parse_args();collect(a.root,a.minutes,a.cities_per_country,a.detail_limit,a.delay)
