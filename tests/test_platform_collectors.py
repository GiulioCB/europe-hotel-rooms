import importlib.util,json,unittest
from pathlib import Path
def module(name,file):
    s=importlib.util.spec_from_file_location(name,Path(__file__).parents[1]/'scripts'/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
trip=module('trip','collect-platforms.py');other=module('other','collect-accommodations.py')
class PublicDirectoryTests(unittest.TestCase):
    def page(self,identity=123,precise=True):
        detail={'hotelBaseInfo':{'masterHotelId':identity,'nameInfo':{'name':'JI Hotel Beijing'},'cityName':'Beijing','countryName':'China'},'hotelPositionInfo':{'address':'Road 1, Beijing','lat':'39.9','lng':'116.4','preciseCoordinatesVisible':precise,'addressVisible':True},'hotelDescriptionInfo':{'lables':['Opened: 2024','Number of Rooms: 122']}}
        payload='Jd:'+json.dumps(['$','@10',None,{'hotelDetailResponse':detail}]);return '<script>self.__next_f.push('+json.dumps([1,payload])+')</script>'
    def test_explicit_room_total_is_separate_from_booking_room_quantity(self):
        record=trip.trip_details(self.page()+'<input name="rooms" value="1">','https://www.trip.com/hotels/beijing-hotel-detail-123/ji-hotel/')
        self.assertEqual(record['rooms'],122);self.assertEqual(record['lat'],39.9);self.assertEqual(record['platforms'],['Trip.com']);self.assertIsNone(record['website'])
    def test_wrong_property_identity_and_imprecise_coordinates_are_not_used(self):
        self.assertIsNone(trip.trip_details(self.page(999),'https://www.trip.com/hotels/beijing-hotel-detail-123/ji-hotel/'))
        self.assertIsNone(trip.trip_details(self.page(123,False),'https://www.trip.com/hotels/beijing-hotel-detail-123/ji-hotel/')['lat'])
    def test_apartment_bedroom_and_capacity_counts_do_not_become_hotel_rooms(self):
        r=other.osm_record({'id':1,'type':'node','lat':50,'lon':8,'tags':{'name':'Serviced stays','tourism':'apartment','brand':'Citadines','rooms':'2','beds':'500','capacity':'1000','apartments':'80'}},'DE')
        self.assertIsNone(r['rooms']);self.assertEqual(r['units'],80);self.assertEqual(r['propertyType'],'Apartment')
    def test_directory_links_do_not_consume_unrelated_apis_or_script(self):
        self.assertEqual(trip.trip_links('<a href="/hotels/beijing-hotel-detail-123/ji/">Hotel</a><a href="/restapi/soa2/">No</a>'),['https://www.trip.com/hotels/beijing-hotel-detail-123/ji/'])
if __name__=='__main__':unittest.main()
