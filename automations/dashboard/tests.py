"""Tests for the turnover import's branch detection.

Written after a combined CON+DOR turnover file spent seven months being filed
entirely under CON. Nothing failed while that happened - the sync reported
success every week, and the figures looked complete. They were simply attributed
to one branch instead of two, which is invisible unless somebody sorts the
dashboard by debtor and wonders why a customer's sales all sit in one place.

SimpleTestCase rather than TestCase: this is string parsing and touches no
database, so the suite runs anywhere without needing rights to create one.
"""
from datetime import date

from django.test import SimpleTestCase

# Absolute, not relative: the app has no __init__.py and works as a namespace
# package under Django's loader, but unittest imports this module on its own and
# cannot resolve a relative import from there.
from dashboard.onedrive_sync import (
    KNOWN_BRANCHES, get_branch_from_file, get_branches_from_file,
)


class _Cell:
    def __init__(self, value):
        self.value = value


class _Sheet:
    """The smallest thing that behaves like the part of a worksheet we read.

    The real header sits at row 7, column 2; the readers scan rows 1-11 and
    columns 1-4, so putting it there exercises the scan rather than bypassing it.
    """

    def __init__(self, header_text, row=7, col=2):
        self._text = header_text
        self._row = row
        self._col = col

    def cell(self, row, column):
        if row == self._row and column == self._col:
            return _Cell(self._text)
        return _Cell(None)


class BranchDetectionTests(SimpleTestCase):

    def test_single_branch(self):
        self.assertEqual(get_branch_from_file(_Sheet('Transaction Branches: IMP')), 'IMP')

    def test_combined_branches_are_not_read_as_the_first_one(self):
        """The bug: 'CON, DOR' used to yield 'CON', filing DOR's rows under CON."""
        sheet = _Sheet('Transaction Branches: CON, DOR')
        self.assertEqual(get_branches_from_file(sheet), ['CON', 'DOR'])
        self.assertEqual(get_branch_from_file(sheet), 'CON-DOR')

    def test_combined_branches_without_a_space(self):
        self.assertEqual(get_branch_from_file(_Sheet('Transaction Branches: CON,DOR')),
                         'CON-DOR')

    def test_singular_heading(self):
        """'Branches?' reads as 'Branche' + optional s, so it never matched this."""
        self.assertEqual(get_branch_from_file(_Sheet('Transaction Branch: ORD')), 'ORD')

    def test_three_branches(self):
        self.assertEqual(get_branch_from_file(_Sheet('Transaction Branches: ATL, DFW, HOU')),
                         'ATL-DFW-HOU')

    def test_case_and_padding_are_tolerated(self):
        self.assertEqual(get_branch_from_file(_Sheet('transaction branches:   lax  ')), 'LAX')

    def test_unknown_code_is_rejected(self):
        """Better to report no branch than to invent one."""
        self.assertIsNone(get_branch_from_file(_Sheet('Transaction Branches: ZZZ')))
        self.assertEqual(get_branches_from_file(_Sheet('Transaction Branches: ZZZ')), [])

    def test_unknown_mixed_with_known_keeps_only_the_known(self):
        self.assertEqual(get_branch_from_file(_Sheet('Transaction Branches: CON, ZZZ')), 'CON')

    def test_empty_value(self):
        self.assertIsNone(get_branch_from_file(_Sheet('Transaction Branches: ')))

    def test_missing_heading(self):
        self.assertIsNone(get_branch_from_file(_Sheet('Debtor Groups:')))
        self.assertEqual(get_branches_from_file(_Sheet('Debtor Groups:')), [])

    def test_duplicates_collapse(self):
        self.assertEqual(get_branches_from_file(_Sheet('Transaction Branches: CON, CON')),
                         ['CON'])

    def test_order_is_preserved_as_written(self):
        """DOR-CON and CON-DOR would be two different labels for one thing."""
        self.assertEqual(get_branches_from_file(_Sheet('Transaction Branches: DOR, CON')),
                         ['DOR', 'CON'])

    def test_header_further_down_the_scan_is_still_found(self):
        self.assertEqual(get_branch_from_file(_Sheet('Transaction Branches: HNL', row=3, col=1)),
                         'HNL')

    def test_header_outside_the_scanned_range_is_not_found(self):
        self.assertIsNone(get_branch_from_file(_Sheet('Transaction Branches: HNL', row=40)))

    def test_every_known_branch_parses(self):
        for code in KNOWN_BRANCHES:
            with self.subTest(branch=code):
                self.assertEqual(get_branch_from_file(_Sheet(f'Transaction Branches: {code}')),
                                 code)

    def test_the_real_header_from_the_september_file(self):
        """Verbatim from the 2026-09-22 CON-DOR attachment."""
        self.assertEqual(get_branch_from_file(_Sheet('Transaction Branches: CON, DOR')),
                         'CON-DOR')


class PickUpdownYearTests(SimpleTestCase):
    """Which year's SharePoint file an Up Down Trader extract may replace.

    The extract replaces a whole year's file, so the rule errs towards leaving
    the file alone: replacing a full year with part of one would drop months
    of history from the Excel report without anything failing.
    """

    def pick(self, stats, today=date(2026, 9, 28)):
        from dashboard.scheduler import _pick_updown_year
        return _pick_updown_year(stats, today)

    def test_a_year_to_date_extract_replaces_its_year(self):
        """The 27 Sep 2026 email: Jan-Sep 2026 plus a few bad future ETDs."""
        stats = [(2026, '2026-01', 31068), (2027, '2027-02', 1), (2033, '2033-03', 27),
                 (2037, '2037-01', 1)]
        self.assertEqual(self.pick(stats), (2026, None))

    def test_an_extract_that_does_not_start_in_january_is_left_alone(self):
        year, why = self.pick([(2026, '2026-04', 20000)])
        self.assertIsNone(year)
        self.assertIn('not January', why)

    def test_a_rolling_extract_spanning_new_year_is_left_alone(self):
        """Aug 2026 - Jan 2027 must not overwrite the full 2026 file."""
        year, why = self.pick([(2026, '2026-08', 15000), (2027, '2027-01', 3000)],
                              today=date(2027, 1, 25))
        self.assertIsNone(year)

    def test_a_small_extract_is_left_alone(self):
        year, why = self.pick([(2026, '2026-01', 40)])
        self.assertIsNone(year)
        self.assertIn('only 40 rows', why)

    def test_a_future_year_is_never_chosen(self):
        year, why = self.pick([(2031, '2031-01', 5000)])
        self.assertIsNone(year)

    def test_an_empty_extract_is_left_alone(self):
        self.assertEqual(self.pick([]), (None, 'the extract is empty'))
