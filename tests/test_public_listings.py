import importlib.util,json,unittest
from pathlib import Path
s=importlib.util.spec_from_file_location('listings',Path(__file__).resolve().parents[1]/'scripts/collect-public-listings.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class PublicListings(unittest.TestCase):
 def page(self,obj):return '<script type="application/ld+json">'+json.dumps(obj)+'</script>'
 def test_hotel_total_and_coordinates(self):
  r=m.parse(self.page({'@type':'Hotel','name':'Independent test','url':'https://example.com/hotel/test','address':{'streetAddress':'1 Test St','addressCountry':'DE'},'geo':{'latitude':52,'longitude':-1},'numberOfRooms':{'value':87}}),'https://example.com/hotel/test','Example',{'de':'DE'})
  self.assertEqual(r['rooms'],87);self.assertEqual(r['lon'],-1);self.assertNotIn('parentCompany',r)
 def test_apartment_bedrooms_are_not_property_room_inventory(self):
  r=m.parse(self.page({'@type':'Apartment','name':'Apartment test','address':{'streetAddress':'2 Test St','addressCountry':'DE'},'numberOfRooms':3}),'https://example.com/apt','Example',{'de':'DE'})
  self.assertIsNone(r['rooms']);self.assertNotIn('units',r)
 def test_recommendation_not_imported_as_primary_property(self):
  self.assertIsNone(m.parse(self.page({'@type':'Hotel','name':'Other','url':'https://example.com/other','address':{'addressCountry':'DE'}}),'https://example.com/primary','Example',{'de':'DE'}))
 def test_tan_uses_property_address_not_footer(self):
  text='<meta property="tan:country" content="Ireland"><meta property="tan:city" content="Dublin"><div class="pd_cont"><h1>Independent stay</h1><p>4 Main St, Dublin</p></div><address>Platform HQ London</address>'
  r=m.parse(text,'https://www.theapartmentnetwork.com/apartments/stay/','The Apartment Network',{'ireland':'IE'})
  self.assertEqual(r['address'],'4 Main St, Dublin');self.assertEqual(r['country'],'IE')
 def test_no_record_from_empty_shell(self):self.assertIsNone(m.parse('<html>Enable JavaScript</html>','https://example.com/hotel','Example',{}))
if __name__=='__main__':unittest.main()
