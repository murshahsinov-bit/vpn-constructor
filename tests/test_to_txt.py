import urllib.parse

from aggregator.formatter.to_txt import generate_txt


TCP_LINK = (
    "vless://11111111-1111-1111-1111-111111111111@198.51.100.7:443"
    "?encryption=none&flow=xtls-rprx-vision&security=reality&sni=example.com"
    "&type=tcp#Germany%20Berlin"
)

XHTTP_LINK = (
    "vless://22222222-2222-2222-2222-222222222222@198.51.100.8:443"
    "?mode=auto&path=%2Fcdn&security=tls&host=cdn.example.com&sni=cdn.example.com"
    "&type=xhttp#Netherlands%20Amsterdam"
)

TCP_TLS_LINK = (
    "vless://33333333-3333-3333-3333-333333333333@198.51.100.9:443"
    "?flow=xtls-rprx-vision&security=tls&sni=ripelever.net&type=raw#Finland"
)


def parse_link(link: str) -> tuple[urllib.parse.SplitResult, dict[str, str]]:
    parsed = urllib.parse.urlsplit(link)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    return parsed, query


def test_incy_fragment_params_for_tcp_only():
    text = generate_txt([TCP_LINK, XHTTP_LINK], client="incy")
    tcp_link, xhttp_link = text.splitlines()

    _parsed, query = parse_link(tcp_link)
    assert query["fragmentPackets"] == "tlshello"
    assert query["fragmentLength"] == "100-200"
    assert query["fragmentInterval"] == "10-20"
    assert "fragment" not in query

    _parsed, xhttp_query = parse_link(xhttp_link)
    assert "fragmentPackets" not in xhttp_query
    assert "fragment" not in xhttp_query
    # Существующие параметры XHTTP не перекодируются.
    assert xhttp_query["host"] == "cdn.example.com"
    assert xhttp_query["path"] == "/cdn"


def test_happ_fragment_single_param():
    text = generate_txt([TCP_LINK], client="happ")
    link = text.splitlines()[0]

    _parsed, query = parse_link(link)
    assert query["fragment"] == "100-200,10-20,tlshello"
    assert "fragmentPackets" not in query
    assert "fragmentLength" not in query


def test_raw_is_treated_as_tcp():
    text = generate_txt([TCP_TLS_LINK], client="happ")
    _parsed, query = parse_link(text.splitlines()[0])
    assert query["fragment"] == "100-200,10-20,tlshello"


def test_existing_fragment_params_are_replaced():
    link = TCP_LINK.replace(
        "#Germany%20Berlin",
        "&fragmentPackets=old&fragment=1,2,ws#Germany%20Berlin",
    )
    text = generate_txt([link], client="incy")
    _parsed, query = parse_link(text.splitlines()[0])

    assert query["fragmentPackets"] == "tlshello"
    assert query["fragmentLength"] == "100-200"
    assert "fragment" not in query


def test_country_flag_and_extended_fragment_are_preserved():
    link = TCP_LINK.replace(
        "#Germany%20Berlin", "#Germany%20Berlin?serverDescription=SGFwcA=="
    )
    text = generate_txt([link], client="happ")
    parsed = urllib.parse.urlsplit(text.splitlines()[0])

    fragment = urllib.parse.unquote(parsed.fragment)
    assert fragment.startswith("🇩🇪 Berlin")
    assert fragment.endswith("?serverDescription=SGFwcA==")


def test_same_names_are_numbered():
    text = generate_txt([TCP_LINK, TCP_LINK], client="incy")
    fragments = [
        urllib.parse.unquote(urllib.parse.urlsplit(line).fragment)
        for line in text.splitlines()
    ]
    assert fragments[0] != fragments[1]
    assert fragments[1].endswith(" Berlin 2")


def test_generate_is_idempotent_for_decorated_names():
    first = generate_txt([TCP_LINK], client="incy")
    second = generate_txt([first], client="incy")

    first_fragment = urllib.parse.unquote(
        urllib.parse.urlsplit(first).fragment
    )
    second_fragment = urllib.parse.unquote(
        urllib.parse.urlsplit(second).fragment
    )
    assert first_fragment == second_fragment == "🇩🇪 Berlin"
