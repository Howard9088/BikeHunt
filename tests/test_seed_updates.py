"""Offline regression tests for fail-closed published cold-cache recovery."""
from __future__ import annotations
import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, call
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.catalog.models import Money, Offer, ProductIdentity
from app.catalog.storage import OfferRepository, atomic_json
from app.public_recovery import baseline_writes, validate_baseline
from app.publication import build_publication
from app.updates import UpdateStore
from scripts import seed_updates as seed

PUBLIC_URL = "https://example.org/BikeHunt/"
COMMIT = "a" * 40
NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


def public_event(event_id):
    return {"id":event_id, "event_key":hashlib.sha256(f"mock-event-{event_id}".encode()).hexdigest(),
        "kind":"new_offer", "source_code":"mock", "source_name":"Mock 商城", "offer_id":f"mock-{event_id}",
        "name_zh":"Mock 骑行上衣", "category":"jerseys", "old_price":None, "new_price":"100.00",
        "currency":"USD", "stock":"in_stock", "observed_at":NOW.isoformat(), "url":f"https://example.org/product/{event_id}"}


def offer(identifier="known", **changes):
    return Offer(offer_id=identifier, source_code="mock", source_name="Mock 商城",
        identity=ProductIdentity(brand="Mock",model="Jersey"), name="Mock Jersey",
        url="https://example.org/product/"+identifier, price=Money(amount="100",currency="USD"),
        stock="in_stock", fetched_at=NOW, **changes)


def payload(events, cursor, offers=()):
    raw = [row.model_dump(mode="json") for row in offers]
    fx = {"snapshot_id":"fixture", "fetched_at":NOW.isoformat(), "stale":False}
    return {"generated_at":(NOW+timedelta(hours=1)).isoformat(),
        "publication":{"commit":COMMIT, "version":COMMIT+":"+(NOW+timedelta(hours=1)).isoformat()},
        "catalog":{"items":[], "fx":fx}, "updates":{"items":events,"cursor":cursor,"fx":fx},
        "details":{"family":{"variants":{"variant":{"offers":[{"offer":row} for row in raw],"fx":fx}}}},
        "collection_status":{"mock":{"source_code":"mock","attempted_at":NOW.isoformat(),"status":"success","errors":[]}}}


