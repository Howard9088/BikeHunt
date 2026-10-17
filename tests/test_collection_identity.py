import unittest
import tempfile
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone
from app.catalog.storage import OfferRepository, collection_url_key, collection_failed
from app.catalog.models import Offer, ProductIdentity, Money

T = datetime(2026, 10, 17, tzinfo=timezone.utc)

def row(code, key, url, collection=None, at=T):
    return Offer(offer_id=key, source_code=code, source_name=code,
        identity=ProductIdentity(brand=code, model=key, size='M'), name=key,
        url=url, collection_url=collection, price=Money(amount='10', currency='CNY'),
        stock='in_stock', fetched_at=at)

def test_query_identity():
    a='https://www.decathlon.com.cn/product-detail?model_code=8969603&utm_source=x&dsm_code=367685'
    assert collection_url_key(a)=='https://www.decathlon.com.cn/product-detail?dsm_code=367685&model_code=8969603'
    assert collection_url_key(a)!=collection_url_key(a.replace('8969603','8987878'))
    assert collection_url_key('https://www.oakley.com/en-us/product/FOS1?utm_x=a&variant=123')=='https://www.oakley.com/en-us/product/FOS1?variant=123'
    assert collection_url_key('https://gobik.com/en/products/foo?variant=123')=='https://gobik.com/en/products/foo'

def exercise(tmp_path, code, aurl, burl, base=None):
    data=tmp_path/'data'; data.mkdir()
    (data/'sources.json').write_text('[]')
    repo=OfferRepository(data)
    a=row(code,'a',base or aurl,aurl); b=row(code,'b',base or burl,burl)
    repo.save(code,[a,b],T,[])
    fresh=a.model_copy(update={'fetched_at':T+timedelta(minutes=1)})
    repo.save(code,[fresh],T+timedelta(minutes=2),[{'url':burl,'error':'failed'}])
    loaded={r.offer_id:r for r in repo.load()}
    assert loaded['a'].collection_state=='current'
    assert loaded['a'].fetched_at==fresh.fetched_at
    assert loaded['b'].collection_state=='retained'
    assert loaded['b'].fetched_at==T
    status=json.loads((data/'collection_status'/f'{code}.json').read_text())
    assert not collection_failed(fresh.model_dump(mode='json'), status)
    assert collection_failed(b, status)
    assert len(loaded)==2
    return repo, fresh, b

def test_decathlon_sibling_failure(tmp_path):
    exercise(tmp_path,'decathlon_cn','https://www.decathlon.com.cn/product-detail?dsm_code=367685&model_code=8969603','https://www.decathlon.com.cn/product-detail?dsm_code=355348')

def test_oakley_variant_failure(tmp_path):
    base='https://www.oakley.com/en-us/product/FOS1'
    exercise(tmp_path,'oakley',base+'?variant=123',base+'?variant=456',base)

def test_canonical_failure_does_not_renew_or_invalidate_exact_success(tmp_path):
    base='https://www.oakley.com/en-us/product/FOS1'
    repo,a,b=exercise(tmp_path,'oakley',base+'?variant=123',base+'?variant=456',base)
    repo.save('oakley',[a],T+timedelta(minutes=3),[{'url':base,'error':'failed'}])
    loaded={r.offer_id:r for r in repo.load()}
    assert loaded['a'].collection_state=='current'
    assert loaded['b'].collection_state=='retained'
    assert loaded['b'].fetched_at==T
    repo.save('oakley',[],T+timedelta(minutes=4),[{'url':base,'error':'failed'}])
    assert all(r.collection_state=='retained' for r in repo.load())

class CollectionIdentityTests(unittest.TestCase):
    def test_identity(self):
        test_query_identity()
    def test_decathlon(self):
        with tempfile.TemporaryDirectory() as temp:
            test_decathlon_sibling_failure(Path(temp))
    def test_oakley(self):
        with tempfile.TemporaryDirectory() as temp:
            test_oakley_variant_failure(Path(temp))
    def test_canonical(self):
        with tempfile.TemporaryDirectory() as temp:
            test_canonical_failure_does_not_renew_or_invalidate_exact_success(Path(temp))

    def test_sanitized_observations(self):
        from app.public_status import public_collection_status
        result=public_collection_status({'oakley': {'successful_offer_observations': {
            'oakley-good': T.isoformat(), 'bad secret value': T.isoformat(),
            'bad-time': 'yesterday', 'naive': '2026-10-17T01:00:00'}}}, set())
        assert result['oakley']['successful_offer_observations']=={'oakley-good':T.isoformat()}

    def test_success_marker_must_match_exact_observation(self):
        url='https://www.oakley.com/en-us/product/FOS1?variant=123'
        item=row('oakley','a',url,url)
        status={'status':'partial','errors':[{'url':url}],
                'successful_offer_observations':{'a':(T+timedelta(minutes=1)).isoformat()}}
        assert collection_failed(item,status)
