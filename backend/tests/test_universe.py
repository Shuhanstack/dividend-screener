from app.universe import parse_file

NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
ZZZT|Test Issue Co - Common|Q|Y|N|100|N|N
ABCDW|ABC Acquisition Corp - Warrant|S|N|N|100|N|N
ABCDU|ABC Acquisition Corp - Units|S|N|N|100|N|N
XYZR|XYZ Corp - Rights|S|N|N|100|N|N
File Creation Time: 1112202608:01|||||||
"""
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
KO|Coca-Cola Company (The) Common Stock|N|KO|N|100|N|KO
BRK.B|Berkshire Hathaway Inc. Class B|N|BRK.B|N|100|N|BRK=B
C$N|Citigroup Inc. Depositary Shares representing 1/1000th Preferred Series N|N|CPRN|N|100|N|C-N
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
ASGI|abrdn Global Infrastructure Income Fund|N|ASGI|N|100|N|ASGI
FOO.WS|Foo Corp Warrants|N|FOO.WS|N|100|N|FOO=W
File Creation Time: 1112202608:01|||||||
"""


def test_parse_excludes_non_common() -> None:
    assert [s for s, _, _ in parse_file(NASDAQ, "nasdaq")] == ["AAPL"]
    # closed-end funds (ASGI) are kept; ETFs (SPY) are not
    assert [s for s, _, _ in parse_file(OTHER, "other")] == ["KO", "BRK-B", "ASGI"]
