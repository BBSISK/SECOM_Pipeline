"""Unit tests for scripts/price_check.py (no AWS calls)."""

from scripts.price_check import matches_usagetype, on_demand_prices


def test_usagetype_match_ignores_region_prefix():
    assert matches_usagetype("EU-Storage-ShardHour", "Storage-ShardHour")


def test_usagetype_match_is_exact_not_substring():
    # The ARM variant must not be counted as the x86 price.
    assert not matches_usagetype("EU-Lambda-GB-Second-ARM", "Lambda-GB-Second")
    assert not matches_usagetype("EU-RDS:Multi-AZ-GP3-Storage", "RDS:GP3-Storage")


def _product(*prices):
    dims = {
        f"d{i}": {"pricePerUnit": {"USD": usd}, "unit": "Hrs", "description": f"tier {i}"}
        for i, usd in enumerate(prices)
    }
    return {"terms": {"OnDemand": {"t1": {"priceDimensions": dims}}}}


def test_on_demand_prices_reads_usd():
    assert list(on_demand_prices(_product("0.0170000000"))) == [(0.017, "Hrs", "tier 0")]


def test_on_demand_prices_skips_free_tiers():
    assert list(on_demand_prices(_product("0.0000000000", "0.005"))) == [(0.005, "Hrs", "tier 1")]


def test_on_demand_prices_handles_missing_terms():
    assert list(on_demand_prices({"terms": {}})) == []
