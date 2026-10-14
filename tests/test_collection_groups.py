import unittest
from scripts.collect_offers import source_groups
class CollectionGroups(unittest.TestCase):
    def test_same_and_overlapping_hosts_are_serialized(self):
        settings=[{'code':'a','domains':['one.test']},{'code':'b','domains':['two.test']},{'code':'c','domains':['one.test','two.test']},{'code':'d','domains':['other.test']}]
        groups=source_groups(settings)
        self.assertEqual({frozenset(x['code'] for x in group) for group in groups},{frozenset('abc'),frozenset('d')})
