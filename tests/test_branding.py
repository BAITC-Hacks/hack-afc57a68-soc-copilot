import base64
import xml.etree.ElementTree as ET

import pytest

from ui.branding import ASSETS, asset_uri, favicon_svg, logo_html


@pytest.mark.parametrize('name', [
    'orgtrace-logo.svg', 'orgtrace-logo-dark.svg',
    'orgtrace-icon.svg', 'orgtrace-icon-dark.svg',
])
def test_brand_assets_are_valid_self_contained_svg(name):
    source = base64.b64decode(asset_uri(name).split(',', 1)[1])
    assert source == (ASSETS / name).read_bytes()
    root = ET.fromstring(source)
    assert root.tag == '{http://www.w3.org/2000/svg}svg'
    assert root.get('viewBox')
    assert not root.findall('.//{http://www.w3.org/2000/svg}script')
    assert all('href' not in key for node in root.iter() for key in node.attrib)


def test_logo_and_favicon_support_both_palettes():
    markup = logo_html()
    assert markup.count('alt="OrgTrace"') == 2
    assert asset_uri('orgtrace-logo.svg') in markup
    assert asset_uri('orgtrace-logo-dark.svg') in markup
    icon = favicon_svg()
    assert ET.fromstring(icon).get('viewBox') == '0 0 64 64'
    assert 'prefers-color-scheme: dark' in icon
    assert '#F3F6F5' in icon and '#63CFBC' in icon
