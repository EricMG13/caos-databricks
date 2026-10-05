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


class ForkR5Tests(unittest.TestCase):
    """Deployment fork r5: the method states the rules its checkers enforce (2 October 2026 live runs)."""

    def test_cp1_audit_sections_are_the_validators_h2s(self):
        # CP-1's method said Evidence Trace and Source Registry were appendix sub-sections;
        # the validator requires each once at H2, and a model demoted both to ####.
        steps = (ROOT / 'skills/cp-1-canonical-data-foundation/references/REF_CP-1_STEPS.md').read_text(encoding='utf-8')
        self.assertNotIn('holds ALL audit items as sub-sections', steps)
        self.assertIn('Source Registry in place of the H2 fails validation', steps)
        self.assertNotIn('Source Gate / Readiness', steps)
        rule = 'H2 headings must be exactly once and in canonical order: ' + ' -> '.join(handoff.CANONICAL_HEADINGS)
        self.assertIn(f'("{rule}")', steps)
        demoted = markdown().replace('## Evidence Trace', '#### Evidence Trace')
        errors = handoff.validate_text(demoted, filename='EXAMPLE_CP-1_20260907.md').errors
        self.assertTrue(any(error.startswith(rule + ';') for error in errors), errors)

    def test_a_register_heading_binds_within_four_non_blank_lines(self):
        # CP-0 T6 was refused as missing: five blockquote lines sat between its heading and table.
        canon = (ROOT / 'CANON_SHARED.md').read_text(encoding='utf-8')
        self.assertIn('Failing that, the nearest heading above the table finds it at any\ndistance', canon)
        self.assertNotIn('A heading five or\nmore non-blank lines above its table leaves the register missing', canon)
        table = '| Evidence | Locator |\n| --- | --- |\n| Cash | p1 |\n'
        # Fork r6: past the four lines, the nearest heading above the table still binds it.
        for notes in (3, 4):
            text = '#### T6 — Evidence Trace\n\n' + ''.join(f'> note {n}\n\n' for n in range(notes)) + table
            with self.subTest(notes=notes):
                self.assertIn('T6', complete.find_registers(text, ['T6']))

    def test_a_cp1_interface_register_is_one_tagged_table(self):
        # A CP-1 that wrote T4.14-T4.19 untagged and again as tagged copies ran to 84 KB, and its
        # copies drifted from the registers. One tagged table serves the register check, the
        # interface parser and CP-MODEL; the two-copy form still reads the same.
        skill = skill_text('cp-1-canonical-data-foundation')
        self.assertIn('Never repeat a register as a second, tagged copy. An absent value in these tables is `null`, '
                      "not the canon's `—`, and every such `null` is also listed in `## Gaps & Conflicts`", skill)
        columns = complete.load_contract(skill, 'CP-1')['registers']['T4.14']['columns']
        row = ['FY2025', '2025', 'null', 'FY', '2025-01-01', '2025-12-31', '365', 'Audited', 'USD', 'millions',
               'US GAAP', 'Consolidated', 'S1', '10-K p. 53', 'null']
        table = register('T4.14', columns, [row]).split('\n', 1)[1]
        tag = '<!-- table-id: cp1.model_period_register -->\n'
        single = '#### T4.14 — Model Period Register\n\n' + tag + table
        two_copy = '#### T4.14 — Model Period Register\n\n' + table + '\n' + tag + table
        for form, text in (('single', single), ('two-copy', two_copy)):
            with self.subTest(form=form):
                violations, _, present = complete.check(skill, text, 'CP-1')
                self.assertEqual(about(violations, 'T4.14'), [])
                self.assertEqual(present['T4.14'][1][0]['component_period_ids'], 'null')
                self.assertNotIn('cp1.model_period_register: CP-MODEL interface table missing -- it is emitted on '
                                 'every run, not only when CP-MODEL was requested', violations)
                parsed = tables.parse_tables(text)['cp1.model_period_register']
                self.assertTrue(tables.is_null(parsed.rows[0]['fiscal_quarter']))
                stable = model_inputs.parse_stable_tables(text)['cp1.model_period_register']
                self.assertEqual(model_inputs._list(stable[0]['component_period_ids']), [])
        # A critical `null` passes the critical-cell check, as the canon's `—` did; n/a and blanks do not.
        blocked = complete.load_contract(skill, 'CP-1')['blocklist']
        self.assertNotIn('null', blocked)
        self.assertTrue({'', 'n/a', 'tbd'} <= blocked)
        # CP-MODEL skips only blank and heading lines after a tag: a comment between tag and table is refused.
        commented = single.replace(tag, tag + '\n<!-- note -->\n')
        with self.assertRaises(model_inputs.ContractError):
            model_inputs.parse_stable_tables(commented)
        # Notes and the tag between heading and table: the nearest heading still binds it (fork r6).
        late = '#### T4.14 — Model Period Register\n\n' + ''.join(f'note {n}\n' for n in range(3)) + tag + table
        self.assertIn('T4.14', complete.find_registers(late, ['T4.14']))
        self.assertIn('cp1.model_period_register', tables.parse_tables(late))


