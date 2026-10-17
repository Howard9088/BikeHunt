"""Public country forms share robots, TLS, throttling and deferral contracts."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.collectors.transport import PublicPageFetcher, CollectionError, SourceDeferred, USER_AGENT

NOW = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
ACTION = 'https://gobik.com/en/localization'
PRODUCT = 'https://gobik.com/en/products/jersey'
FIELDS = {'form_type':'localization', 'utf8':'✓', '_method':'put',
          'return_to':'/en/products/jersey', 'country_code':'ES'}


class PublicLocalizationTests(unittest.TestCase):
    def fetcher(self, *, robots=b'User-agent: *\nAllow: /', status=302,
                location=PRODUCT, error=None, response_url=ACTION):
        calls = []; sleeps = []
        def get(url, **kwargs):
            calls.append(('GET', url, kwargs))
            return SimpleNamespace(status=200, body=robots if url.endswith('/robots.txt') else b'fresh product',
                                   headers={}, cookies={}, url=url)
        def post(url, **kwargs):
            calls.append(('POST', url, kwargs))
            if error:
                raise error
            headers={'Retry-After':'3600'}
            if location is not None:
                headers['Location']=location
            return SimpleNamespace(status=status, body=b'', headers=headers,
                cookies={'localization':'source-set-value'}, url=response_url)
        return PublicPageFetcher({'gobik.com'}, request=get, post_request=post, sleep=sleeps.append,
            clock=lambda:100, utcnow=lambda:NOW), calls, sleeps

    def test_multipart_post_uses_server_cookie_and_fresh_get_without_auto_redirects(self):
        fetcher, calls, sleeps = self.fetcher()
        capture = fetcher.submit_public_localization(ACTION, FIELDS, PRODUCT)
        self.assertEqual([(method,url) for method,url,_ in calls],
            [('GET','https://gobik.com/robots.txt'), ('POST',ACTION), ('GET',PRODUCT)])
        kwargs = calls[1][2]
        self.assertFalse(kwargs['follow_redirects']); self.assertEqual(kwargs['max_redirects'],0)
        self.assertEqual(kwargs['headers']['User-Agent'], USER_AGENT)
        self.assertIsInstance(kwargs['verify'], str)
        body = kwargs['data'].decode(); boundary=kwargs['headers']['Content-Type'].split('boundary=')[1]
        self.assertTrue(body.startswith('--'+boundary+'\r\n'))
        self.assertTrue(body.endswith('--'+boundary+'--\r\n'))
        for name,value in FIELDS.items():
            self.assertIn(f'name="{name}"\r\n\r\n{value}\r\n', body)
        self.assertEqual(calls[2][2]['cookies']['localization'],'source-set-value')
        self.assertEqual(capture.url, PRODUCT); self.assertEqual(capture.observed_at,NOW)
        self.assertTrue(sleeps and min(sleeps)>=1)

    def test_both_post_and_return_path_require_robots_permission(self):
        for disallowed in ['/en/localization', '/en/products/']:
            fetcher,calls,_=self.fetcher(robots=('User-agent: *\nDisallow: '+disallowed).encode())
            with self.assertRaises(CollectionError):
                fetcher.submit_public_localization(ACTION,FIELDS,PRODUCT)
            self.assertEqual(len(calls),1)

    def test_post_429_or_retry_after_503_defers_host(self):
        for status in [429,503]:
            fetcher,calls,_=self.fetcher(status=status)
            with self.assertRaises(SourceDeferred):
                fetcher.submit_public_localization(ACTION,FIELDS,PRODUCT)
            self.assertIn('gobik.com',fetcher.deferred)
            count=len(calls)
            with self.assertRaises(SourceDeferred):
                fetcher.fetch(PRODUCT)
            self.assertEqual(len(calls),count)

    def test_uncertain_or_server_failed_form_is_not_retried(self):
        for kwargs in [{'error':OSError('timeout')},{'status':500}]:
            fetcher,calls,_=self.fetcher(**kwargs)
            with self.assertRaises(CollectionError):
                fetcher.submit_public_localization(ACTION,FIELDS,PRODUCT)
            self.assertEqual(sum(method=='POST' for method,_,_ in calls),1)

    def test_missing_cross_domain_or_different_product_redirect_never_followed(self):
        for target in [None, 'https://other.example/en/products/jersey', PRODUCT+'?country=ES',
                       PRODUCT.replace('jersey','other')]:
            fetcher,calls,_=self.fetcher(location=target)
            with self.assertRaises(CollectionError):
                fetcher.submit_public_localization(ACTION,FIELDS,PRODUCT)
            self.assertEqual(len(calls),2)

    def test_unexpected_post_redirect_response_fails_before_followup_get(self):
        fetcher,calls,_=self.fetcher(response_url=PRODUCT)
        with self.assertRaises(CollectionError):
            fetcher.submit_public_localization(ACTION,FIELDS,PRODUCT)
        self.assertEqual(len(calls),2)

    def test_rejects_arbitrary_fields_actions_and_multiline_values_before_network(self):
        cases=[(ACTION,{**FIELDS,'token':'not allowed'},PRODUCT),
               (ACTION,{**FIELDS,'return_to':'/another'},PRODUCT),
               (ACTION,{**FIELDS,'country_code':'ES\r\nHeader: value'},PRODUCT),
               ('https://gobik.com/en/cart/add',FIELDS,PRODUCT),
               ('https://other.example/en/localization',FIELDS,PRODUCT),
               (ACTION,FIELDS,PRODUCT.replace('gobik.com','other.example'))]
        for action,fields,target in cases:
            fetcher,calls,_=self.fetcher()
            with self.assertRaises(CollectionError):
                fetcher.submit_public_localization(action,fields,target)
            self.assertFalse(calls)


if __name__ == '__main__':
    unittest.main()
