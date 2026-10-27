import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import additional_sources as a

class GoogleOutcomes(unittest.TestCase):
    def run_case(self, rows, code=0):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            output=root/'.cache/google/VA/results.csv'
            output.parent.mkdir(parents=True)
            output.write_text('stale results')
            class Process:
                def wait(self, timeout): return code
            def launch(*args, **kwargs):
                self.assertFalse(output.exists())
                with output.open('w') as f:
                    writer=csv.DictWriter(f, fieldnames=['title','category','complete_address','link'])
                    writer.writeheader();writer.writerows(rows)
                return Process()
            with patch.object(a,'country_names',return_value={'IT':'Italy','VA':'Vatican'}), patch.object(a,'queries',return_value=['hotels Vatican']), patch.object(a.subprocess,'Popen',side_effect=launch):
                result=a.google('VA',root=root,binary=Path('/fake'))
            report=json.loads((root/'data/source-coverage/google-VA.json').read_text())
            return result,report
    def test_valid_foreign_hotels_warn_without_claiming_census(self):
        result,report=self.run_case([{'title':'Rome hotel','category':'Hotel','complete_address':'{"country":"IT"}','link':'https://www.google.com/maps/place/a'}])
        self.assertEqual(result,0);self.assertEqual(report['status'],'no_matching_hotels');self.assertFalse(report['complete_hotel_census'])
    def test_empty_or_malformed_results_still_fail(self):
        for rows in [[],[{'title':'bad'}]]:
            self.assertEqual(self.run_case(rows)[0],1)
    def test_process_failure_still_fails_without_matches(self):
        self.assertEqual(self.run_case([{'title':'Rome hotel','category':'Hotel','complete_address':'{"country":"IT"}','link':'https://www.google.com/maps/place/a'}],1)[0],1)
