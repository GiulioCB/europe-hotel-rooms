// A research catalogue identifies trading brands and supplied parent mappings.
// It does not establish who owns or operates an individual property.
export const foldBrand=value=>String(value||'').normalize('NFKD').replace(/\p{M}/gu,'').toLowerCase().replace(/&/g,' and ').replace(/\+/g,' plus ').replace(/[^\p{L}\p{N}]+/gu,' ').trim().replace(/\s+/g,' ');
const HOSTS={marriott:'marriott.com',hilton:'hilton.com',ihg:'ihg.com',accor:'accor.com',hyatt:'hyatt.com',wyndham:'wyndhamhotels.com',choice:'choicehotels.com',radisson:'radissonhotels.com',minor:'minorhotels.com',melia:'melia.com'};
const validCoordinates=h=>Number.isFinite(h.lat)&&Number.isFinite(h.lon)&&Math.abs(h.lat)<=90&&Math.abs(h.lon)<=180;
const scalar=v=>typeof v==='string'||typeof v==='number'?String(v):'';
export function createBrandMatcher(catalogue){
 const exact=new Map(),trie=new Map(),han=[],entries=catalogue.brands||[];
 for(const entry of entries)for(const alias of entry.aliases||[entry.name]){
  const key=foldBrand(alias);if(!key)continue;
  if(/\p{Script=Han}/u.test(key)&&key.length>=3)han.push({entry,alias:key});
  if(!exact.has(key))exact.set(key,[]);if(!exact.get(key).some(e=>e.id===entry.id))exact.get(key).push(entry);
  let node=trie;for(const token of key.split(' ')){if(!node.has(token))node.set(token,new Map());node=node.get(token)}
  const hits=node.get('');if(hits){if(!hits.some(e=>e.entry.id===entry.id))hits.push({entry,alias:key})}else node.set('',[{entry,alias:key}]);
 }
 function websiteSupports(h,entry){let host;try{host=new URL(h.website).hostname.toLowerCase()}catch{return false}
  return entry.parents.some(parent=>Object.entries(HOSTS).some(([key,domain])=>foldBrand(parent).includes(key)&&(host===domain||host.endsWith('.'+domain))))||((host==='nh-hotels.com'||host.endsWith('.nh-hotels.com'))&&entry.name.startsWith('NH'));
 }
 return h=>{
  const reported=h.originalBrand??h.brand;
  const explicit=exact.get(foldBrand(reported));
  if(explicit?.length===1&&!h.brandNameInferred)return {entry:explicit[0],basis:'Source reports brand',status:'source_brand',evidence:scalar(reported)};
  const words=foldBrand(h.name).split(' '),hits=[];
  const fullName=foldBrand(h.name);for(const hit of han)if(fullName.includes(hit.alias))hits.push({...hit,backed:false,score:hit.alias.length});
  for(let start=0;start<words.length;start++){let node=trie;
   for(let end=start;end<words.length&&node.has(words[end]);end++){node=node.get(words[end]);
    for(const hit of node.get('')||[]){if(hit.entry.nameMatchCountries&&!hit.entry.nameMatchCountries.includes(h.country))continue;const backed=websiteSupports(h,hit.entry),distinctive=hit.entry.nameMatchingAllowed&&hit.alias.length>=4;
     if(distinctive||backed)hits.push({...hit,backed,score:hit.alias.length});}
   }
  }
  hits.sort((a,b)=>b.score-a.score||Number(b.backed)-Number(a.backed));
  const best=hits[0];if(!best||hits.some(hit=>hit.score===best.score&&hit.entry.id!==best.entry.id))return null;
  return {entry:best.entry,basis:best.backed?'Hotel name and brand website':'Hotel name match · needs review',status:best.backed?'name_and_website':'name_match',evidence:scalar(h.name)};
 };
}

function propertyKey(value){try{const url=new URL(value),host=url.hostname.toLowerCase().replace(/^www\./,'');let path=url.pathname.toLowerCase().replace(/\/$/,'');
 if(host.endsWith('marriott.com')){const code=path.match(/\/hotels\/(?:travel\/)?([a-z0-9]{5})(?:-|\/|$)/);if(code)return 'marriott:'+code[1]}
 if(host.endsWith('accor.com')){const code=path.match(/\/hotel\/([a-z0-9]{4})(?:\/|$)/);if(code)return 'accor:'+code[1]}
 if(path.length<4&&Object.values(HOSTS).some(domain=>host===domain||host.endsWith('.'+domain)))return null;
 return host+path;
 }catch{return null}}

