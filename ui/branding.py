"""Local, theme-aware brand assets; no network or generated approximations."""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).with_name('assets')


@lru_cache(maxsize=4)
def asset_uri(name: str) -> str:
    if name not in {'orgtrace-logo.svg', 'orgtrace-logo-dark.svg',
                    'orgtrace-icon.svg', 'orgtrace-icon-dark.svg'}:
        raise ValueError('Unknown brand asset')
    return 'data:image/svg+xml;base64,' + base64.b64encode((ASSETS / name).read_bytes()).decode('ascii')


def logo_html() -> str:
    return ('<div class="brand brand-logo">'
            f'<img class="brand-light" src="{asset_uri("orgtrace-logo.svg")}" '
            'alt="OrgTrace" width="300" height="96">'
            f'<img class="brand-dark" src="{asset_uri("orgtrace-logo-dark.svg")}" '
            'alt="OrgTrace" width="300" height="96"></div>')


def favicon_svg() -> str:
    """Use the supplied icon, with a system-dark fallback before JS starts."""
    source = (ASSETS / 'orgtrace-icon.svg').read_text(encoding='utf-8')
    return source.replace('</svg>', '''<style>
        @media (prefers-color-scheme: dark) {
            [stroke="#202D36"] { stroke: #F3F6F5; }
            [fill="#087F73"] { fill: #63CFBC; }
        }
        </style></svg>''')
