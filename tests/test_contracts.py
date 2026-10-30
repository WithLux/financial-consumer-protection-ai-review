import json
import unittest
from datetime import date
from pathlib import Path
from pydantic import ValidationError
from backend.models import (AIReviewResult, AIssue, KnowledgeBase, ReviewStatus,
                            validate_issue, can_transition, can_finalize, IssuePatch)


def candidate(**changes):
    value = dict(issue_id='i1', risk_type='misleading', severity='high',
                 original_text='保证收益', location=dict(segment_id='s1', start=2, end=6),
                 reason='请核实收益承诺语境', regulation_ids=['REG-NET-10-3'],
                 suggestion='删除保证性表述并核实风险披露', review_status='pending')
    value.update(changes)
    return value


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase.model_validate_json(Path('data/regulations/regulations.json').read_text())

    def test_verified_quote_and_reference(self):
        result = validate_issue(AIssue(**candidate()), {'s1': '产品保证收益'}, self.kb, date(2026,10,30), 'marketing', 'online')
        self.assertEqual(result.location_status, 'verified')
        self.assertEqual(result.reference_status, 'verified')
        self.assertEqual(result.review_status, 'pending')

    def test_unknown_reference_is_pending_not_invented(self):
        result = validate_issue(AIssue(**candidate(regulation_ids=['FAKE'])), {'s1':'产品保证收益'}, self.kb, date(2026,10,30), 'marketing', 'online')
        self.assertEqual(result.unverified_regulation_ids, ['FAKE'])
        self.assertEqual(result.reference_status, 'needs_verification')
        self.assertEqual(result.regulation_ids, [])

    def test_quote_mismatch_not_highlighted(self):
        result = validate_issue(AIssue(**candidate()), {'s1':'产品并不保证'}, self.kb, date(2026,10,30), 'marketing', 'online')
        self.assertEqual(result.location_status, 'needs_verification')

    def test_wrong_scope_or_date_not_verified(self):
        for day, material, channel in [(date(2026,1,1),'marketing','online'),(date(2026,10,30),'notice','offline')]:
            result = validate_issue(AIssue(**candidate()), {'s1':'产品保证收益'}, self.kb, day, material, channel)
            self.assertEqual(result.reference_status, 'needs_verification')

    def test_no_references_remains_heuristic(self):
        result = validate_issue(AIssue(**candidate(regulation_ids=[])), {'s1':'产品保证收益'}, self.kb, date(2026,10,30), 'marketing', 'online')
        self.assertEqual(result.reference_status, 'needs_verification')

    def test_ai_cannot_confirm_human_decision_or_server_validation(self):
        for values in [candidate(review_status='accepted'), candidate(reference_status='verified')]:
            with self.assertRaises(ValidationError): AIssue(**values)

    def test_offsets_and_duplicate_ids(self):
        with self.assertRaises(ValidationError): AIssue(**candidate(location=dict(segment_id='s1',start=6,end=2)))
        with self.assertRaises(ValidationError): AIReviewResult(issues=[candidate(),candidate()])

    def test_unicode_codepoint_location(self):
        issue=AIssue(**candidate(location=dict(segment_id='s1',start=1,end=5)))
        result=validate_issue(issue, {'s1':'😀保证收益'}, self.kb, date(2026,10,30), 'marketing','online')
        self.assertEqual(result.location_status, 'verified')

    def test_patch_requires_reason_and_version(self):
        with self.assertRaises(ValidationError): IssuePatch(expected_version=1,review_status='rejected',decision_reason='')
        patch=IssuePatch(expected_version=1,review_status='rejected',decision_reason='仅为反面引述')
        self.assertEqual(patch.expected_version,1)

    def test_transition_and_finalization_guards(self):
        self.assertTrue(can_transition(ReviewStatus.pending,ReviewStatus.running))
        self.assertFalse(can_transition(ReviewStatus.issued,ReviewStatus.running))
        issue=validate_issue(AIssue(**candidate()), {'s1':'产品保证收益'}, self.kb,date(2026,10,30),'marketing','online')
        self.assertFalse(can_finalize([issue],coverage_confirmed=True,limitations_acknowledged=True))
        accepted=issue.model_copy(update={'review_status':'accepted','decision_reason':'核实后采纳'})
        self.assertTrue(can_finalize([accepted],coverage_confirmed=True,limitations_acknowledged=True))
        invalid=accepted.model_copy(update={'reference_status':'needs_verification'})
        self.assertFalse(can_finalize([invalid],coverage_confirmed=True,limitations_acknowledged=True))
        rejected=invalid.model_copy(update={'review_status':'rejected'})
        self.assertTrue(can_finalize([rejected],coverage_confirmed=True,limitations_acknowledged=True))
        self.assertFalse(can_finalize([],coverage_confirmed=False,limitations_acknowledged=True))

    def test_patch_edit_and_location_pair_contract(self):
        with self.assertRaises(ValidationError):
            IssuePatch(expected_version=1,review_status='edited',decision_reason='修改')
        with self.assertRaises(ValidationError):
            IssuePatch(expected_version=1,review_status='edited',decision_reason='修改',original_text='新文本')
        with self.assertRaises(ValidationError):
            IssuePatch(expected_version=1,review_status='accepted',decision_reason='采纳',suggestion='改动')
        valid=IssuePatch(expected_version=1,review_status='edited',decision_reason='修改',suggestion='新建议')
        self.assertEqual(valid.suggestion,'新建议')

    def test_checked_in_schemas_match_models(self):
        self.assertEqual(json.loads(Path('schemas/ai-review-result.schema.json').read_text()),AIReviewResult.model_json_schema())
        self.assertEqual(json.loads(Path('schemas/knowledge-base.schema.json').read_text()),KnowledgeBase.model_json_schema())

    def test_library_reference_integrity(self):
        data=self.kb.model_dump(mode='json')
        data['rules'][0]['regulation_ids']=['FAKE']
        with self.assertRaises(ValidationError): KnowledgeBase.model_validate(data)

    def test_json_schemas_are_generated_from_models(self):
        self.assertIn('issues',AIReviewResult.model_json_schema()['properties'])


if __name__=='__main__': unittest.main()
