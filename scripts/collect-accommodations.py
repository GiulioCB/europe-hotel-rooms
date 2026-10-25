"""Official serviced stays plus branded non-hotel OSM accommodation, free."""
import argparse,hashlib,importlib.util,json,re,time,urllib.parse,urllib.request
from pathlib import Path
spec=importlib.util.spec_from_file_location('public_directories',Path(__file__).with_name('collect-platforms.py'));public=importlib.util.module_from_spec(spec);spec.loader.exec_module(public)
ROOT=Path(__file__).resolve().parents[1]
TYPES={'apartment':'Apartment','hostel':'Hostel','motel':'Motel','guest_house':'Guesthouse / B&B','resort':'Resort','holiday_park':'Holiday park','chalet':'Chalet / holiday cottage'}
def positive(value):
    try:return int(value) if re.fullmatch(r'\d+',str(value)) and 0<int(value)<100000 else None
    except (TypeError,ValueError):return None
def osm_record(item,country):
    t=item.get('tags',{});typ=t.get('tourism');name=t.get('name:en') or t.get('name')
    if not name or typ not in TYPES:return None
    center=item.get('center',item);lat,lon=center.get('lat'),center.get('lon')
    identity='osm:'+item['type']+':'+str(item['id']);source='https://www.openstreetmap.org/'+item['type']+'/'+str(item['id'])
    rooms=positive(t.get('rooms')) if typ not in ['apartment','chalet','holiday_park'] else None
    units=positive(t.get('capacity:apartments') or t.get('apartments'))
    return {'id':identity,'name':name,'country':country,'brand':t.get('brand:en') or t.get('brand') or 'Brand not reported','brandId':'unreported','operator':t.get('operator'),
      'city':t.get('addr:city'),'region':t.get('addr:state'),'postcode':t.get('addr:postcode'),'address':', '.join(filter(None,[' '.join(filter(None,[t.get('addr:street'),t.get('addr:housenumber')])),t.get('addr:postcode'),t.get('addr:city')])) or None,
      'lat':lat,'lon':lon,'website':t.get('website') or t.get('contact:website'),'propertyType':TYPES[typ],'propertyTypeBasis':'OSM tourism='+typ,
      'rooms':rooms,'roomsSourceUrl':source if rooms else None,'roomsEvidence':'OSM rooms='+str(rooms) if rooms else None,'roomsObservedAt':public.now() if rooms else None,
      'units':units,'unitsType':'apartments' if units else None,'unitsSourceUrl':source if units else None,'unitsEvidence':'Explicit OSM apartment count' if units else None,
      'source':'OpenStreetMap accommodation observation','sourceUrl':source,'collectedAt':public.now(),'status':'Community observation','platforms':['OpenStreetMap']}
