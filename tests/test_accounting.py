import sys, unittest
from fractions import Fraction as Q
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analyze import components, endpoints, stable, median
from build_inputs import validate, DATES
from cli import compare


class AccountingTests(unittest.TestCase):
    def test_denominator_only_gain(self):
        r = components(100, 90, Q(9, 10), 1)
        self.assertEqual(r["share_change_pp"], 10)
        self.assertEqual(r["numerator_component_pp"], 0)
        self.assertEqual(r["denominator_component_pp"], 10)

    def test_numerator_only_gain(self):
        r = components(100, 100, Q(9, 10), 1)
        self.assertEqual(r["numerator_component_pp"], 10)
        self.assertEqual(r["denominator_component_pp"], 0)

    def test_nothing_changed(self):
        r = components(100, 100, Q(9, 10), Q(9, 10))
        self.assertEqual(r["share_change_pp"], 0)
        self.assertEqual(r["numerator_component_pp"], 0)
        self.assertEqual(r["denominator_component_pp"], 0)

    def test_cancellation(self):
        r = components(100, 90, Q(9, 10), Q(9, 10))
        self.assertGreater(r["denominator_component_pp"], 0)
        self.assertLess(r["numerator_component_pp"], 0)
        self.assertEqual(r["share_change_pp"], 0)

    def test_growing_denominator(self):
        self.assertLess(
            components(100, 110, Q(9, 10), Q(9, 10))["denominator_component_pp"], 0
        )

    def test_decreasing_share(self):
        self.assertEqual(components(100, 100, 1, Q(9, 10))["share_change_pp"], -10)

    def test_infeasible_counterfactual(self):
        r = components(100, 80, Q(9, 10), 1)
        self.assertEqual(r["counterfactual_status"], "infeasible")
        self.assertEqual(r["constant_implied_count_change_pp"], "")

    def test_feasible_counterfactual(self):
        self.assertEqual(
            components(100, 90, Q(9, 10), 1)["constant_implied_count_change_pp"], 10
        )

    def test_count_scale_invariance(self):
        a = components(100, 90, Q(9, 10), 1)
        b = components(1000, 900, Q(9, 10), 1)
        self.assertEqual(a["numerator_component_pp"], b["numerator_component_pp"])
        self.assertEqual(a["denominator_component_pp"], b["denominator_component_pp"])

    def test_zero_denominator(self):
        self.assertRaises(AssertionError, components, 0, 100, 1, 1)

    def test_noninteger_units(self):
        self.assertRaises(AssertionError, components, Q(3, 2), 100, 1, 1)

    def test_percent_scaling_error(self):
        self.assertRaises(AssertionError, components, 100, 100, 90, 95)

    def test_negative_share(self):
        self.assertRaises(AssertionError, components, 100, 100, Q(-1, 100), 1)

    def test_lower_clip(self):
        self.assertEqual(endpoints(0), (0, Q(1, 10000)))

    def test_upper_clip(self):
        self.assertEqual(endpoints(1), (Q(9999, 10000), 1))

    def test_interior_sensitivity(self):
        self.assertEqual(endpoints(Q(1, 2)), (Q(4999, 10000), Q(5001, 10000)))

    def test_stable_positive(self):
        self.assertEqual(stable(Q(1, 100), Q(2, 100)), "positive")

    def test_stable_negative(self):
        self.assertEqual(stable(Q(-2, 100), Q(-1, 100)), "negative")

    def test_stable_zero(self):
        self.assertEqual(stable(0, 0), "zero")

    def test_zero_boundary_ambiguous(self):
        self.assertEqual(stable(0, Q(1, 100)), "ambiguous")

    def test_span_zero_ambiguous(self):
        self.assertEqual(stable(-1, 1), "ambiguous")

    def test_even_median(self):
        self.assertEqual(median([Q(1, 3), Q(2, 3)]), Q(1, 2))

    def test_odd_median(self):
        self.assertEqual(median([3, 1, 2]), 2)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.geo = {f"{i:02}": "Authored " + str(i) for i in range(1, 52)}
        self.rows = [
            dict(
                data_as_of=t,
                geography_id=g,
                geography_desc=name,
                area_data_type="Total",
                geography_type="State",
                biz_res="R",
                technology="Any Terrestrial",
                total_units="100",
                speed_25_3="0.900000000",
                speed_100_20="0.800000000",
            )
            for t in DATES
            for g, name in self.geo.items()
        ]

    def test_fixed_complete_keys(self):
        self.assertEqual(validate(self.rows, self.geo)["rows"], 204)

    def test_missing_key(self):
        self.rows.pop()
        self.assertRaises(AssertionError, validate, self.rows, self.geo)

    def test_conflicting_copy(self):
        self.rows[-1] = dict(self.rows[0], total_units="101")
        self.assertRaises(AssertionError, validate, self.rows, self.geo)

    def test_wrong_technology(self):
        self.rows[0]["technology"] = "Any Technology"
        self.assertRaises(AssertionError, validate, self.rows, self.geo)

    def test_wrong_population(self):
        self.rows[0]["biz_res"] = "X"
        self.assertRaises(AssertionError, validate, self.rows, self.geo)

    def test_wrong_area(self):
        self.rows[0]["area_data_type"] = "Rural"
        self.assertRaises(AssertionError, validate, self.rows, self.geo)

    def test_name_code_conflict(self):
        self.rows[0]["geography_desc"] = "Different"
        self.assertRaises(AssertionError, validate, self.rows, self.geo)

    def test_source_scale(self):
        self.rows[0]["speed_25_3"] = "90"
        self.assertRaises(AssertionError, validate, self.rows, self.geo)

    def test_speed_nesting(self):
        self.rows[0]["speed_100_20"] = "0.99"
        self.assertRaises(AssertionError, validate, self.rows, self.geo)

    def test_zero_units(self):
        self.rows[0]["total_units"] = "0"
        self.assertRaises(AssertionError, validate, self.rows, self.geo)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.old = dict(
            geography_id="AUTHORED",
            geography_type="State",
            area_data_type="Total",
            biz_res="R",
            technology="Any Terrestrial",
            speed="speed_100_20",
            unit="map_units",
            data_as_of="2023-12-31",
            total_units="100",
            share="0.9",
        )
        self.new = dict(self.old, data_as_of="2024-06-30", total_units="90", share="1")

    def test_exact_exercise(self):
        self.assertEqual(compare(self.old, self.new)["denominator_component_pp"], "10")

    def test_unordered_dates(self):
        self.new["data_as_of"] = "2023-12-31"
        self.assertEqual(compare(self.old, self.new)["status"], "unavailable")

    def test_wrong_geography(self):
        self.new["geography_id"] = "DIFFERENT"
        self.assertEqual(compare(self.old, self.new)["status"], "unavailable")

    def test_unit_mismatch(self):
        self.new["unit"] = "households"
        self.assertEqual(compare(self.old, self.new)["status"], "unavailable")

    def test_native_strings(self):
        self.new["share"] = 1.0
        self.assertEqual(compare(self.old, self.new)["status"], "unavailable")

    def test_null_unavailable(self):
        self.new["total_units"] = None
        self.assertEqual(compare(self.old, self.new)["status"], "unavailable")

    def test_non_decimal_token(self):
        self.new["share"] = "9/10"
        self.assertEqual(compare(self.old, self.new)["status"], "unavailable")

    def test_missing_identity(self):
        del self.new["technology"]
        self.assertEqual(compare(self.old, self.new)["status"], "unavailable")

    def test_other_technology(self):
        self.old["technology"] = self.new["technology"] = "Any Technology"
        self.assertEqual(compare(self.old, self.new)["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