def _r5_parse_tables(text, cells=False):
    """`cp_tables.parse_tables` as fork r5 shipped it: the reference every r6 tolerance is held to.
    With `cells`, its binding with r6's cell reading (one-hyphen separators, escaped pipes)."""
    import re
    lines = handoff.unfenced_markdown(text).splitlines()
    out, pending_id, i = {}, None, 0
    while i < len(lines):
        line = lines[i]
        m = tables.TABLE_ID_RE.fullmatch(line.strip())
        if m:
            if pending_id is not None:
                raise ValueError(f'{pending_id}: table-id has no following table')
            if m.group(1) in out:
                raise ValueError(f'{m.group(1)}: duplicate table-id')
            pending_id = m.group(1)
            i += 1
            continue
        stripped = line.strip()
        if pending_id and stripped.startswith('|') and stripped.count('|') >= 2:
            header = tables._split_row(stripped)
            if not all(header) or len(header) != len(set(header)):
                raise ValueError('columns')
            i += 1
            if i >= len(lines) or len(tables._split_row(lines[i])) != len(header) or not all(
                    re.fullmatch(r':?-+:?' if cells else r':?-{3,}:?', cell) for cell in tables._split_row(lines[i])):
                raise ValueError('separator')
            i += 1
            rows = []
            while i < len(lines):
                row = lines[i].strip()
                if not row.startswith('|'):
                    break
                split = tables._row_cells(row, len(header)) if cells else tables._split_row(row)
                if len(split) != len(header):
                    raise ValueError('width')
                rows.append(dict(zip(header, split)))
                i += 1
            out[pending_id] = (header, rows)
            pending_id = None
            continue
        if stripped and not stripped.startswith('<!--'):
            pending_id = pending_id if stripped.startswith('|') else None
        i += 1
    if pending_id is not None:
        raise ValueError('dangling')
    return out


def _r5_find_registers(text):
    """`completeness_check.find_registers(text)` as fork r5 shipped it, with no ID list."""
    lines = handoff.unfenced_markdown(text).splitlines()
    out, recent, i = {}, [], 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith('|') and s.count('|') >= 2 and not tables.SEPARATOR_RE.match(s):
            header, j = tables._split_row(s), i + 1
            if j < len(lines) and tables.SEPARATOR_RE.match(lines[j].strip()) and '|' in lines[j]:
                j += 1
            rows = []
            while j < len(lines) and lines[j].strip().startswith('|'):
                cells = tables._split_row(lines[j].strip())
                cells += [''] * (len(header) - len(cells))
                rows.append(dict(zip(header, cells[:len(header)])))
                j += 1
            labels = [x for x in reversed(recent) if x.startswith('#')] + [x for x in reversed(recent) if not x.startswith('#')]
            for label in labels:
                match = complete.REGISTER_ID_RE.search(label)
                if match:
                    out.setdefault(match.group(1), (header, rows))
                    break
            i, recent = j, []
            continue
        if s:
            recent = (recent + [s])[-4:]
        i += 1
    return out


