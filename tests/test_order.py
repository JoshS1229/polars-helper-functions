"""Tests for the Stata-style column ordering helper."""

import unittest

import polars as pl
import polars.selectors as cs

import polars_helper_functions as phf


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.df = pl.DataFrame(
            {"a": [1], "b": [2.0], "c": ["three"], "d": [4], "e": [5]}
        )

    def test_moves_names_to_front_and_deduplicates(self):
        result = phf.order(self.df, "b", ["a", "b"])
        self.assertEqual(result.columns, ["b", "a", "c", "d", "e"])

    def test_before_and_after_preserve_remaining_order(self):
        self.assertEqual(
            phf.order(self.df, "d", "e", before="b").columns,
            ["a", "d", "e", "b", "c"],
        )
        self.assertEqual(
            phf.order(self.df, "a", "e", after="c").columns,
            ["b", "c", "a", "e", "d"],
        )

    def test_selectors_expand_in_frame_order(self):
        result = phf.order(self.df, "c", cs.numeric())
        self.assertEqual(result.columns, ["c", "a", "b", "d", "e"])

    def test_lazyframe_stays_lazy(self):
        result = phf.order(self.df.lazy(), cs.starts_with("d"), "b")
        self.assertIsInstance(result, pl.LazyFrame)
        self.assertEqual(result.collect_schema().names(), ["d", "b", "a", "c", "e"])

    def test_invalid_arguments_raise_useful_errors(self):
        with self.assertRaisesRegex(ValueError, "Only one"):
            phf.order(self.df, "a", before="b", after="c")
        with self.assertRaisesRegex(ValueError, "Column not found.*missing"):
            phf.order(self.df, "missing")
        with self.assertRaisesRegex(ValueError, "Anchor column not found.*missing"):
            phf.order(self.df, "a", before="missing")
        with self.assertRaisesRegex(TypeError, "only strings"):
            phf.order(self.df, ["a", 1])


if __name__ == "__main__":
    unittest.main()
