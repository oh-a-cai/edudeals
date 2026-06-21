"""No-DB self-check for the upsert NULL guard. Run: python test_database.py"""
from database import Deal, drop_unconflictable


def test_drops_null_redemption_url():
    deals = [
        Deal(brand="A", description="x", redemption_url="https://a.com"),
        Deal(brand="B", description="y", redemption_url=None),
        Deal(brand="C", description="z", redemption_url=""),  # empty == falsy
    ]
    kept = drop_unconflictable(deals)
    assert [d.brand for d in kept] == ["A"], kept
    print("ok: null/empty redemption_url rows dropped")


if __name__ == "__main__":
    test_drops_null_redemption_url()
