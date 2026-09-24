"""Regressions for the September 2026 package review; stdlib unless integration is enabled."""
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def module(slug, name):
    sys.path.insert(0, str(ROOT / 'skills' / slug / 'scripts'))
    return importlib.import_module(name)


handoff = module('cp-0-source-readiness', 'validate_handoff')
tables = module('cp-0-source-readiness', 'cp_tables')
complete = module('cp-0-source-readiness', 'completeness_check')
funding = module('cp-4c-restructuring-fulcrum', 'funding_gap')
recovery = module('cp-3-relative-value-security-selection', 'recovery_waterfall')
covenant = module('cp-4-legal-covenant-interpreter', 'covenant_headroom')
bond = module('cp-2h-ratings-migration-trigger', 'bond_analytics')
model_inputs = module('cp-model', 'validate_cp_model_inputs')
memo_markdown = module('cp-memo-credit-research-report', 'cp_memo.markdown')


def markdown(**changes):
    fields = dict(module_id='CP-1', module_name='CanonicalDataFoundation', run_id='run-1',
                  reporting_period='FY2025', analysis_date='2026-09-07', confidence_score=90,
                  confidence_band='High', qa_status='Passed', committee_status='Committee Ready',
                  limitation_flags=[], validation_warnings=[], upstream_artifacts_used=[],
                  downstream_consumers=['CP-MODEL'], issuer_name='Example', issuer_id='EXAMPLE')
    fields.update(changes)
    return ('---\n' + '\n'.join(f'{key}: {json.dumps(value)}' for key, value in fields.items())
            + '\n---\n' + '\n'.join(f'## {heading}\nSupported conclusion.\n' for heading in handoff.CANONICAL_HEADINGS))