def release(data, schema=1):
    if schema==2:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);build_publication(copy.deepcopy(data),root/'out',root/'cache')
            return {path.name:path.read_bytes() for path in (root/'out/data').iterdir()}
    raw=json.dumps(data).encode()
    manifest={"schema_version":1,"commit":COMMIT,"generated_at":data['generated_at'],
        "version":data['publication']['version'],"snapshot":{"path":"data/site-data.json","bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}}
    return {"publication.json":json.dumps(manifest).encode(),"site-data.json":raw}


def responses(files):
    def read(request, **kwargs):
        return io.BytesIO(files[request.full_url.rsplit('/',1)[-1]])
    return read


class SeedUpdatesTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        atomic_json(self.root/'data/public_updates.json',[public_event(5)])

    def restore(self, data, schema=1):
        with patch.object(seed.urllib.request,'urlopen',side_effect=responses(release(data,schema))):
            return seed.restore_public_cursor(self.root,PUBLIC_URL)

    def next_event_id(self):
        return UpdateStore(self.root).capture([], [offer('brand-new')])[0]['id']

    def test_published_cursor_and_product_metadata_win_over_repository(self):
        e=public_event(86);e['product']={'offer_id':e['offer_id'],'url':e['url'],'name':'Jersey','brand':'Mock','model':'Jersey'}
        result=self.restore(payload([e],100))
        self.assertEqual(result,{'source':'published','restored':1,'cursor':100,'restored_offers':0})
        self.assertEqual(UpdateStore(self.root).cursor(),100)
        self.assertEqual(UpdateStore(self.root).latest()[0]['product']['name'],'Jersey')
        self.assertEqual(self.next_event_id(),101)

    def test_empty_events_reserve_and_publish_real_cursor(self):
        self.restore(payload([],200));self.assertEqual(UpdateStore(self.root).cursor(),200)
        self.assertEqual(self.next_event_id(),201)

    def test_network_failure_retries_then_fails_closed_without_seed(self):
        with patch.object(seed.urllib.request,'urlopen',side_effect=URLError('offline')) as request,patch.object(seed.time,'sleep') as sleep:
            with self.assertRaises(URLError):seed.restore_public_cursor(self.root,PUBLIC_URL)
        self.assertEqual(request.call_count,3);self.assertEqual(sleep.call_args_list,[call(1),call(2)])
        self.assertEqual(UpdateStore(self.root).cursor(),0)

    def test_invalid_manifest_digest_fails_atomically(self):
        files=release(payload([public_event(8)],8));files['site-data.json']+=b' '
        with patch.object(seed.urllib.request,'urlopen',side_effect=responses(files)),patch.object(seed.time,'sleep'):
            with self.assertRaises(ValueError):seed.restore_public_cursor(self.root,PUBLIC_URL)
        self.assertEqual(UpdateStore(self.root).latest(),[])
        self.assertFalse((self.root/'data/offers').exists())

    def test_schema_two_restores_latest_genuine_status_observation(self):
        o=offer();data=payload([],10,[o]);files=release(data,2)
        status=json.loads(files['verification.json']);status['offers'][o.offer_id]['fetched_at']=(NOW+timedelta(minutes=30)).isoformat()
        files['verification.json']=json.dumps(status).encode();m=json.loads(files['publication.json']);m['status'].update(bytes=len(files['verification.json']),sha256=hashlib.sha256(files['verification.json']).hexdigest());files['publication.json']=json.dumps(m).encode()
        with patch.object(seed.urllib.request,'urlopen',side_effect=responses(files)):seed.restore_public_cursor(self.root,PUBLIC_URL)
        restored=OfferRepository(self.root/'data').load()[0]
        self.assertEqual(restored.fetched_at,NOW+timedelta(minutes=30))
        self.assertEqual(restored.stock,'in_stock')

    def test_schema_two_mismatched_status_rejected(self):
        files=release(payload([],10,[offer()]),2);status=json.loads(files['verification.json']);status['snapshot_sha256']='f'*64
        files['verification.json']=json.dumps(status).encode();m=json.loads(files['publication.json']);m['status'].update(bytes=len(files['verification.json']),sha256=hashlib.sha256(files['verification.json']).hexdigest());files['publication.json']=json.dumps(m).encode()
        with patch.object(seed.urllib.request,'urlopen',side_effect=responses(files)),patch.object(seed.time,'sleep'):
            with self.assertRaises(ValueError):seed.restore_public_cursor(self.root,PUBLIC_URL)

    def test_cold_cache_known_unchanged_offer_creates_no_duplicate(self):
        o=offer();self.restore(payload([public_event(86)],100,[o]))
        repo=OfferRepository(self.root/'data');repo.save('mock',[o.model_copy(update={'fetched_at':NOW+timedelta(hours=2)})],NOW+timedelta(hours=2),[])
        self.assertEqual(UpdateStore(self.root).cursor(),100)
        self.assertEqual(len(UpdateStore(self.root).latest()),1)

    def test_real_price_stock_and_new_offer_changes_still_emit(self):
        o=offer();self.restore(payload([],100,[o]));repo=OfferRepository(self.root/'data')
        fresh=o.model_copy(update={'fetched_at':NOW+timedelta(hours=2),'price':Money(amount='90',currency='USD')})
        repo.save('mock',[fresh],NOW+timedelta(hours=2),[])
        fresh=fresh.model_copy(update={'stock':'out_of_stock','fetched_at':NOW+timedelta(hours=3)})
        repo.save('mock',[fresh,offer('different')],NOW+timedelta(hours=3),[])
        self.assertEqual({e['kind'] for e in UpdateStore(self.root).latest()},{'price_changed','inventory_changed','new_offer'})
        self.assertEqual(UpdateStore(self.root).cursor(),103)

    def test_preserves_newer_local_offer_and_outstanding_cooldown(self):
        o=offer();local=o.model_copy(update={'fetched_at':NOW+timedelta(hours=2),'stock':'out_of_stock','collection_state':'retained'})
        atomic_json(self.root/'data/offers/mock.json',{'source_code':'mock','offers':[local.model_dump(mode='json')]})
        retry=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        error={'url':o.url,'error':'HTTP 429','retry_at':retry}
        atomic_json(self.root/'data/collection_status/mock.json',{'source_code':'mock','attempted_at':(NOW-timedelta(hours=1)).isoformat(),'status':'failed','errors':[error]})
        self.restore(payload([],100,[o]));restored=OfferRepository(self.root/'data').load()[0]
        self.assertEqual(restored.fetched_at,local.fetched_at);self.assertEqual(restored.stock,'out_of_stock');self.assertEqual(restored.collection_state,'retained')
        self.assertIn(error,json.loads((self.root/'data/collection_status/mock.json').read_text())['errors'])

    def test_warm_duplicate_offer_ids_keep_newest_observation_in_any_order(self):
        original = offer()
        newer = original.model_copy(update={'fetched_at':NOW+timedelta(hours=2),
            'price':Money(amount='90',currency='USD'),'stock':'out_of_stock'})
        unknown = original.model_copy(update={'fetched_at':None})
        for duplicates in ([original,newer],[newer,original],[newer,unknown]):
            with self.subTest(order=[row.fetched_at for row in duplicates]):
                atomic_json(self.root/'data/offers/mock.json',{'source_code':'mock',
                    'offers':[row.model_dump(mode='json') for row in duplicates]})
                result = self.restore(payload([],100,[original]))
                raw = json.loads((self.root/'data/offers/mock.json').read_text())['offers']
                self.assertEqual(len(raw),1)
                selected = Offer.model_validate(raw[0])
                self.assertEqual(selected.fetched_at,newer.fetched_at)
                self.assertEqual(selected.price,newer.price)
                self.assertEqual(selected.stock,newer.stock)
                self.assertEqual(result['restored_offers'],0)
                # Canonicalization itself emits no change; a repeated same-state
                # collection must also remain quiet against this exact baseline.
                self.assertEqual(UpdateStore(self.root).capture([selected],
                    [selected.model_copy(update={'fetched_at':NOW+timedelta(hours=3)})]),[])

    def test_duplicate_equal_or_unknown_observations_use_repository_last_row(self):
        original = offer()
        changed = original.model_copy(update={'price':Money(amount='90',currency='USD'),
            'stock':'out_of_stock','collection_state':'retained'})
        for observed in (NOW,None):
            with self.subTest(observed=observed):
                first = original.model_copy(update={'fetched_at':observed})
                last = changed.model_copy(update={'fetched_at':observed})
                atomic_json(self.root/'data/offers/mock.json',{'source_code':'mock',
                    'offers':[first.model_dump(mode='json'),last.model_dump(mode='json')]})
                self.restore(payload([],100,[first]))
                raw = json.loads((self.root/'data/offers/mock.json').read_text())['offers']
                self.assertEqual(len(raw),1)
                self.assertEqual(Offer.model_validate(raw[0]),last)

    def test_retained_or_unknown_time_is_never_refreshed_to_now(self):
        o=offer().model_copy(update={'fetched_at':None,'collection_state':'retained'})
        self.restore(payload([],100,[o]));restored=OfferRepository(self.root/'data').load()[0]
        self.assertIsNone(restored.fetched_at);self.assertEqual(restored.collection_state,'retained')

    def test_existing_database_still_recovers_missing_offer_baselines(self):
        seed.restore_public_cursor(self.root)
        self.restore(payload([public_event(8)],10,[offer()]))
        self.assertEqual(UpdateStore(self.root).cursor(),10);self.assertEqual(len(OfferRepository(self.root/'data').load()),1)

    def test_conflicting_local_event_id_fails_closed(self):
        seed.restore_public_cursor(self.root);e=public_event(5);e['event_key']='f'*64
        with self.assertRaises(ValueError):self.restore(payload([e],5,[offer()]))
        self.assertFalse((self.root/'data/offers').exists())

    def test_snapshot_over_ten_megabytes_and_bounded_reads(self):
        data=payload([],100);data['padding']='x'*(11*1024*1024);files=release(data)
        class Bounded(io.BytesIO):
            def read(self,n=-1):
                if n<0:raise AssertionError('Unbounded read')
                return super().read(n)
        with patch.object(seed.urllib.request,'urlopen',side_effect=lambda r,**kw:Bounded(files[r.full_url.rsplit('/',1)[-1]])):
            self.assertEqual(seed.restore_public_cursor(self.root,PUBLIC_URL)['cursor'],100)

    def test_oversized_snapshot_is_rejected_before_download(self):
        files=release(payload([],100));m=json.loads(files['publication.json']);m['snapshot']['bytes']=seed.MAX_RESPONSE_BYTES+1;files['publication.json']=json.dumps(m).encode()
        with patch.object(seed.urllib.request,'urlopen',side_effect=responses(files)) as request,patch.object(seed.time,'sleep'):
            with self.assertRaises(ValueError):seed.restore_public_cursor(self.root,PUBLIC_URL)
        self.assertEqual(request.call_count,3)

    def test_checkpoint_reserves_ids_without_creating_events(self):
        self.write_checkpoint(1257);(self.root/'data/public_updates.json').unlink()
        self.assertEqual(seed.restore_public_cursor(self.root)['cursor'],1257)
        self.assertEqual(UpdateStore(self.root).latest(),[]);self.assertEqual(self.next_event_id(),1258)

    def write_checkpoint(self,cursor):
        atomic_json(self.root/'data/event_cursor_checkpoint.json',{'schema_version':1,'cursor':cursor,'commit':COMMIT,'generated_at':NOW.isoformat(),'snapshot_sha256':'b'*64})

    def test_newer_local_and_live_cursors_win_over_checkpoint(self):
        self.write_checkpoint(100);self.restore(payload([],200));self.assertEqual(seed.restore_public_cursor(self.root)['cursor'],200)
        self.restore(payload([],300));self.assertEqual(UpdateStore(self.root).cursor(),300)

    def test_invalid_checkpoint_rejected(self):
        for value in (True,-1,2**63-1):
            with self.subTest(value=value):
                self.write_checkpoint(value)
                with self.assertRaises(ValueError):seed.restore_public_cursor(self.root)

    def test_invalid_event_fields_and_duplicate_keys_rejected(self):
        for change in ({'id':True},{'new_price':'NaN'},{'old_price':'-1'},{'currency':'usd'},{'stock':'guessed'}, {'observed_at':'2026-10-14T00:00:00'},{'url':'http://example.org/a'},{'event_key':'invalid'},{'private':'bad'}, {'recovered_history':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):seed.validate_events([public_event(8)|change],8)
        with self.assertRaises(ValueError):seed.validate_events([public_event(8),public_event(8)],8)

    def test_repository_seed_invalid_fails_and_missing_is_first_release(self):
        atomic_json(self.root/'data/public_updates.json',[public_event(5)|{'new_price':'NaN'}])
        with self.assertRaises(ValueError):seed.restore_public_cursor(self.root)
        (self.root/'data/public_updates.json').unlink();self.assertEqual(seed.restore_public_cursor(self.root)['cursor'],0)


class ActualHistoryRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name);(self.root/'data').mkdir()
        source=Path(__file__).resolve().parents[1]/'data'
        for name in ('event_cursor_checkpoint.json','event_history_recovery.json'):shutil.copy(source/name,self.root/'data'/name)
        self.artifact=seed.history_recovery(self.root,seed.checkpoint_cursor(self.root))

    def test_proven_replays_retained_but_hidden_history_restored_once(self):
        rows=self.artifact['replayed_events'];data=payload(rows,1162)
        # Fixtures contain genuine October14 later timestamps; schema1 validates them against its publication time.
        data['generated_at']=self.artifact['affected_publication']['generated_at'];data['publication']['version']=COMMIT+':'+data['generated_at']
        with patch.object(seed,'download_public_snapshot',return_value=(data,None)):
            result=seed.restore_public_cursor(self.root,PUBLIC_URL)
        self.assertEqual((result['suppressed_replays'],result['recovered_history'],result['cursor']),(100,100,1357))
        store=UpdateStore(self.root);visible=store.latest(limit=100)
        self.assertEqual(len(visible),100);self.assertTrue(all(e['recovered_history'] for e in visible))
        self.assertEqual({e['event_key'] for e in visible},{e['event_key'] for e in self.artifact['restored_events']})
        self.assertEqual([e['original_id'] for e in visible],list(range(1257,1157,-1)))
        self.assertEqual(store.pending(1162),[])
        with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],200)
        # Cache restore from the repaired public window keeps markers and does not duplicate history.
        data['updates'].update(items=visible,cursor=1357)
        with patch.object(seed,'download_public_snapshot',return_value=(data,None)):
            again=seed.restore_public_cursor(self.root,PUBLIC_URL)
        self.assertEqual(again['recovered_history'],0);self.assertEqual(store.cursor(),1357)
        new=store.capture([],[offer('actually-new')])[0];self.assertEqual(new['id'],1358)
        self.assertEqual([e['id'] for e in store.pending(1257)],[1358])

    def test_completed_history_ages_out_without_resurrection_on_cold_cache(self):
        for count in (1, 100):
            with self.subTest(genuine_events=count), tempfile.TemporaryDirectory() as tmp:
                warm, cold = Path(tmp)/'warm', Path(tmp)/'cold'
                shutil.copytree(self.root/'data', warm/'data')
                seed.restore_public_cursor(warm)
                store = UpdateStore(warm)
                for number in range(count):
                    store.capture([], [offer('genuine-' + str(number))])
                latest, cursor, markers = store.latest(limit=100), store.cursor(), store.history_recovery()
                self.assertEqual(sum(bool(row.get('recovered_history')) for row in latest), 100-count)
                shutil.copytree(self.root/'data', cold/'data')
                data = payload(latest, cursor)
                data['updates']['history_recovery'] = markers
                with patch.object(seed,'download_public_snapshot',return_value=(data,None)):
                    result = seed.restore_public_cursor(cold, PUBLIC_URL)
                self.assertEqual(result['recovered_history'], 0)
                cold_store = UpdateStore(cold)
                self.assertEqual(cold_store.cursor(), cursor)
                self.assertEqual([(row['id'],row['event_key']) for row in cold_store.latest(limit=100)],
                                 [(row['id'],row['event_key']) for row in latest])
                self.assertEqual(cold_store.history_recovery(), markers)
                # A publication from that recovered cold cache must merge cleanly
                # back into the earlier warm cache, retaining the same key/ID pairs.
                data['updates'].update(items=cold_store.latest(limit=100),history_recovery=cold_store.history_recovery())
                with patch.object(seed,'download_public_snapshot',return_value=(data,None)):
                    self.assertEqual(seed.restore_public_cursor(warm, PUBLIC_URL)['recovered_history'], 0)
                self.assertEqual(store.cursor(), cursor)

    def test_warm_cache_more_than_public_window_uses_only_exact_incident_proof(self):
        rows = copy.deepcopy(self.artifact['replayed_events'])
        template = rows[0]
        for number in range(20):
            rows.append(template | {'id':900+number,'event_key':hashlib.sha256(f'extra-replay-{number}'.encode()).hexdigest()})
        kept = [template | {'id':950,'event_key':'1'*64,'new_price':'1'},
                template | {'id':951,'event_key':'2'*64,'offer_id':'unseen-offer'},
                template | {'id':952,'event_key':'3'*64,'observed_at':'2026-10-14T00:00:00+00:00'},
                template | {'id':2000,'event_key':'4'*64}]
        rows.extend(kept)
        store = UpdateStore(self.root)
        with store.connect() as db:
            columns = seed.EVENT_FIELDS
            db.executemany('INSERT INTO events ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
                           [tuple(row[field] for field in columns) for row in rows])
        result = seed.restore_public_cursor(self.root)
        self.assertEqual(result['suppressed_replays'],120)
        self.assertEqual(result['cursor'],2100)
        self.assertEqual({row['event_key'] for row in store.pending(0)},{row['event_key'] for row in kept})
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],224)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM suppressed_events').fetchone()[0],120)
        self.assertEqual(seed.restore_public_cursor(self.root)['suppressed_replays'],0)

    def test_changed_price_stock_url_or_currency_never_suppressed(self):
        for field,value in (('new_price','1'),('currency','JPY'),('stock','unknown'),('url','https://example.org/changed')):
            artifact=copy.deepcopy(self.artifact);artifact['replayed_events'][0][field]=value
            atomic_json(self.root/'data/event_history_recovery.json',artifact)
            with self.subTest(field=field),self.assertRaises(ValueError):seed.history_recovery(self.root,1257)

    def test_unknown_current_event_is_preserved(self):
        seed.restore_public_cursor(self.root)
        store=UpdateStore(self.root);event=store.capture([],[offer('new-independent')])[0]
        seed.restore_public_cursor(self.root)
        self.assertEqual(store.pending(1257)[0]['event_key'],event['event_key'])


if __name__=='__main__':unittest.main(verbosity=2)
