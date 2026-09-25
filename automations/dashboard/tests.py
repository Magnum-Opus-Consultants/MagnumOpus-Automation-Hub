"""Tests for the turnover import's branch detection.

Written after a combined CON+DOR turnover file spent seven months being filed
entirely under CON. Nothing failed while that happened - the sync reported
success every week, and the figures looked complete. They were simply attributed
to one branch instead of two, which is invisible unless somebody sorts the
dashboard by debtor and wonders why a customer's sales all sit in one place.

SimpleTestCase rather than TestCase: this is string parsing and touches no
database, so the suite runs anywhere without needing rights to create one.
"""
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