class RegressionTests(unittest.TestCase):
    def test_required_handoff_values(self):
        filename = 'EXAMPLE_CP-1_20260907.md'
        self.assertEqual(handoff.validate_text(markdown(), filename=filename).exit_code, 0)
        for field in handoff.REQUIRED_FIELDS + handoff.ISSUER_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(handoff.validate_text(markdown(**{field: None}), filename=filename).exit_code, 2)
        for field in ('confidence_band', 'qa_status', 'committee_status'):
            for value in ([], {}, True, 2):
                with self.subTest(field=field, value=value):
                    self.assertEqual(handoff.validate_text(markdown(**{field: value})).exit_code, 2)

    def test_cp_dr_enum_types(self):
        fields = dict(module_id='CP-DR', scope_key='Sector', subject_name='Sector', research_question='Question',
                      approved_plan_hash='sha256:' + 'a' * 64, scope_type='sector', source_mode='supplied_only',
                      coverage_score=90, research_status='Complete', research_stop_reason='coverage_satisfied')
        self.assertEqual(handoff.validate_text(markdown(**fields)).exit_code, 0)
        for field in ('scope_type', 'source_mode', 'research_status', 'research_stop_reason', 'coverage_score'):
            for value in (None, [], {}):
                with self.subTest(field=field, value=value):
                    self.assertEqual(handoff.validate_text(markdown(**dict(fields, **{field: value}))).exit_code, 2)

    def test_completeness_uses_real_registers(self):
        skill = (ROOT / 'skills/cp-1-canonical-data-foundation/SKILL.md').read_text()
        contract = complete.load_contract(skill, 'CP-1')
        sections = []
        for name, spec in contract['registers'].items():
            sections.append(f'### {name}\n| ' + ' | '.join(spec['columns']) + ' |\n| '
                            + ' | '.join('---' for _ in spec['columns']) + ' |\n'
                            + ('| ' + ' | '.join('present' for _ in spec['columns']) + ' |\n')
                            * max(1, spec['minimum_body_rows']))
        sections.extend(f'<!-- table-id: {name} -->\n| value |\n| --- |\n| present |'
                        for name in contract['unconditional_stable_tables'])
        good = '\n\n'.join(sections)
        self.assertFalse(complete.check(skill, good, 'CP-1')[0])
        width = len(next(iter(contract['registers'].values()))['columns'])
        blank_row = good.replace(sections[0], sections[0] + '|' * (width + 1) + '\n')
        self.assertTrue(complete.check(skill, blank_row, 'CP-1')[0])
        self.assertTrue(complete.check(skill, good.replace('present', '', 1), 'CP-1')[0])
        self.assertTrue(complete.check(skill, '```markdown\n' + good + '\n```', 'CP-1')[0])
        self.assertTrue(complete.check(skill, good.replace('| value |\n| --- |\n| present |', ''), 'CP-1')[0])

    def test_completeness_enforces_bullet_list_columns(self):
        skill = (ROOT / 'skills/cp-3-relative-value-security-selection/SKILL.md').read_text()
        # fork r1: `unknown` is a value-list label now; a bare `n/a` is still a placeholder.
        draft = '### T3.7\n| Rank | Evidence ID |\n| --- | --- |\n| 1 | n/a |\n'
        violations, contract, _ = complete.check(skill, draft, 'CP-3')
        spec = contract['registers']['T3.7']
        self.assertIn('Countervailing Evidence', spec['columns'])
        self.assertEqual(spec['columns'], spec['critical_columns'])
        self.assertTrue(any(v.startswith('T3.7: missing column(s)') for v in violations), violations)
        self.assertTrue(any(v.startswith('T3.7 row 1: critical column')
                            and 'disqualifying placeholder' in v for v in violations), violations)

    def test_tagged_table_shapes(self):
        table = '<!-- table-id: example -->\n| A | B |\n| --- | --- |\n| 1 | 2 |\n'
        self.assertEqual(len(tables.parse_tables(table)['example']), 1)
        self.assertFalse(tables.parse_tables('````markdown\n```\n' + table + '\n````'))
        self.assertFalse(tables.parse_tables(table.replace('<!-- table-id: example -->', '`<!-- table-id: example -->`')))
        empty_first = table.replace('| 1 | 2 |', '||2|')
        self.assertEqual(tables.parse_tables(empty_first)['example'].rows, [dict(A='', B='2')])
        self.assertEqual(complete.find_registers('### T1\n' + empty_first)['T1'][1], [dict(A='', B='2')])
        self.assertEqual(tables.parse_tables(table + '|||\n')['example'].rows[-1], dict(A='', B=''))
        for bad in (table + table, table.replace('| 1 | 2 |', '| 1 |'), table.replace('| A | B |', '| A | A |')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tables.parse_tables(bad)

    def test_finite_and_unambiguous_figures(self):
        for bad in (float('nan'), float('inf'), -float('inf'), '1e309', 10**1000, '1,2.3', '1.2.3'):
            with self.subTest(value=str(bad)), self.assertRaises(ValueError):
                tables.parse_figure(bad)
        self.assertEqual(tables.parse_figure('1,234.56'), 1234.56)
        self.assertEqual(tables.parse_figure('1.234,56'), 1234.56)
        self.assertIsNone(tables.parse_figure('n/a'))
        with self.assertRaises(ValueError):
            covenant.headroom({'test_type': 'max-ratio', 'threshold': 5, 'current_ratio': float('nan')})
        with self.assertRaises(ValueError):
            covenant.headroom({'test_type': 'max-ratio', 'threshold': 1e308, 'current_ratio': -1e308})
        with self.assertRaises(ValueError):
            covenant.trigger_headroom({'trigger_direction': 'max-ratio', 'threshold': 1e308,
                                      'cases': [{'period': 'FY26', 'value': -1e308}]})

    def test_funding_currency_across_components(self):
        payload = dict(horizon_years=2, currency='USD', cash=100,
                       instruments=[dict(instrument='Note', amount=100, years_to_maturity=1, currency='EUR')])
        self.assertEqual(funding.compute(payload)['as_of_balance_sheet_date']['gap']['status'], 'Not Calculable')
        payload['instruments'][0]['currency'] = 'USD'
        self.assertEqual(funding.compute(payload)['as_of_balance_sheet_date']['gap']['coverage_ratio'], 1)
        payload.update(forecast_fcf=10, forecast_fcf_currency='EUR')
        self.assertEqual(funding.compute(payload)['as_of_balance_sheet_date']['gap']['status'], 'Not Calculable')
        del payload['currency']
        with self.assertRaises(ValueError):
            funding.compute(payload)

    def test_recovery_boundaries_and_unknowns(self):
        claims = [dict(claim_id='S', amount=100), dict(claim_id='J', amount=100)]
        for ev, state, residual in ((0, 'zero recovery', 0), (100, 'class boundary', 0),
                                    (150, 'partial recovery', 0), (200, 'fully repaid', 0),
                                    (225, 'fully repaid', 25)):
            with self.subTest(ev=ev):
                result = recovery.waterfall(ev, claims)
                self.assertEqual((result['allocation_state'], result['residual_to_equity']), (state, residual))
        summary = recovery.sensitivity(claims, [dict(label='zero', enterprise_value=0)])
        self.assertNotIn('every class is whole', summary['note'])
        self.assertIsNone(summary['fulcrum_stable'])
        claims[0]['amount'] = None
        result = recovery.waterfall(100, claims)
        self.assertIsNone(result['claims'][1]['recovered'])
        self.assertIsNone(result['residual_to_equity'])
        for ev, stack, costs in ((100, [], [dict(amount=-25)]), (100, [dict(claim_id='S', amount=-1)], []), (-1, [], [])):
            with self.subTest(ev=ev, stack=stack, costs=costs), self.assertRaises(ValueError):
                recovery.waterfall(ev, stack, costs)
        for claim_id in (None, '', ' ', 1, []):
            with self.subTest(claim_id=claim_id), self.assertRaises(ValueError):
                recovery.waterfall(50, [dict(claim_id=claim_id, amount=100)])

    def test_sustained_trigger_needs_a_window_within_one_case(self):
        trigger = dict(trigger='L', trigger_direction='max-ratio', threshold=5,
                       cases=[dict(case='Base', period='2026Q4', value=5.5),
                              dict(case='Downside', period='2026Q4', value=6)])
        self.assertIs(covenant.trigger_headroom(trigger)['sustained'], False)
        trigger['cases'][1].update(case='Base', period='2027Q1')
        self.assertIsNone(covenant.trigger_headroom(trigger)['sustained'])
        trigger['sustained_periods'] = ['2026Q4', '2027Q1']
        self.assertEqual(covenant.trigger_headroom(trigger)['sustained_cases'], ['Base'])
        trigger['cases'][1]['value'] = None
        self.assertIsNone(covenant.trigger_headroom(trigger)['sustained'])
        trigger['cases'] = []
        self.assertEqual(covenant.trigger_headroom(trigger)['classification'], 'insufficient information')

    def test_bond_rejects_unsupported_assumptions(self):
        base = dict(price=100, coupon=6, years_to_maturity=5)
        self.assertAlmostEqual(bond.compute(base)['yield_to_maturity'], .06)
        for changes in (dict(years_to_maturity=2.1), dict(years_to_maturity=2.2),
                        dict(convention={'compounding': 'annual'}), dict(accrued_interest=1),
                        dict(call_schedule=[dict(years=1.1, price=100)])):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                bond.compute(dict(base, **changes))
        self.assertEqual(bond.compute(dict(base, call_schedule=[dict(years=1, price=None)]))['status'], 'Not Calculable')
        for changes in (dict(recovery_assumption=.99, benchmark_yield=.04, horizon_years=.5),
                        dict(recovery_assumption=.4, benchmark_yield=.04, horizon_years=-1),
                        dict(recovery_assumption=2)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                bond.compute(dict(base, **changes))

    def test_current_catalyst_handoff_is_accepted(self):
        text = markdown(module_id='CP-2A', module_name='DownsidePathway')
        self.assertEqual(handoff.validate_text(text, filename='EXAMPLE_CP-2A_20260907.md').exit_code, 0)
        errors = []
        model_inputs._validate_auxiliary_envelope('CP-2A', text, None, errors)
        self.assertFalse(errors)
        self.assertEqual(model_inputs.CP2B_SNAPSHOT_TABLE, 'cp2b.cp_model_catalysts')

    def test_fenced_memo_examples_and_limitations_stay_out(self):
        text = ('## Analysis\n### Credit view\nActual conclusion.\n\n````text\n'
                '```\nExample only: revenue grew 900%.\n~~~\n- Fake finding.\n````\n\n'
                'Actual second conclusion.\n## Gaps & Conflicts\n~~~\n- Fake limitation.\n~~~\n- Actual limitation.')
        passages = memo_markdown.reader_passages(text)
        self.assertEqual([p.text for p in passages], ['Actual conclusion.', 'Actual second conclusion.'])
        self.assertEqual([p.text for p in memo_markdown.limitation_passages(text)], ['Actual limitation.'])

    def test_cli_never_serializes_nonfinite_results(self):
        script = ROOT / 'skills/cp-4c-restructuring-fulcrum/scripts/funding_gap.py'
        payload = dict(horizon_years=1, currency='USD', cash=1e308, forecast_fcf=1e308,
                       instruments=[dict(amount=10, years_to_maturity=1)])
        result = subprocess.run([sys.executable, '-B', str(script)], input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(result.stdout)
        self.assertEqual(json.loads(result.stderr)['status'], 'blocked')

    def test_package_verification_detects_tampering(self):
        import verify_package
        with tempfile.TemporaryDirectory() as scratch:
            package = Path(scratch) / 'package'
            shutil.copytree(ROOT, package)
            with patch.object(verify_package, 'ROOT', package):
                verify_package.sync_copies()
                verify_package.refresh_metadata()
                verify_package.verify_metadata()
                for relative in ('README.md', 'tests/test_regressions.py',
                                 'skills/cp-1-canonical-data-foundation/scripts/validate_handoff.py',
                                 'DEPLOY_V_COPILOT_MEMORY_PROMPT.md'):
                    path = package / relative
                    original = path.read_bytes()
                    path.write_bytes(original + b'\nchanged\n')
                    with self.subTest(path=relative), self.assertRaises(ValueError):
                        verify_package.verify_metadata()
                    path.write_bytes(original)
                for relative in ('unexpected.txt', 'skills/unindexed.txt'):
                    path = package / relative
                    path.write_text('unlisted')
                    with self.subTest(path=relative), self.assertRaises(ValueError):
                        verify_package.verify_metadata()
                    path.unlink()
                verify_package.verify_metadata()
                index = package / verify_package.INDEX
                original = index.read_bytes()
                wrong_route = json.loads(original)
                wrong_route['skills'][0]['aliases'] = []
                index.write_text(json.dumps(wrong_route))
                with self.assertRaises(ValueError):
                    verify_package.refresh_metadata()
                index.write_bytes(original)
                verify_package.verify_metadata()


def skill_text(slug):
    return (ROOT / 'skills' / slug / 'SKILL.md').read_text(encoding='utf-8')


def register(reg, columns, rows):
    return (f'### {reg}\n| ' + ' | '.join(columns) + ' |\n| ' + ' | '.join('---' for _ in columns) + ' |\n'
            + ''.join('| ' + ' | '.join(row) + ' |\n' for row in rows) + '\n')


def about(violations, reg):
    return [v for v in violations if v.startswith(reg + ':') or v.startswith(reg + ' row')]


class ForkR3Tests(unittest.TestCase):
    """Deployment fork r3: a register written as the method specifies it passes the method's own check."""

    def test_method_columns_pass_the_checker(self):
        # G2-6: the checker follows the step specs, and keeps a column a downstream reader reads.
        pipes = lambda text: text.split(' | ')
        cases = (
            ('cp-1-canonical-data-foundation', 'CP-1', 'T4.1', ['Source File Name', 'Document Type', 'Period Coverage', 'Currency', 'Unit',
                                                              'Perimeter', 'Accounting Basis', 'Evidence Quality Tier', 'Analytical Use', 'Limitations']),
            ('cp-1-canonical-data-foundation', 'CP-1', 'T4.10', ['KPI Category', 'Metric Name', 'FY2025', 'FY2024', 'Trend Direction', 'Analyst Note']),
            ('cp-1-canonical-data-foundation', 'CP-1', 'T4.14', pipes('period_id | fiscal_year | fiscal_quarter | period_type | start_date | end_date | day_count | audit_status | currency | unit | accounting_basis | entity_perimeter | source_id | source_locator | component_period_ids')),
            ('cp-1-canonical-data-foundation', 'CP-1', 'T4.18', pipes('facility_id | facility_name | period_id | facility_type | carrying_value | principal | drawn_amount | commitment | secured_status | seniority | currency | margin_or_coupon | maturity_date | lease_classification | source_id | source_locator')),
            ('cp-1b-earnings-delta', 'CP-1B', 'T4.6', ['Metric', 'Comparison Basis', 'Prior Value', 'Current Value', 'Abs Change', '% Change', 'Mgmt Driver', 'Analyst Driver', 'Credit Implication']),
            ('cp-1b-earnings-delta', 'CP-1B', 'T4.12', pipes('metric_id | current_period_id | reference_period_id | comparison_basis | current_value | reference_value | absolute_change | percentage_change | calculation_status | restatement_flag | basis_change_flag | perimeter_change_flag | definition_change_flag | values | changes')),
            ('cp-1b-earnings-delta', 'CP-1B', 'T4.15', pipes('downstream_module | status | blocking_metric_ids | blocking_period_ids | conflict_refs | explanation')),
            ('cp-1c-peer-benchmark', 'CP-1C', 'T4.5', ['Entity', 'Total/Net/Sr Sec Leverage', 'Int Coverage', 'Adj Int Coverage', 'FFO/Debt', 'Liquidity', 'Period', 'Currency', 'Calc Status', 'Comp Status']),
            ('cp-1c-peer-benchmark', 'CP-1C', 'T4.10', ['Method', 'Multiple Source', 'Multiple Value', 'Borrower Metric', 'Period', 'Implied EV', 'Low', 'Median', 'High', 'Calc Status', 'Limitations']),
        )
        for slug, module_id, reg, columns in cases:
            with self.subTest(module=module_id, register=reg):
                violations, contract, _ = complete.check(skill_text(slug), register(reg, columns, [['x'] * len(columns)]), module_id)
                self.assertEqual(about(violations, reg), [])
        kept = complete.load_contract(skill_text('cp-1b-earnings-delta'), 'CP-1B')['registers']['T4.12']['columns']
        self.assertTrue({'metric_id', 'values', 'changes'} <= set(kept))
        kept = complete.load_contract(skill_text('cp-1c-peer-benchmark'), 'CP-1C')['registers']['T4.5']['columns']
        self.assertIn('Total/Net/Sr Sec Leverage', kept)

    def test_forecast_cases_match_as_the_method_writes_them(self):
        # G3-13: `Base case` holds `base`; a word that only starts with it does not.
        columns = ['assumption_id', 'driver', 'case', 'period', 'value/range', 'unit', 'class', 'source', 'rationale']
        rows = [['A-1', 'Revenue', 'Base case', 'FY2026', '2%', 'pct', 'management_guidance', 'Guidance p4', 'Guided'],
                ['A-2', 'Revenue', 'DOWNSIDE (volume)', 'FY2026', '-5%', 'pct', 'analyst_judgment', 'Analysis', 'Stress']]
        text = register('T2H.3', columns, rows)
        violations, _, _ = complete.check(skill_text('cp-2g-forward-credit-model'), text, 'CP-2G')
        self.assertEqual(about(violations, 'T2H.3'), [])
        violations, _, _ = complete.check(skill_text('cp-2g-forward-credit-model'), text.replace('Base case', 'Baseline'), 'CP-2G')
        self.assertEqual(about(violations, 'T2H.3'),
                         ["T2H.3: cp2g.requires_base_and_downside_cases -- column 'case' lacks 'base'"])

    def test_a_direction_with_no_supported_driver_takes_one_row(self):
        # G2-15: CP-2's T2.10 needs Positive and Negative; a none-supported row states the missing one.
        columns = ['Rank', 'Driver', 'Evidence', 'Risk Mechanic', 'Credit Implication', 'Direction', 'Confidence']
        rows = [['1', 'Maturity wall', '10-K note 9', 'Refinancing need', 'Higher PD', 'Negative', 'High'],
                ['2', 'None supported', 'Filings reviewed; no supported positive driver', '—', '—', 'Positive', 'Not Assessable']]
        violations, _, _ = complete.check(skill_text('cp-2-fundamental-credit-synthesizer'), register('T2.10', columns, rows), 'CP-2')
        self.assertEqual(about(violations, 'T2.10'), [])

    def test_months_to_empty_is_a_register_with_columns(self):
        # G2-14: T2E.6 has the method's columns; a result it cannot calculate is still a row.
        contract = complete.load_contract(skill_text('cp-2d-liquidity-cash-flow-bridge'), 'CP-2D')
        columns = contract['registers']['T2E.6']['columns']
        self.assertEqual(columns, ['Calculation', 'Result', 'Formula / Inputs', 'Cash-Burn Basis', 'Status', 'Source Trace'])
        row = ['Months to Empty', 'Not Calculable', '250 / -4.0', 'FY2025, recurring; cash-generative, no runway to exhaust', 'Calculated', 'T2E.5']
        violations, _, _ = complete.check(skill_text('cp-2d-liquidity-cash-flow-bridge'), register('T2E.6', columns, [row]), 'CP-2D')
        self.assertEqual(about(violations, 'T2E.6'), [])

    def test_an_empty_upstream_bridge_is_carried_in_one_row(self):
        # G2-10: CP-1D carries CP-1's permitted empty bridge as one NONE row per register.
        contract = complete.load_contract(skill_text('cp-1d-earnings-quality'), 'CP-1D')
        text = ''
        for reg in ('T1D.1', 'T1D.2', 'T1D.3', 'T1D.4'):
            columns = contract['registers'][reg]['columns']
            text += register(reg, columns, [['NONE' if c in ('Add-Back ID', 'Step') else '—' for c in columns]])
        violations, _, _ = complete.check(skill_text('cp-1d-earnings-quality'), text, 'CP-1D')
        for reg in ('T1D.1', 'T1D.2', 'T1D.3', 'T1D.4'):
            self.assertEqual(about(violations, reg), [], reg)

    def test_absorbed_catalyst_rules_are_enforced(self):
        # G2-18: CP-2B's rules and table bind in CP-2A's own profile, as CP-2C's do in CP-1A's.
        contract = complete.load_contract(skill_text('cp-2a-downside-pathway'), 'CP-2A')
        self.assertIn('cp2b.cp_model_catalysts', contract['unconditional_stable_tables'])
        columns = contract['registers']['T5.3']['columns']
        row = {c: 'x' for c in columns}
        row.update({'Probability': 'Very likely', 'Risk Direction': 'Negative', 'Event ID': 'E-1'})
        violations, _, _ = complete.check(skill_text('cp-2a-downside-pathway'), register('T5.3', columns, [[row[c] for c in columns]]), 'CP-2A')
        self.assertTrue(any('cp2b.risk_probability_enum' in v for v in about(violations, 'T5.3')), violations)

    def test_screen_gap_register_may_be_empty(self):
        # G1-18: TL*.4 matches the payload's gap register, which may be empty.
        contract = complete.load_contract(skill_text('cp-l10-financial-change-screen'), 'CP-L10')
        for reg in ('TL10.4', 'TL20.4', 'TL23.4', 'TL30.4', 'TL40.4'):
            self.assertEqual(contract['registers'][reg]['minimum_body_rows'], 0, reg)
        violations, _, _ = complete.check(skill_text('cp-l10-financial-change-screen'),
                                          register('TL10.4', contract['registers']['TL10.4']['columns'], []), 'CP-L10')
        self.assertEqual(about(violations, 'TL10.4'), [])

    def test_one_opening_heading_per_artifact(self):
        # G2-18, G3-17, G1-18: an absorbed phase heads a later section, never a second opening.
        for slug in ('cp-1a-business-transaction-fact-pack', 'cp-2a-downside-pathway', 'cp-1d-earnings-quality',
                     'cp-2e-macro-fx-hedging-sensitivity', 'cp-l10-financial-change-screen'):
            text = skill_text(slug)
            with self.subTest(slug=slug):
                self.assertEqual(text.count('- **opening_h3**: ###'), 1)
                self.assertLessEqual(text.count('open `## Analysis` with `###') + text.count('Open `## Analysis` with `###'), 1)

    def test_canon_maps_status_and_defines_upgrade(self):
        # G3-12, G3-8, G2-18: the status map, UPGRADE and Not Reviewed are stated once, in the canon.
        canon = (ROOT / 'CANON_SHARED.md').read_text(encoding='utf-8')
        self.assertIn('D1 FROM MODULE STATUS', canon)
        self.assertIn('SEC5 UPGRADE', canon)
        self.assertIn("front-matter qa_status is always Passed, Restricted or Blocked, never Not Reviewed", canon)
        for path in (ROOT / 'skills').glob('*/SKILL.md'):
            text = path.read_text(encoding='utf-8')
            if '- **missing_input_behavior**: `UPGRADE`' in text:
                self.assertIn('- **UPGRADE** (canon SEC5)', text, path.parent.name)

    def test_qa_gate_order_and_deep_research_t8(self):
        # G1-14: CP-5 is CP-6's QA gate; G1-6: CP-DR is a T8 row on the routes that carry it.
        runbook = (ROOT / 'skills/cp-5-evidence-trace-validator/references/CP-5_RUNBOOK.md').read_text(encoding='utf-8')
        self.assertNotIn('CP-6, CP-6A)', runbook)
        cp6 = skill_text('cp-6-ic-debate-challenge')
        self.assertNotIn('**Downstream (QA):** CP-5', cp6)
        self.assertIn('**Upstream (QA gate):** CP-5', cp6)
        steps = (ROOT / 'skills/cp-0-source-readiness/references/REF_CP-0_STEPS.md').read_text(encoding='utf-8')
        self.assertIn('CP-8, CP-L10, CP-DR. Never recommend CP-X, CP-PARSE, a retired alias, CP-MODEL or CP-MEMO.', steps)

    def test_scripts_emit_no_bare_placeholder(self):
        # G3-15: an output the method says to transcribe never lands a refused placeholder.
        missing = covenant.headroom({'test': 'L', 'test_type': 'max-ratio', 'threshold': None, 'current_ratio': 4})
        self.assertEqual((missing['status'], missing['headroom_display']),
                         ('Not Calculable', '[Insufficient Information] — missing: threshold'))
        gap = covenant.trigger_headroom({'trigger': 'L', 'trigger_direction': 'max-ratio', 'threshold': 5,
                                         'cases': [{'period': 'FY26', 'value': None}]})
        self.assertEqual(gap['periods'][0]['status'], 'Not Calculable')
        result = recovery.waterfall(100, [dict(claim_id='S', amount=None)])
        self.assertEqual(result['allocation_state'], 'Not Calculable')

    def test_figure_spaces_range_and_percent_conventions(self):
        # N57: every digit-group space alike; an out-of-range exponent refused; the two percent readings documented.
        for spaced in ('1 234', '1 234', '1 234', '1 234'):
            self.assertEqual(tables.parse_figure(spaced), 1234.0, repr(spaced))
        for tiny in ('1e-400', '1e-310'):
            with self.subTest(value=tiny), self.assertRaises(ValueError):
                tables.parse_figure(tiny)
        self.assertEqual(tables.parse_figure('0e-400'), 0.0)
        self.assertEqual(tables.parse_figure('10.4%'), 10.4)
        errors = []
        self.assertAlmostEqual(model_inputs._number('10.4%', field='f', errors=errors), 0.104)
        self.assertIsNone(model_inputs._number('1e-400', field='f', errors=errors))
        self.assertEqual(len(errors), 1)


class ForkR4Tests(unittest.TestCase):
    """Deployment fork r4: what fork r3 left outside its rows (N70)."""

    def test_a_driver_that_cuts_both_ways_is_split_never_mixed(self):
        # N70: the canon deprecates Mixed (split); CP-2's method and checker allowed it.
        columns = ['Rank', 'Driver', 'Evidence', 'Risk Mechanic', 'Credit Implication', 'Direction', 'Confidence']
        split = [['1', 'Asset sale', 'Release p2', 'Debt paydown', 'Positive — Deleveraging', 'Positive', 'High'],
                 ['2', 'Asset sale', 'Release p2', 'Lost EBITDA', 'Negative — Revenue Decline', 'Negative', 'High']]
        slug = 'cp-2-fundamental-credit-synthesizer'
        violations, _, _ = complete.check(skill_text(slug), register('T2.10', columns, split), 'CP-2')
        self.assertEqual(about(violations, 'T2.10'), [])
        mixed = split + [['3', 'Asset sale', 'Release p2', 'Both', 'Neutral — Stable', 'Mixed', 'Low']]
        violations, _, _ = complete.check(skill_text(slug), register('T2.10', columns, mixed), 'CP-2')
        self.assertTrue(any('cp2.materiality_direction_enum' in v for v in about(violations, 'T2.10')), violations)
        for name in ('references/REF_CP-2_STEPS.md', 'references/CP-2_SCHEMA_REFERENCE.md',
                     'references/CP-2_SYSTEM_REFERENCE.md'):
            text = (ROOT / 'skills' / slug / name).read_text(encoding='utf-8')
            with self.subTest(name=name):
                self.assertNotIn('Negative / Mixed', text)
                self.assertNotIn('Negative | Mixed', text)
                self.assertIn('Mixed->split', text)

    def test_cp_model_tables_are_unconditional_only(self):
        # N70: each was listed as a conditional appendix register and an unconditional stable table.
        for slug, module_id, table in (('cp-2-fundamental-credit-synthesizer', 'CP-2', 'cp2.cp_model_strengths_weaknesses'),
                                       ('cp-2g-forward-credit-model', 'CP-2G', 'cp2g.cp_model_forecast_drivers')):
            text = skill_text(slug)
            with self.subTest(module=module_id):
                self.assertIn('  - **conditional_register_ids**: none\n', text)
                self.assertNotIn('**conditional_register_ids**: ' + table, text)
                self.assertIn(table, complete.load_contract(text, module_id)['unconditional_stable_tables'])

    def test_the_research_brief_is_followed_only_where_it_is_delivered(self):
        # N70: every module but CP-L10 was told to use a brief only CP-DR is delivered.
        pointer = 'where `../cp-os-credit-os/references/CP_DR_RESEARCH_BRIEF_V1.md` is delivered with this module'
        unconditioned = 'Otherwise use `../cp-os-credit-os/references/CP_DR_RESEARCH_BRIEF_V1.md`'
        paragraphs = 0
        for path in sorted((ROOT / 'skills').glob('*/SKILL.md')):
            text = path.read_text(encoding='utf-8')
            with self.subTest(skill=path.parent.name):
                self.assertNotIn(unconditioned, text)
            paragraphs += pointer in text
        self.assertEqual(paragraphs, 20)
        canon = (ROOT / 'CANON_SHARED.md').read_text(encoding='utf-8')
        self.assertIn('Where `skills/cp-os-credit-os/references/CP_DR_RESEARCH_BRIEF_V1.md` is delivered with a module, follow it', canon)


@unittest.skipUnless(os.environ.get('DEPLOY_V_INTEGRATION') == '1', 'enable integration for native PDF and DOCX dependencies')
class IntegrationTests(unittest.TestCase):
    def test_exporter_binds_current_catalyst_owner(self):
        domain = module('cp-model', 'cp_model_v3.domain')
        self.assertIn('CP-2A', domain.BundlePaths(*(Path('source.md') for _ in range(5))).by_module())
        row = dict(rank='1', event_date_or_window='2026-10-01', event='Refinancing',
                   credit_relevance='Maturity extension', source_id='S1', source_locator='p. 1', as_of='2026-09-07')
        self.assertEqual(domain._parse_catalysts([row])[0].owner, 'CP-2A')
        exporter = ROOT / 'skills/cp-model/scripts/export_cp_model_v3.py'
        with tempfile.TemporaryDirectory() as scratch:
            for option in ('--cp2a', '--cp2b'):
                args = [sys.executable, '-B', str(exporter)]
                for flag in ('--cp1', '--cp1a', '--cp1b', '--cp2', option):
                    args.extend((flag, str(Path(scratch) / 'missing.md')))
                args.extend(('--output-dir', str(Path(scratch) / 'output')))
                result = subprocess.run(args, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                blocked = json.loads(result.stdout)
                self.assertIn('CP-2A', [item['module_id'] for item in blocked['source_artifacts']])
                self.assertFalse((Path(scratch) / 'output').exists())

    def test_real_pdf_page_names_and_containment(self):
        from pypdf import PdfWriter
        builder = module('cp-memo-credit-research-report', 'cp_memo.builder')
        renderer = module('cp-memo-credit-research-report', 'cp_memo.render_pdf')
        raster = shutil.which('pdftoppm')
        self.assertIsNotNone(raster, 'pdftoppm is required for integration checks')
        for count in (9, 10, 100):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as scratch:
                workspace = Path(scratch).resolve()
                render = workspace / 'render'; render.mkdir()
                writer = PdfWriter()
                for _ in range(count):
                    writer.add_blank_page(width=20, height=20)
                writer.write(render / 'draft.pdf')
                subprocess.run([raster, '-png', '-r', '10', str(render / 'draft.pdf'), str(render / 'page')], check=True, capture_output=True)
                pages = sorted(render.glob('page-*.png'), key=renderer._page_number)
                payload = dict(page_count=count, pages=list(map(str, pages)))
                self.assertEqual(builder._validate_session_render(payload, workspace), count)
                pages[0].unlink()
                pages[0].symlink_to(render / 'draft.pdf')
                with self.assertRaises(ValueError):
                    builder._validate_session_render(payload, workspace)


if __name__ == '__main__':
    unittest.main()
