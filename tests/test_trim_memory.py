"""Tests for the Windows working-set trimming helper."""

import ctypes
import unittest
from unittest import mock

import polars_helper_functions as phf
from polars_helper_functions import helpers


class TrimMemoryTests(unittest.TestCase):
    def test_trim_memory_is_exported_from_package(self):
        self.assertIs(phf.trim_memory, helpers.trim_memory)

    def test_trim_memory_is_noop_off_windows(self):
        with mock.patch("os.name", "posix"), mock.patch("gc.collect") as collect:
            self.assertIsNone(helpers.trim_memory())

        collect.assert_not_called()

    def test_trim_memory_collects_garbage_and_empties_working_set(self):
        kernel32 = mock.Mock()
        psapi = mock.Mock()
        process = object()
        kernel32.GetCurrentProcess.return_value = process
        psapi.EmptyWorkingSet.return_value = True

        with (
            mock.patch("os.name", "nt"),
            mock.patch("gc.collect") as collect,
            mock.patch.object(
                ctypes, "WinDLL", create=True, side_effect=[kernel32, psapi]
            ) as win_dll,
        ):
            self.assertIsNone(helpers.trim_memory())

        collect.assert_called_once_with()
        self.assertEqual(
            win_dll.call_args_list,
            [
                mock.call("kernel32", use_last_error=True),
                mock.call("psapi", use_last_error=True),
            ],
        )
        kernel32.GetCurrentProcess.assert_called_once_with()
        psapi.EmptyWorkingSet.assert_called_once_with(process)


if __name__ == "__main__":
    unittest.main()