class ForkR6Tests(unittest.TestCase):
    """Deployment fork r6: the readers tolerate what well-meaning answers wrote, and refuse what they did before."""

    GOOD = '| a | b |\n| --- | --- |\n| 1 | 2 |\n'

    def test_one_malformed_interface_table_is_named_alone(self):
        # P1 CP-1 #1: one 14-cell row of a 15-column table voided all seven interface tables.
        short = '| a | b |\n| --- | --- |\n| 1 | 2 |\n| FY2024 |\n| 3 |\n'
        text = '<!-- table-id: x.good -->\n' + self.GOOD + '\n<!-- table-id: x.short -->\n' + short
        found, errors = tables.read_tables(text)
        self.assertEqual(list(found), ['x.good'])
        self.assertEqual(errors, {'x.short': 'x.short: row 2 (first cell `FY2024`) has 1 cells, header has 2 -- '
                                             'table row width differs from its header; 1 more row(s) differ'})
        # The guarantee: a short row is still refused, and `parse_tables` still refuses the whole document.
        with self.assertRaisesRegex(ValueError, '^x.short: row 2 '):
            tables.parse_tables(text)
        skill = skill_text('cp-1-canonical-data-foundation').replace(
            'cp1.model_period_register; cp1.model_account_register', 'x.good; x.short; cp1.model_account_register')
        violations = complete.check(skill, text, 'CP-1')[0]
        self.assertIn(errors['x.short'], violations)
        self.assertFalse([v for v in violations if v.startswith(('x.good', 'x.short: CP-MODEL'))], violations)
        self.assertIn('cp1.model_account_register: CP-MODEL interface table missing -- it is emitted on every run, '
                      'not only when CP-MODEL was requested', violations)
        for fault, message in (('| a | a |\n| --- | --- |\n', 'table columns must be nonempty and unique'),
                               ('| a | b |\n| 1 | 2 |\n', 'missing or malformed table separator')):
            with self.subTest(fault=message):
                found, errors = tables.read_tables('<!-- table-id: x.bad -->\n' + fault + '\n<!-- table-id: x.good -->\n' + self.GOOD)
                self.assertEqual((list(found), errors), (['x.good'], {'x.bad': f'x.bad: {message}'}))

    def test_a_tag_crosses_a_heading_to_the_next_table_only(self):
        # P1 CP-1 #3 put the readiness tag above `#### CP-MODEL Readiness`; the heading broke the bind.
        crossed = '<!-- table-id: x.t -->\n\n#### CP-MODEL Readiness\n\n' + self.GOOD
        self.assertEqual(tables.parse_tables(crossed)['x.t'].rows, [{'a': '1', 'b': '2'}])
        self.assertEqual(model_inputs.parse_stable_tables(crossed)['x.t'], [{'a': '1', 'b': '2'}])
        # The guarantees: a tag binds only the next table, across nothing but blank, comment and heading lines.
        for name, text in (('prose', '<!-- table-id: x.t -->\n#### H\nA note.\n' + self.GOOD),
                           ('h2', '<!-- table-id: x.t -->\n## Gaps & Conflicts\n' + self.GOOD),
                           ('next tag', '<!-- table-id: x.t -->\n#### H\n<!-- table-id: x.u -->\n' + self.GOOD),
                           ('malformed', '<!-- table-id: x.t -->\n#### H\n| a | b |\n| 1 | 2 |\n'),
                           ('twice', '<!-- table-id: x.t -->\n#### H\n' + self.GOOD + '\n<!-- table-id: x.t -->\n#### H\n' + self.GOOD)):
            with self.subTest(case=name):
                self.assertNotIn('x.t', tables.parse_tables(text))
        # A tag that binds the strict way wins over one that crossed a heading, as before.
        later = '<!-- table-id: x.t -->\n#### H\n| a | b |\n| --- | --- |\n| 0 | 0 |\n\n<!-- table-id: x.t -->\n' + self.GOOD
        self.assertEqual(tables.parse_tables(later)['x.t'].rows, [{'a': '1', 'b': '2'}])
        # Directly under the tag, a malformed table is still refused.
        with self.assertRaisesRegex(ValueError, 'separator'):
            tables.parse_tables('<!-- table-id: x.t -->\n| a | b |\n| 1 | 2 |\n')

    def test_one_hyphen_separators_and_escaped_pipes_read_alike(self):
        # A row that splits to the header's width at every `|` reads as before: `C:\` ends its cell.
        text = '<!-- table-id: x.t -->\n| a | b |\n|-|:-:|\n| x \\| y | z |\n| w | C:\\|\n'
        rows = [{'a': 'x | y', 'b': 'z'}, {'a': 'w', 'b': 'C:\\'}]
        self.assertEqual(tables.parse_tables(text)['x.t'].rows, rows)
        self.assertEqual(model_inputs.parse_stable_tables(text)['x.t'], rows)
        with self.assertRaises(ValueError):
            tables.parse_tables(text.replace('| x \\| y | z |', '| x \\| y \\| z |'))

    def test_every_document_read_before_reads_the_same(self):
        # Held against fork r5's reader over random documents: a tolerance only reads what it refused.
        import random
        vocabulary = ['', '<!-- table-id: x.a -->', '<!-- table-id: x.b -->', '<!-- note -->', '#### H', '## H2',
                      'prose', '| a | b |', '| --- | --- |', '|-|-|', '| 1 | 2 |', '| 3 |', '| x \\| y | z |',
                      '| --- | --- | --- |', '| w | C:\\|',
                      '| 1 | 2 | 3 |', '|', '---|---', '```', '> quote']
        generator = random.Random(20261003)
        compared = 0
        for _ in range(6000):
            text = '\n'.join(generator.choice(vocabulary) for _ in range(generator.randint(1, 14)))
            try:
                before = _r5_parse_tables(text)
            except ValueError:
                continue
            compared += 1
            now = {k: (t.columns, t.rows) for k, t in tables.parse_tables(text).items()}
            self.assertEqual({k: now[k] for k in before}, before, text)
            self.assertEqual([k for k in now if k in before], list(before), text)
        self.assertGreater(compared, 1000)

    def test_every_register_bound_before_is_bound_the_same(self):
        import random
        vocabulary = ['', '#### T6 — Trace', '### T4.5', '## Analysis', '#### Notes', 'see T4.5', '> note', 'prose',
                      '| a | b |', '| --- | --- |', '| 1 | 2 |', '| c | d |', '```'] + ['> note', 'prose'] * 4
        generator = random.Random(3102026)
        added = 0
        for _ in range(6000):
            text = '\n'.join(generator.choice(vocabulary) for _ in range(generator.randint(1, 24)))
            before, now = _r5_find_registers(text), complete.find_registers(text)
            self.assertEqual({k: now.get(k) for k in before}, before, text)
            added += len(now) > len(before)
        self.assertGreater(added, 50)

    def test_the_cp1_skeleton_reads_as_every_reader_requires(self):
        # No CP-1 answer of 2-3 October had a worked example of heading, tag, table and its nulls' gap lines.
        import re
        from datetime import date
        steps = (ROOT / 'skills/cp-1-canonical-data-foundation/references/REF_CP-1_STEPS.md').read_text(encoding='utf-8')
        [skeleton] = re.findall(r'^```markdown\n(#### T4\.14 .*?)^```$', steps, re.M | re.S)
        skill = skill_text('cp-1-canonical-data-foundation')
        self.assertIn('A worked skeleton is in `references/REF_CP-1_STEPS.md` § REF_CP-1_13.', skill)
        self.assertIn('never a note row inside them (its empty cells fail the register check); a note goes to T4.12', skill)
        violations, _, present = complete.check(skill, skeleton, 'CP-1')
        self.assertEqual(about(violations, 'T4.14'), [])
        self.assertEqual(len(present['T4.14'][1]), 2)
        self.assertEqual(complete.load_contract(skill, 'CP-1')['registers']['T4.14']['columns'], present['T4.14'][0])
        self.assertFalse([v for v in violations if v.startswith('cp1.model_period_register')], violations)
        rows = model_inputs.parse_stable_tables(skeleton)['cp1.model_period_register']
        self.assertEqual([r for r in tables.parse_tables(skeleton)['cp1.model_period_register'].rows], list(rows))
        gaps = skeleton.split('## Gaps & Conflicts', 1)[1]
        for row in rows:
            self.assertIn(row['period_type'], model_inputs.PERIOD_TYPES)
            self.assertIn(row['audit_status'], model_inputs.AUDIT_STATUSES)
            self.assertIn(row['unit'], model_inputs.PERIOD_UNITS)
            start, end = date.fromisoformat(row['start_date']), date.fromisoformat(row['end_date'])
            self.assertEqual(int(row['day_count']), (end - start).days + 1)
            self.assertEqual(model_inputs._list(row['component_period_ids']), [])
            for column, value in row.items():
                if value == 'null':
                    self.assertRegex(gaps, rf'T4\.14, [^\n]*{re.escape(row["period_id"])}[^\n]*`{column}`: null — ')

    def test_the_canon_spells_null_and_qa_status_as_the_checkers_read_them(self):
        canon = (ROOT / 'CANON_SHARED.md').read_text(encoding='utf-8')
        # `blank` is on every critical-cell blocklist and `Not Reviewed` is not a handoff's qa_status.
        self.assertNotIn('null/blank', canon)
        self.assertNotIn('null / blank', canon)
        self.assertNotIn('| Not Reviewed / Passed', canon)
        self.assertNotIn('qa_status(Not Reviewed', canon)
        self.assertEqual(canon.count('| QA status | Passed / Restricted / Blocked (never Not Reviewed) |'), 4)
        self.assertEqual(canon.count('never an empty cell: `—` in an untagged register, `null` in a tagged table'), 3)
        self.assertNotIn('Not Reviewed', handoff.QA_STATUSES)
        # The QA severity rule the validator enforces (`_finding_severities`) is stated beside the caps.
        self.assertIn('The validator reads every table under `## QA Validation` with a Severity column as findings\n'
                      '  against this handoff', canon)
        table = '| Finding | Severity |\n| --- | --- |\n| Source gap | MATERIAL |\n'
        body = markdown().replace('## QA Validation\nSupported conclusion.\n', '## QA Validation\n' + table)
        errors = handoff.validate_text(body, filename='EXAMPLE_CP-1_20260907.md').errors
        self.assertTrue(any(e.startswith('a MATERIAL finding requires qa_status Restricted') for e in errors), errors)
        moved = markdown().replace('## Analysis\nSupported conclusion.\n', '## Analysis\n' + table)
        self.assertEqual(handoff.validate_text(moved, filename='EXAMPLE_CP-1_20260907.md').exit_code, 0)

    def test_a_tag_below_its_table_never_crosses_into_the_next(self):
        # Fix round 1 (C1): tags written below their tables crossed the next heading and bound
        # the next register's table under the wrong id.
        def block(k, heading):
            return f'{heading}\n\n| c{k} | v{k} |\n| --- | --- |\n| r{k} | 1 |\n\n<!-- table-id: x.t{k} -->\n\n'
        for heading in ('#### T{k} — Register', '#### Operating KPI Schedule {k}'):
            text = ''.join(block(k, heading.format(k=k)) for k in (1, 2, 3))
            with self.subTest(heading=heading):
                self.assertEqual(tables.read_tables(text)[0], {})
                with self.assertRaises(model_inputs.ContractError):
                    model_inputs.parse_stable_tables(text)
        # Nor across a heading naming a register, even after a tagged table.
        named = '<!-- table-id: x.a -->\n' + self.GOOD + '\n<!-- table-id: x.b -->\n#### T4.15 — Accounts\n' + self.GOOD
        self.assertEqual(list(tables.parse_tables(named)), ['x.a'])
        # Across a heading naming no register, after a tagged table or a heading, it still binds.
        after = named.replace('#### T4.15 — Accounts', '#### CP-MODEL Readiness')
        self.assertEqual(list(tables.parse_tables(after)), ['x.a', 'x.b'])
        self.assertEqual(list(model_inputs.parse_stable_tables(after)), ['x.a', 'x.b'])

    def test_a_crossing_tag_binds_only_when_its_id_is_tagged_once(self):
        # Fix round 1 (I1): a second tag of the id, before a malformed table, prose or nothing, left
        # the crossed read bound, and CP-MODEL refused the duplicate.
        bad = '| a | b |\n| --- | --- |\n| 1 |\n'
        first = '<!-- table-id: x.t -->\n#### H\n' + self.GOOD + '\n<!-- table-id: x.t -->\n'
        for name, rest in (('malformed', '#### H2\n' + bad), ('prose', '#### H2\nA note.\n'), ('nothing', '#### H2\n')):
            with self.subTest(second=name):
                self.assertEqual(tables.read_tables(first + rest), ({}, {}))
                with self.assertRaises(model_inputs.ContractError):
                    model_inputs.parse_stable_tables(first + rest)
        # Only blank and heading lines across a crossing, as CP-MODEL reads it.
        for line in ('<!-- c -->', '|'):
            with self.subTest(between=line):
                self.assertNotIn('x.t', tables.parse_tables('<!-- table-id: x.t -->\n#### H\n' + line + '\n' + self.GOOD))

    def test_an_escaped_pipe_never_shifts_a_critical_cell(self):
        # Fix round 1 (C2): the interface reader read `\|` as text while the register locator split
        # at it and truncated, so a blank or placeholder critical cell slid out of its column.
        skill = ('\n## Output profile — binding on CP-X\'s canonical Markdown\n\n'
                 '- **completeness_contract**: structured below\n'
                 '  - **full_run_disqualifiers**: structured below\n'
                 '    - **critical_cell_values_casefold**: ; n/a; tbd\n'
                 '  - **required_registers**: structured below\n'
                 '    - **T1.1**: structured below\n'
                 '      - **columns**: Item; Locator; Refs\n'
                 '      - **critical_columns**: identical to columns\n'
                 '      - **disqualifier_exempt_columns**: none\n'
                 '      - **minimum_body_rows**: 1\n')
        for refs in ('', 'n/a', 'TBD'):
            row = f'| Revenue | FY2024 results \\| p. 4 | {refs} |'
            text = f'### T1.1 — Accounts\n<!-- table-id: x.t -->\n| Item | Locator | Refs |\n| --- | --- | --- |\n{row}\n'
            with self.subTest(refs=refs):
                violations = complete.check(skill, text, 'CP-X')[0]
                self.assertEqual(violations, [f"T1.1 row 1: critical column 'Refs' holds a disqualifying placeholder {refs!r}"])
                cells = complete.find_registers(text, ['T1.1'])['T1.1'][1][0]
                self.assertEqual(list(cells.values()), list(tables.parse_tables(text)['x.t'].rows[0].values()))

    def test_a_row_opening_on_a_double_pipe_is_never_re_read(self):
        # Fix round 1 (M1): CP-MODEL strips every edge pipe and `cp_tables` one, so the escaped
        # re-read of `|| S1 | ... \| note 4 |` gave the two readers different cells.
        head = '<!-- table-id: x.t -->\n| a | b | c |\n| --- | --- | --- |\n'
        for row in ('|| S1 | 10-K p. 53 \\| note 4 |', '| S1 | 10-K p. 53 \\| note 4 ||'):
            with self.subTest(row=row):
                with self.assertRaisesRegex(ValueError, 'table row width differs'):
                    tables.parse_tables(head + row + '\n')
                self.assertEqual(tables._row_cells(row, 3), tables._split_row(row))
                self.assertEqual(model_inputs._row_values(row, 3), model_inputs._split_row(row))

    def test_the_three_readers_agree_on_what_the_tolerances_accept(self):
        # Fix round 1 (M4): over documents the r5 reader refused or read otherwise, each table the
        # r6 interface reader newly binds is the one its tag was written for, its id is tagged once,
        # CP-MODEL reads it alike, and the register locator reads the same cells. (A tag directly
        # above the next table binds it, as in r5, whichever table the writer meant: only a binding
        # across a heading is held to the writer's table.)
        import random
        generator = random.Random(4102026)
        rows = ['| r{k} | 1 |', '| r{k} \\| s | 2 |', '|| r{k} | 3 |', '| r{k} | TBD |', '| r{k} \\| s | |',
                '| r{k} |', '| r{k} | 4 ||']
        headings = ['#### T{k} — Register', '#### Section {k}', '#### CP-MODEL Readiness', '## H2', 'A note.', '']
        placements = ['above heading', 'below heading', 'below table', 'none', 'twice', 'twice bad']
        fresh_docs = 0
        for _ in range(20000):
            lines = []
            for k in range(1, generator.randint(1, 4) + 1):
                tag, heading = f'<!-- table-id: x.t{k} -->', generator.choice(headings).format(k=k)
                place = generator.choice(placements)
                table = [f'| c{k} | v{k} |', generator.choice(['| --- | --- |', '|-|:-:|'])]
                table += [generator.choice(rows).format(k=k) for _ in range(generator.randint(1, 2))]
                lines += [tag, ''] if place in ('above heading', 'twice', 'twice bad') else []
                lines += [heading, ''] if heading else []
                lines += [tag, ''] if place == 'below heading' else []
                lines += table + ['']
                lines += [tag, ''] if place == 'below table' else []
                lines += [tag, '#### Again', '', 'A note.', ''] if place == 'twice' else []
                lines += [tag, '#### Again', '', f'| c{k} | v{k} |', '| --- | --- |', '| r |', ''] if place == 'twice bad' else []
            text = '\n'.join(lines)
            try:
                now = tables.parse_tables(text)
            except ValueError:
                continue
            try:
                before = _r5_parse_tables(text)
            except ValueError:
                before = {}
            try:
                bound = _r5_parse_tables(text, cells=True)
            except ValueError:
                bound = {}
            fresh = [i for i, t in now.items() if before.get(i) != (t.columns, t.rows)]
            fresh_docs += bool(fresh)
            for table_id in fresh:
                table, tag = now[table_id], f'<!-- table-id: {table_id} -->'
                if bound.get(table_id) != (table.columns, table.rows):  # bound across a heading
                    self.assertEqual(table.columns, ['c' + table_id[3:], 'v' + table_id[3:]], text)
                self.assertEqual(lines.count(tag), 1, text)
                start = lines.index(tag)
                end = next(j for j in range(start + 1, len(lines)) if lines[j].startswith('|'))
                while end < len(lines) and lines[end].startswith('|'):
                    end += 1
                model = model_inputs.parse_stable_tables('\n'.join(lines[start:end]))[table_id]
                self.assertEqual([list(r.values()) for r in model], [list(r.values()) for r in table.rows], text)
                register = 'T' + table_id[3:]
                found = complete.find_registers(text, [register]).get(register)
                if found and found[0] == table.columns:
                    self.assertEqual([list(r.values()) for r in found[1]], [list(r.values()) for r in table.rows], text)
            try:
                model = model_inputs.parse_stable_tables(text)
            except model_inputs.ContractError:
                continue
            for table_id, table in now.items():
                self.assertEqual([list(r.values()) for r in model[table_id]], [list(r.values()) for r in table.rows], text)
        self.assertGreater(fresh_docs, 1000)

    def test_the_nearest_heading_binds_its_next_table_at_any_distance(self):
        # N4 CP-0 #5: five blockquote lines sat between `#### T6 — Evidence Trace` and its table.
        notes = ''.join(f'> note {n}\n\n' for n in range(5))
        self.assertIn('T6', complete.find_registers('#### T6 — Evidence Trace\n\n' + notes + self.GOOD, ['T6']))
        # The guarantees: a heading binds only the next table below it, and only as the nearest heading.
        other = '| c | d |\n| --- | --- |\n| 3 | 4 |\n\n'
        between = complete.find_registers('#### T6\n\n' + notes + other + notes + self.GOOD, ['T6'])
        self.assertEqual(between['T6'][0], ['c', 'd'])
        shadowed = '#### T6\n\n' + notes + '#### Notes\n\n' + notes + self.GOOD
        self.assertNotIn('T6', complete.find_registers(shadowed, ['T6']))
        # Within the four lines, the nearest line naming a register binds, past a heading naming none.
        self.assertIn('T6', complete.find_registers('#### T6\n#### Notes\n' + self.GOOD, ['T6']))
        # A binding made the near way, anywhere, is never displaced by a distant heading.
        near = '#### T6\n\n' + notes + other + '#### T6 — again\n' + self.GOOD
        self.assertEqual(complete.find_registers(near, ['T6'])['T6'][0], ['a', 'b'])


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
