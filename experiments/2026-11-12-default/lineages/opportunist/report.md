# RSI run: snake:opportunist

- proposer: `gaussian_hill_climb`; rule: `PairedBootstrapRule` (min gain 2%, 10,000 bootstrap resamples)
- run seed 143402694; framework v1, code c1faa27590837b50
- generations: 4; accepted: 0; stopped by: no accept in 4 generations
- episodes used: 1,400

## Final check (champion vs generation-0 baseline on the final seeds)

Nothing was accepted; the champion is still the baseline.

## Champion parameters

| parameter | baseline | champion |
|---|---|---|
| w_immediate_death | -1000 | -1000 |
| space_cap | 60 | 60 |
| search_radius | 12 | 12 |
| trap_margin | 2 | 2 |
| keep_distance | 4 | 4 |
| keep_repel | 1 | 1 |
| pull_radius | 15 | 15 |
| random_tiebreak | 1 | 1 |
| attack_threshold | 1 | 1 |
| cruise_head_on_risk | -100 | -100 |
| cruise_territory | 30 | 30 |
| cruise_space | 15 | 15 |
| cruise_space_vs_length | 30 | 30 |
| cruise_nearest_enemy_head | -20 | -20 |
| cruise_straightness | 0.01 | 0.01 |
| attack_head_on_risk | -40 | -40 |
| attack_territory | 20 | 20 |
| attack_space | 6 | 6 |
| attack_space_vs_length | 20 | 20 |
| attack_nearest_enemy_head | -10 | -10 |
| attack_enemy_escape_moves | -20 | -20 |
| attack_enemy_space_after | -10 | -10 |
| attack_cut_off | 10 | 10 |

## Decisions

| gen | candidate | stage | dev diff | holdout diff | holdout CI | accepted | why |
|---|---|---|---|---|---|---|---|
| 1 | 9d6e7bc6 | holdout | +0.008 | +0.03 | [+0.012, +0.05] | no | holdout gain +375.0%, 95% CI [+0.012, +0.05]; guard worse: ['self_wall_deaths'] |
| 2 | 7ecdc02d | holdout | +0.002 | +0 | [+0, +0] | no | holdout gain +0.0%, 95% CI [+0, +0]: below the 2% minimum gain |
| 3 | 42431600 | dev | +0 | - | - | no | dev mean difference +0 is not above 0 |
| 4 | 660a2782 | holdout | +0.01 | +0 | [-0.01, +0.01] | no | holdout gain +0.0%, 95% CI [-0.01, +0.01]: below the 2% minimum gain |
