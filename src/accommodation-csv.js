export function accommodationCsvCell(value){
 if(typeof value==='number'&&!Number.isFinite(value))value='';
 let text=Array.isArray(value)?value.join(' / '):value&&typeof value==='object'?JSON.stringify(value):String(value??'');
 if(typeof value!=='number')text=text.replace(/^[=+@\-\t\r]/,"'$&");
 return '"'+text.replace(/"/g,'""')+'"';
}
