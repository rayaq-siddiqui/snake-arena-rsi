# RSI run: snake:trapper

- proposer: `gaussian_hill_climb`; rule: `PairedBootstrapRule` (min gain 2%, 10,000 bootstrap resamples)
- run seed 1240441715; framework v1, code c1faa27590837b50
- generations: 3; accepted: 1; stopped by: generation budget
- episodes used: 1,200

## Final check (champion vs generation-0 baseline on the final seeds)

Mean score 0.128 vs 0.075 over 200 seeds: difference +0.053, 95% CI [+0.024, +0.087], 0 failures.

## Champion parameters

| parameter | baseline | champion |
|---|---|---|
| w_immediate_death | -1000 | -1000 |
| space_cap | 60 | 60 |
| search_radius | 12 | 12 |
| trap_margin | 2 | 2 |
| keep_distance | 3 | 2 |
| keep_repel | 1 | 1 |
| pull_radius | 15 | 15 |
| random_tiebreak | 1 | 1 |
| w_head_on_risk | -40 | -40 |
| w_territory | 20 | 20 |
| w_space | 6 | 4.897 |
| w_space_vs_length | 20 | 20 |
| w_enemy_space_after | -15 | -15 |
| w_enemy_escape_moves | -10 | -10 |
| w_nearest_enemy_head | -20 | -20 |
| w_straightness | 0.01 | 0.01 |
| w_cut_off | 4 | 4 |

## Decisions

| gen | candidate | stage | dev diff | holdout diff | holdout CI | accepted | why |
|---|---|---|---|---|---|---|---|
| 1 | 7c8846aa | dev | -0.008 | - | - | no | dev mean difference -0.008 is not above 0 |
| 2 | 551fa9fc | holdout | +0.024 | +0.016 | [-0.003, +0.035] | no | holdout gain +22.9%, 95% CI [-0.003, +0.035]: interval reaches 0 |
| 3 | abd1a3ca | holdout | +0.052 | +0.072 | [+0.026, +0.13] | yes | accepted: holdout gain +100.0%, 95% CI [+0.026, +0.13] |
