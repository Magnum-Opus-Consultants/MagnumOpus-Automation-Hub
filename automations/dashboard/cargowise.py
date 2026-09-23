"""A small CargoWise (WiseGrid) OData client.

The AWA data-services scripts each carry their own copy of this handshake. This
is the same flow, in one place, for the reports the platform pulls itself.

Authentication is four calls, in order, and the order matters: claim a
credential, list what that user may act as, select a branch and department, then
begin a session. Skip the select and OData answers for whichever branch the user
happened to land in, which is how a report quietly returns another site's rows.

Credentials come from the environment or from settings. Nothing is stored here.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

from django.conf import settings

logger = logging.getLogger(__name__)


class CargoWiseError(RuntimeError):
    pass


class CargoWise:
    """One authenticated session against one CargoWise environment."""

    def __init__(self, base=None, module=None, model=None,
                 username=None, password=None, department=None):
        self.base = (base or getattr(settings, 'CW_BASE_URL',
                                     'https://www-isbint.wisegrid.net')).rstrip('/')
        self.module = module or getattr(settings, 'CW_MODULE', 'TWD')
        self.model = model or getattr(settings, 'CW_ODATA_MODEL', 'TransitWarehouse')
        self.username = username or getattr(settings, 'CW_USERNAME', '')
        self.password = password or getattr(settings, 'CW_PASSWORD', '')
        self.department_code = (department
                                or getattr(settings, 'CW_DEPARTMENT_CODE', 'BRN')).upper()

        if not self.username or not self.password:
            raise CargoWiseError(
                'CargoWise credentials are not configured (CW_USERNAME / CW_PASSWORD).')

        self._auth = f'{self.base}/Glow/auth/v2'
        self._odata = f'{self.base}/Glow/odata/{self.model}'
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar))

        self.user_key = None
        self.display_name = ''
        self.branches = {}
        self.department_key = None
        self._branch = None

    # ── plumbing ────────────────────────────────────────────────────────────
    def _open(self, url, data=None, headers=None, method=None, timeout=180):
        req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        return self._opener.open(req, timeout=timeout)

    def _post(self, path, body):
        r = self._open(f'{self._auth}/{path}', data=json.dumps(body).encode(),
                       method='POST',
                       headers={'Content-Type': 'application/json',
                                'Accept': 'application/json',
                                'Referer': f'{self.base}/{self.module}/Desktop',
                                'Origin': self.base})
        return json.load(r)

    def get(self, resource, params):
        """One OData GET. Raises for anything but success."""
        url = f'{self._odata}/{resource}?{urllib.parse.urlencode(params)}'
        return json.load(self._open(url, headers={
            'Accept': 'application/json', 'wtg-app': 'Glow',
            'Referer': f'{self.base}/{self.module}/Desktop'}))

    # ── session ─────────────────────────────────────────────────────────────
    def login(self):
        res = self._post('credential/claim/Staff',
                         {'userName': self.username, 'password': self.password,
                          'setTokenCookie': True})
        if res.get('result') != 0:
            raise CargoWiseError(f'CargoWise login refused (result={res.get("result")})')
        self.user_key = res['userKey']
        self.display_name = res.get('userDisplayName') or self.username

        ctx = self._post('credential/context/list',
                         {'logonProviderType': 'Staff', 'userKey': self.user_key,
                          'useTokenCookie': True})
        self.branches = {b['code'].upper(): b['key'] for b in ctx.get('branchInfos', [])}
        for d in ctx.get('departmentInfos', []):
            if d['code'].upper() == self.department_code:
                self.department_key = d['key']
        if not self.department_key:
            raise CargoWiseError(f'Department {self.department_code} not available '
                                 f'to {self.username}')
        logger.info('[cargowise] authenticated as %s', self.display_name)
        return self

    def select_branch(self, code):
        """Point this session at one branch. Every later GET answers for it."""
        code = code.upper()
        if code not in self.branches:
            raise CargoWiseError(f'Branch {code} not available to {self.username}')
        self._post('credential/context/select',
                   {'logonProviderType': 'Staff', 'userKey': self.user_key,
                    'branchKey': self.branches[code],
                    'departmentKey': self.department_key,
                    'useAndSetTokenCookie': True})
        self._post('session/begin', {'tokenType': 1, 'sessionType': 'General',
                                     'useAndSetTokenCookie': True})
        self._branch = code
        return self

    def page(self, resource, params, page_size=50, max_pages=400):
        """Every row of a query, following $skip until a short page arrives.

        A session can expire mid-pull, so a 401 re-authenticates and resumes on
        the same page rather than losing the rows already gathered. max_pages is
        a stop against a filter that matches far more than anyone intended.
        """
        rows, skip = [], 0
        for _ in range(max_pages):
            q = dict(params, **{'$top': str(page_size), '$skip': str(skip)})
            for attempt in range(3):
                try:
                    data = self.get(resource, q)
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 401 and attempt < 2:
                        logger.info('[cargowise] session expired, re-authenticating')
                        self.login()
                        if self._branch:
                            self.select_branch(self._branch)
                        continue
                    detail = ''
                    try:
                        detail = e.read()[:300].decode('utf-8', 'replace')
                    except Exception:
                        pass
                    raise CargoWiseError(f'{resource} failed: HTTP {e.code} {detail}')
            else:
                raise CargoWiseError(f'{resource}: repeated failures')

            batch = data.get('value', [])
            rows.extend(batch)
            if len(batch) < page_size:
                return rows
            skip += page_size
        logger.warning('[cargowise] %s stopped at %d rows (max_pages)', resource, len(rows))
        return rows


def address(record, kind):
    """Rebuild one typed address the way the grid's export writes it.

    CargoWise stores the parts separately and the export joins them into
    "NAME, STREET, CITY STATE ZIP, COUNTRY". Producing the same string here
    means the parsing on the other side does not have to know which produced it.
    """
    for a in record.get('Addresses', []):
        if a.get('E2_AddressType') != kind:
            continue
        ad = a.get('Address') or {}
        oh = ad.get('OrgHeader') or {}
        ctry = ad.get('Country') or {}
        name = oh.get('OH_FullName') or ad.get('OA_CompanyNameOverride') or ''
        a1 = ad.get('OA_Address1') or ad.get('OA_Code') or ''
        a2 = ad.get('OA_Address2') or ''
        csz = ' '.join(x for x in (ad.get('OA_City') or '', ad.get('OA_State') or '',
                                   ad.get('OA_PostCode') or '') if x)
        country = ctry.get('RN_Desc') or ad.get('OA_RN_NKCountryCode') or ''
        return ', '.join(x for x in (name, a1, a2, csz, country) if x)
    return ''