def frasers(root,deadline,details=35,delay=2):
    url='https://www.frasershospitality.com/en/our-brands/';fetch=public.Fetcher(delay,root/'.cache/platform-pages');file=root/'data/platforms/frasers.json';old=json.loads(file.read_text(encoding='utf-8')) if file.exists() else [];records={h['id']:h for h in old}
    report={'source':'Frasers Hospitality official directory','updatedAt':public.now(),'complete':False,'failures':[]}
    try:
        text=fetch.get(url);config=json.loads((root/'config/platform-seeds.json').read_text(encoding='utf-8'));countries={s['slug']:s['code'] for s in config['countries']};seen=set();count=0
        for path,name in public.Document(text).anchor_labels:
            if not re.match(r'^/en/[a-z-]+/[^/]+/[^/]+/$',path) or not name or re.search(r'opening|coming soon',name,re.I):continue
            parts=path.strip('/').split('/');country=countries.get(parts[1])
            if not country or path in seen:continue
            seen.add(path);website=urllib.parse.urljoin(url,path);identity='frasers:'+parts[-1];previous=records.get(identity,{})
            brand=next((b for b in ['Fraser Suites Reserve','Capri by Fraser','Modena by Fraser','Fraser Residence','Fraser Suites','Fraser Place','Malmaison','Hotel du Vin'] if b.casefold() in name.casefold()),None)
            record={**previous,'id':identity,'name':name,'country':country,'brand':brand or 'Brand not reported','brandId':'unreported','city':previous.get('city'),'website':website,
              'propertyType':'Serviced apartment / aparthotel' if brand and brand not in ['Malmaison','Hotel du Vin'] else 'Hotel','propertyTypeBasis':'Official property brand / directory',
              'source':'Frasers Hospitality official directory','sourceUrl':website,'directorySourceUrl':url,'collectedAt':public.now(),'status':'Official directory listing'}
            if count<details and time.monotonic()<deadline:
                count+=1
                try:
                    page=fetch.get(website);found=public.jsonld_details(page,website)
                    if found:
                        found.pop('countryName',None)
                        for key,value in found.items():
                            if value is not None and value!='':record[key]=value
                    # Only the property's own description metadata may assert unit totals.
                    meta=re.search(r'<meta\b(?=[^>]*\bname=["\x27]description["\x27])[^>]*\bcontent=["\x27]([^"\x27]*)',page,re.I)
                    units=re.search(r'\b(\d{1,4})\s+(?:fully[- ]furnished\s+)?(?:serviced\s+)?apartments\b',meta[1],re.I) if meta else None
                    if units:record.update(units=int(units[1]),unitsType='apartments',unitsSourceUrl=website,unitsEvidence=units[0])
                except Exception as exc:report['failures'].append({'url':website,'error':str(exc)[:120]})
            records[identity]=record
        report.update(saved=len(records),publishedLinks=len(seen),detailPagesAttempted=count)
    except Exception as exc:report['failures'].append({'url':url,'error':str(exc)[:150]})
    public.atomic(file,list(records.values()));public.atomic(root/'data/source-coverage/platform-frasers.json',report);print(json.dumps(report),flush=True)
def collect(root,minutes=100,country=None,details=35,delay=3):
    deadline=time.monotonic()+minutes*60;frasers(root,deadline,details,delay)
    config=json.loads((root/'config/platform-seeds.json').read_text(encoding='utf-8'));countries=[country] if country else config['europeCountries'];report={'source':'OpenStreetMap branded accommodation expansion','updatedAt':public.now(),'complete':False,'countries':[]}
    for code in countries:
        if time.monotonic()>deadline:break
        path=root/'data/platforms'/('osm-accommodation-'+code+'.json')
        try:
            query='[out:json][timeout:65];area["ISO3166-1"="'+code+'"][admin_level=2]->.c;('+''.join('nwr(area.c)[tourism="'+typ+'"][brand];' for typ in TYPES)+');out center tags;'
            request=urllib.request.Request('https://overpass.private.coffee/api/interpreter',urllib.parse.urlencode({'data':query}).encode(),headers={'User-Agent':'HRI-AccommodationDirectory/1.0'})
            with urllib.request.urlopen(request,timeout=85) as response:raw=json.load(response)
            if raw.get('remark'):raise ValueError(raw['remark'])
            rows=[r for item in raw.get('elements',[]) if (r:=osm_record(item,code))]
            if rows:public.atomic(path,rows)
            report['countries'].append({'country':code,'count':len(rows),'status':'partial observations','collectedAt':public.now()})
            print('OSM accommodation',code,len(rows),flush=True)
        except Exception as exc:report['countries'].append({'country':code,'status':'failed; prior records retained','error':str(exc)[:150],'collectedAt':public.now()})
        public.atomic(root/'data/source-coverage/platform-osm-accommodation.json',report);time.sleep(delay)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--minutes',type=float,default=100);p.add_argument('--country');p.add_argument('--details',type=int,default=35);p.add_argument('--delay',type=float,default=3);a=p.parse_args();collect(a.root,a.minutes,a.country,a.details,a.delay)
