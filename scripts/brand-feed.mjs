// Same free-source observations, reduced to requested brands for the website.
import {readFile,writeFile,readdir,mkdir,rename} from 'node:fs/promises';
import {gzipSync} from 'node:zlib';
import {createBrandMatcher,mergeHotelObservations} from '../src/brand-matching.js';
const catalogue=JSON.parse(await readFile(new URL('../config/requested-brands.json',import.meta.url),'utf8'));
const match=createBrandMatcher(catalogue),rows=[],platformRows=[];
try{for(const file of (await readdir('data/platforms')).filter(f=>f.endsWith('.json')).sort())platformRows.push(...JSON.parse(await readFile('data/platforms/'+file,'utf8')))}catch(e){if(e.code!=='ENOENT')throw e}
if(process.argv[2])rows.push(...JSON.parse(await readFile(process.argv[2],'utf8')));
else for(const source of ['countries','google','registries']){
 let files=[];try{files=await readdir('data/'+source)}catch(e){if(e.code!=='ENOENT')throw e}
 for(const name of files.filter(f=>f.endsWith('.json')).sort())rows.push(...JSON.parse(await readFile('data/'+source+'/'+name,'utf8')));
}
const number=value=>value!==null&&value!==''&&value!==undefined&&Number.isFinite(Number(value))?Number(value):null;
const normalized=rows.filter(r=>r.country_scope!=='query_country_unverified').map(r=>({
 id:r.hotel_id,name:r.name,country:r.country,brand:r.brand||'Brand not reported',brandId:'unreported',operator:r.operator||null,
 city:r.city||null,region:r.region||null,address:r.address||null,postcode:r.postcode||null,lat:number(r.latitude),lon:number(r.longitude),
 rooms:number(r.rooms),website:r.website||null,source:r.source||'OpenStreetMap community observation',sourceUrl:r.source_url,
 collectedAt:r.last_seen,status:'Additional directory observation',propertyType:r.property_type||'Hotel',googleMapsUrl:r.google_maps_url||null,
 roomsSourceUrl:r.rooms_source_url||null,roomsEvidence:r.rooms_evidence||null,roomsObservedAt:r.rooms_observed_at||null,
 roomsStatus:r.rooms_status||'unknown',countryBasis:r.country_basis||r.country_scope
}));
const branded=normalized.filter(h=>match(h));
const hotels=mergeHotelObservations(mergeHotelObservations([],branded),platformRows);
const roomAssertions=normalized.filter(h=>h.rooms!==null&&!match(h));
const feed={schemaVersion:1,generatedAt:new Date().toISOString(),catalogueSourceSha256:catalogue.sourceSha256,
 sourceRecords:normalized.length+platformRows.length,hotels,roomAssertions,platformCoverage:await Promise.all((await readdir('data/source-coverage').catch(()=>[])).filter(f=>f.startsWith('platform-')&&f.endsWith('.json')).map(async f=>((r)=>({source:r.source,updatedAt:r.updatedAt,records:r.records??r.saved,newObservations:r.newObservations,complete:false,countriesAttempted:r.countries?.length,failedRequests:r.failures?.length??r.coverage?.filter(x=>x.status==='failed').length??r.countries?.filter(x=>x.status.startsWith('failed')).length??0}))(JSON.parse(await readFile('data/source-coverage/'+f,'utf8'))))),limitations:['Partial source coverage; not a complete hotel census.','Parent mappings are supplied research, not independently verified legal ownership.','Name-only brand matches require review.','Room assertions enrich matching collected properties; they do not establish brand membership.']};
await mkdir('exports',{recursive:true});const target='exports/branded-hotels.json.gz';await writeFile(target+'.tmp',gzipSync(JSON.stringify(feed)));await rename(target+'.tmp',target);
const fields=['id','name','country','city','region','address','brand','propertyType','rooms','units','unitsType','lat','lon','source','sourceUrl','roomsSourceUrl','roomsEvidence','collectedAt'];
const cell=v=>'"'+String(v??'').replace(/^[=+@\-\t\r]/,"'$&").replace(/"/g,'""')+'"';
const csv='\uFEFF'+[fields.join(','),...platformRows.map(h=>fields.map(f=>cell(h[f])).join(','))].join('\r\n');await writeFile('exports/platform-accommodations.csv',csv);await writeFile('exports/platform-accommodations.csv.gz',gzipSync(csv));
console.log(JSON.stringify({sourceRecords:rows.length,matchedObservations:branded.length,hotels:hotels.length,roomAssertions:roomAssertions.length}));
