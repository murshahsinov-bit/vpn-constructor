import pytest

from netrun_worker.naming import (
    flag_code,
    pretty_name,
    prettify_subscription,
)

GERMANY = (
    "vless://uuid@example.com:443?type=xhttp&security=reality#"
    "%F0%9F%87%A9%F0%9F%87%AA%20%D0%91%D0%B5%D1%81%D0%BF%D0%BB%D0%B0%D1%82%D0%BD%D1%8B%D0%B9"
    "%20VPN%20tg%3AVLESSFORU%20%F0%9F%87%A9%F0%9F%87%AA%20t.me/rjsxrd"
)
NO_FLAG = (
    "vless://uuid@35295cx.us8.h1clayd.click:443?type=tcp&security=reality#"
    "%F0%9F%8C%90%20%F0%9F%94%A5Join%2BTelegram%3A%40Farah_VPN%F0%9F%9F%A3"
)


@pytest.mark.parametrize(
    "remark, expected",
    [
        ("🇩🇪 Германия", "DE"),
        ("🌐 🔥Join+Telegram:@Farah_VPN🟣", None),
        ("", None),
    ],
)
def test_flag_code(remark, expected):
    assert flag_code(remark) == expected


def test_country_wins_over_marketing_name():
    assert pretty_name(GERMANY) == "🇩🇪 Германия · XHTTP"


def test_tcp_is_labelled_and_raw_maps_to_tcp():
    link = "vless://uuid@example.com:443?type=raw&security=reality#%F0%9F%87%B7%F0%9F%87%BA%20AetrisVPN"
    assert pretty_name(link) == "🇷🇺 Россия · TCP"


def test_marketing_only_remark_falls_back_to_host():
    assert pretty_name(NO_FLAG) == "Сервер · h1clayd.click · TCP"


def test_numeric_leftover_falls_back_to_host():
    link = (
        "vless://uuid@95.85.232.83:2087?type=xhttp#"
        "%F0%9F%8C%90%20%F0%9F%94%A5Join%2BTelegram%3A%40Farah_VPN%F0%9F%9F%A3%202"
    )
    assert pretty_name(link) == "Сервер · 95.85.232.83 · XHTTP"


def test_russian_remark_survives_without_flag():
    link = "vless://uuid@example.com:443?type=grpc#%D0%A1%D0%B5%D1%80%D0%B2%D0%B5%D1%80%20%D0%B2%20%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B5"
    assert pretty_name(link) == "Сервер в Москве · gRPC"


def test_non_share_lines_are_kept_verbatim():
    text = "SVS1.trial.expired\n\nnot a link\n"
    assert prettify_subscription(text) == text


def test_duplicates_get_a_counter_suffix():
    text = "\n".join([GERMANY, GERMANY, GERMANY])
    names = [line.rsplit("#", 1)[1] for line in prettify_subscription(text).splitlines()]
    assert names == [
        "%F0%9F%87%A9%F0%9F%87%AA%20%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%C2%B7%20XHTTP",
        "%F0%9F%87%A9%F0%9F%87%AA%20%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%C2%B7%20XHTTP%202",
        "%F0%9F%87%A9%F0%9F%87%AA%20%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%C2%B7%20XHTTP%203",
    ]


def test_query_parameters_are_untouched():
    result = prettify_subscription(GERMANY)
    assert "type=xhttp&security=reality" in result


def test_bytes_input_and_trailing_newline():
    result = prettify_subscription(GERMANY.encode("utf-8"))
    assert result.endswith("\n")
    assert result.count("\n") == 1


def test_pretty_name_is_idempotent():
    once = prettify_subscription(GERMANY)
    twice = prettify_subscription(once)
    assert once == twice
