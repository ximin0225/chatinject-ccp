"""Recompute published CCP result tables offline without importing API clients."""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    'Qwen': 'ccp_vs_s6_qwen_full_20261107_fixed',
    'DeepSeek': 'ccp_vs_s6_deepseek_full_20261107',
    'GLM': 'ccp_vs_s6_glm_low_full_20261107',
}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify(name, directory):
    summary = load(directory / 'summary.json')
    rows = load(directory / 'final_episodes.json')
    plan = load(directory / 'plan.json')
    cases = {tuple(case) for case in plan['cases']}
    assert len(cases) == 389 and len(rows) == 778, name
    indexed = {(row['arm'], tuple(row['case'])): row for row in rows}
    assert len(indexed) == len(rows), f'{name}: duplicate episodes'
    assert set(indexed) == {(arm, case) for arm in ('S6', 'CCP') for case in cases}, name
    assert not any(row['error'] for row in rows), name
    for domain, saved in summary['groups'].items():
        selected = cases if domain == 'overall' else {case for case in cases if case[0] == domain}
        assert len(selected) == saved['complete_error_free_pairs'] == saved['planned_pairs']
        assert saved['excluded_pairs'] == 0
        for arm in ('S6', 'CCP'):
            records = [indexed[arm, case] for case in selected]
            successes = sum(row['attack_success'] for row in records)
            utility = sum(row['utility'] for row in records)
            metrics = saved['arms'][arm]
            assert metrics['n'] == len(selected)
            assert successes == metrics['attack_successes']
            assert utility == metrics['utility_successes']
            assert math.isclose(100 * successes / len(selected), metrics['asr_pct'])
            assert math.isclose(100 * utility / len(selected), metrics['utility_pct'])
        gains = sum(indexed['CCP', c]['attack_success'] and not indexed['S6', c]['attack_success'] for c in selected)
        losses = sum(indexed['S6', c]['attack_success'] and not indexed['CCP', c]['attack_success'] for c in selected)
        assert gains == saved['CCP_only_success'] and losses == saved['S6_only_success']
        delta = 100 * (gains - losses) / len(selected)
        assert math.isclose(delta, saved['CCP_minus_S6_asr_percentage_points'], abs_tol=1e-12)
        discordant = gains + losses
        p = min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(gains, losses) + 1)) / 2 ** discordant) if discordant else 1.0
        assert math.isclose(p, saved['mcnemar_exact_two_sided_p'])
    overall = summary['groups']['overall']
    s6 = overall['arms']['S6']['attack_successes']
    ccp = overall['arms']['CCP']['attack_successes']
    retained = {c for c in cases if not (c[0] == 'travel' and c[2] == 'injection_task_6')}
    assert len(retained) == 369
    sensitivity = {arm: sum(indexed[arm, c]['attack_success'] for c in retained) for arm in ('S6', 'CCP')}
    print(f'PASS {name}: 389 pairs / 778 episodes, native S6={s6}/389 CCP={ccp}/389; '
          f'excluding travel goal 6: S6={sensitivity["S6"]}/369 CCP={sensitivity["CCP"]}/369')


if __name__ == '__main__':
    for model, folder in RUNS.items():
        verify(model, ROOT / 'results' / folder)
    print('PASS: published per-episode records and summaries agree. Raw traces are not included.')