export function mergeHotelObservations(base,additional,{append=true,cloneBase=true}={}){
 const records=cloneBase?base.map(h=>({...h})):base,ids=new Map(records.map(h=>[h.id,h])),sites=new Map(),names=new Map();
 function index(h){const site=propertyKey(h.website),name=h.country+'|'+foldBrand(h.name);if(site){if(!sites.has(site))sites.set(site,[]);sites.get(site).push(h)}if(!names.has(name))names.set(name,[]);names.get(name).push(h)}
 records.forEach(index);
 for(const incoming of additional){if(!incoming?.id||!incoming.name)continue;let match=ids.get(incoming.id);
  const site=propertyKey(incoming.website),siteCandidates=site?sites.get(site)||[]:[];
  if(!match&&siteCandidates.length===1&&siteCandidates[0].country===incoming.country&&(!validCoordinates(siteCandidates[0])||!validCoordinates(incoming)||(Math.abs(siteCandidates[0].lat-incoming.lat)<.01&&Math.abs(siteCandidates[0].lon-incoming.lon)<.01)))match=siteCandidates[0];
  if(!match){const candidates=(names.get(incoming.country+'|'+foldBrand(incoming.name))||[]).filter(h=>{
    if(validCoordinates(h)&&validCoordinates(incoming))return Math.abs(h.lat-incoming.lat)<.001&&Math.abs(h.lon-incoming.lon)<.001;
    return (h.city&&incoming.city&&foldBrand(h.city)===foldBrand(incoming.city))||(h.postcode&&incoming.postcode&&h.postcode===incoming.postcode);
   });if(candidates.length===1)match=candidates[0];}
  if(!match){if(append){const h={...incoming};records.push(h);ids.set(h.id,h);index(h)}continue}
  ids.set(incoming.id,match);
  if(incoming.platforms)match.platforms=[...new Set([...(match.platforms||[]),...incoming.platforms])];
  if(incoming.platformUrls)match.platformUrls={...match.platformUrls,...incoming.platformUrls};
  match.otherDirectoryListings=[...(match.otherDirectoryListings||[]),{id:incoming.id,source:incoming.source,url:incoming.sourceUrl}].filter((v,i,a)=>a.findIndex(x=>x.id===v.id&&x.url===v.url)===i);
  if(!validCoordinates(match)&&validCoordinates(incoming)){match.lat=incoming.lat;match.lon=incoming.lon;match.fieldEvidence={...match.fieldEvidence,coordinates:{source:incoming.source,sourceUrl:incoming.sourceUrl,collectedAt:incoming.collectedAt}};}
  for(const field of ['rooms','units','unitsType','unitsSourceUrl','unitsEvidence','parkingSpaces','city','region','address','website','operator','postcode'])if((match[field]===null||match[field]===undefined||match[field]==='')&&incoming[field]!==null&&incoming[field]!==undefined&&incoming[field]!==''){
   match[field]=incoming[field];match.fieldEvidence={...match.fieldEvidence,[field]:{source:incoming.source,sourceUrl:incoming.roomsSourceUrl&&field==='rooms'?incoming.roomsSourceUrl:incoming.sourceUrl,collectedAt:incoming.collectedAt}};
   if(field==='rooms')for(const key of ['roomsSourceUrl','roomsEvidence','roomsObservedAt','roomsStatus'])if(incoming[key])match[key]=incoming[key];
  }
  if(Number.isFinite(match.rooms)&&Number.isFinite(incoming.rooms)&&match.rooms!==incoming.rooms)match.roomCountConflict='Different published room totals: '+match.rooms+' and '+incoming.rooms;
  if(incoming.googleMapsUrl)match.googleMapsUrl=incoming.googleMapsUrl;
 }
 return records;
}

export function applyRequestedBrands(inventory,catalogue,{mutate=false}={}){
 const matcher=createBrandMatcher(catalogue),coverage=new Map((catalogue.brands||[]).map(b=>[b.id,{id:b.id,name:b.name,parents:b.parents,aliases:b.aliases,origins:b.origins,count:0,mapped:0,nameMatches:0,countries:[]}]))
 const hotels=inventory.hotels.map(original=>{const h=mutate?original:{...original},match=matcher(h);
  if(!match)return {...h,requestedBrandId:null,parentCompanies:[],parentCompany:null};
  const {entry}=match;h.originalBrand=h.originalBrand??h.brand;h.brand=entry.name;h.brandId=entry.id;h.requestedBrandId=entry.id;h.requestedBrandMatch=match.status;h.brandMatchBasis=match.basis;h.brandMatchEvidence=match.evidence;
  h.parentCompanies=[...entry.parents];h.parentCompany=entry.parents.length===1?entry.parents[0]:null;h.parentMappingBasis='Parent grouping from your supplied research list';h.brandNameInferred=match.status!=='source_brand';
  const counts=coverage.get(entry.id);counts.count++;if(validCoordinates(h))counts.mapped++;if(match.status!=='source_brand')counts.nameMatches++;if(!counts.countries.includes(h.country))counts.countries.push(h.country);
  return h;
 });
 const brands=new Map();for(const h of hotels){if(!brands.has(h.brandId))brands.set(h.brandId,{id:h.brandId,name:h.brand,group:h.group,logo:h.logo||null,website:h.brandSourceUrl||null,count:0});brands.get(h.brandId).count++}
 const requestedBrands=[...coverage.values()];for(const b of requestedBrands)if(!brands.has(b.id))brands.set(b.id,{id:b.id,name:b.name,count:0,requested:true});
 const parents=new Map();for(const h of hotels)for(const name of h.parentCompanies||[])parents.set(name,(parents.get(name)||0)+1);
 return {...inventory,hotels,brands:[...brands.values()].sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name)),requestedBrands,
  parentCompanies:[...parents].map(([name,count])=>({name,count})),requestedCoverage:{catalogueEntries:requestedBrands.length,matchedEntries:requestedBrands.filter(b=>b.count).length,mappedEntries:requestedBrands.filter(b=>b.mapped).length,matchedHotels:hotels.filter(h=>h.requestedBrandId).length,mappedHotels:hotels.filter(h=>h.requestedBrandId&&validCoordinates(h)).length,nameMatchedHotels:hotels.filter(h=>h.brandNameInferred).length,unmatchedEntries:requestedBrands.filter(b=>!b.count).length,mappingBasis:catalogue.mappingBasis}};
}
