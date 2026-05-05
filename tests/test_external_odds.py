"""Тесты для NB-Bet/Flashscore best-effort agреgaторов."""

from services.external_odds import (
    _infer_1x2_from_nb,
    _nb_bookmaker,
    _sstats_1x2_average,
)


def test_sstats_1x2_average_combines_books():
    raw = [
        {
            "bookmakerName": "WilliamHill",
            "odds": [
                {
                    "marketName": "Match Winner",
                    "odds": [
                        {"name": "Home", "value": 2.0},
                        {"name": "Draw", "value": 3.4},
                        {"name": "Away", "value": 3.5},
                    ],
                }
            ],
        },
        {
            "bookmakerName": "10Bet",
            "odds": [
                {
                    "marketName": "1X2",
                    "odds": [
                        {"name": "1", "value": 2.2},
                        {"name": "X", "value": 3.6},
                        {"name": "2", "value": 3.3},
                    ],
                }
            ],
        },
    ]
    avg = _sstats_1x2_average(raw)
    assert avg is not None
    assert abs(avg["1"] - 2.1) < 0.01
    assert abs(avg["X"] - 3.5) < 0.01
    assert abs(avg["2"] - 3.4) < 0.01


def test_sstats_1x2_average_returns_none_without_winner_market():
    raw = [{"bookmakerName": "A", "odds": [{"marketName": "Goals OU", "odds": []}]}]
    assert _sstats_1x2_average(raw) is None


def test_infer_1x2_from_nb_finds_triple_close_to_target():
    # NB-Bet bucket has 1X2 odds among other markets; target is (2.10, 3.40, 3.50)
    nb = {
        "5": {
            "1": 2.10,
            "2": 3.50,
            "3": 3.40,
            "4": 1.50,  # шум
            "5": 2.50,  # шум
            "10": 5.0,  # шум
        }
    }
    target = {"1": 2.10, "X": 3.40, "2": 3.50}
    triple = _infer_1x2_from_nb(nb, target)
    assert triple is not None
    # Должны вернуться values, перестановкой совпадающие со SStats target
    assert sorted(triple) == sorted([2.10, 3.40, 3.50])


def test_infer_1x2_from_nb_returns_none_when_no_target():
    assert _infer_1x2_from_nb({"5": {"1": 2.0, "2": 3.0, "3": 3.5}}, None) is None


def test_infer_1x2_from_nb_returns_none_when_too_far():
    nb = {"5": {"1": 99.0, "2": 88.0, "3": 77.0}}  # явно вне разумного диапазона
    target = {"1": 2.10, "X": 3.40, "2": 3.50}
    assert _infer_1x2_from_nb(nb, target) is None


def test_nb_bookmaker_has_match_winner_shape():
    book = _nb_bookmaker((2.10, 3.40, 3.50))
    assert book["bookmakerName"] == "NB-Bet"
    market = book["odds"][0]
    assert market["marketName"] == "Match Winner"
    names = {o["name"]: o["value"] for o in market["odds"]}
    assert names == {"Home": 2.10, "Draw": 3.40, "Away": 3.50}
